"""
StakingService — staking infrastructure for the 0pnMatrx platform.

5 % FLAT commission on all staking rewards (platform takes 5 %, staker
gets 95 %).  1 ETH MINIMUM stake requirement.  Commission goes to
platform_wallet from config.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.staking.apy_calculator import APYCalculator
from runtime.blockchain.services.staking.arming import (
    resolve_staking_contract,
    staking_not_deployed,
)
from runtime.blockchain.services.staking.pools import StakingPoolManager
from runtime.blockchain.web3_manager import Web3Manager

logger = logging.getLogger(__name__)

_COMMISSION_PCT = 5.0       # 5 % flat
_MIN_STAKE_ETH = 1.0        # 1 ETH minimum


class StakingService:
    """Main staking service.

    Config keys (under ``config["staking"]``):
        commission_pct (float): Platform commission on rewards (default 5).
        min_stake (float): Minimum stake in ETH (default 1).

    Config keys (under ``config["blockchain"]``):
        platform_wallet (str): Address receiving commission.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        s_cfg: dict[str, Any] = config.get("staking", {})
        bc_cfg: dict[str, Any] = config.get("blockchain", {})

        self._commission_pct: float = float(
            s_cfg.get("commission_pct", _COMMISSION_PCT)
        )
        self._min_stake: float = float(
            s_cfg.get("min_stake", _MIN_STAKE_ETH)
        )
        self._platform_wallet: str = bc_cfg.get("platform_wallet", "")
        # NEW-94: resolution moved to arming.py so all three staking classes
        # gate on the SAME address. Behaviour is unchanged — the helper is the
        # former inline expression, extracted verbatim.
        self._staking_contract: str = resolve_staking_contract(config)
        self._web3 = Web3Manager.get_shared(config)

        self._apy = APYCalculator(config)
        self._pools = StakingPoolManager(config)

        # (staker, pool_id) -> position record
        self._positions: dict[tuple[str, str], dict[str, Any]] = {}
        # Commission ledger
        self._commissions: list[dict[str, Any]] = []

        logger.info(
            "StakingService initialised (commission=%.1f%%, min_stake=%.2f ETH).",
            self._commission_pct, self._min_stake,
        )

    @property
    def apy_calculator(self) -> APYCalculator:
        return self._apy

    @property
    def pools(self) -> StakingPoolManager:
        return self._pools

    # ------------------------------------------------------------------
    # Core staking operations
    # ------------------------------------------------------------------

    async def stake(
        self,
        staker: str,
        amount: float,
        pool_id: str = "default",
    ) -> dict:
        """Stake tokens into a pool.

        Args:
            staker: Address of the staker.
            amount: Amount to stake (must be >= min_stake for new positions).
            pool_id: Target pool (default "default").

        Returns:
            Updated position record.
        """
        if amount <= 0:
            raise ValueError("Stake amount must be positive")

        # NEW-94: the gate that used to be written out here is now the shared
        # domain gate. Same web3, same contract, same polarity — the only
        # change is that fourteen sibling methods now use it too.
        refusal = staking_not_deployed(
            self._web3, self._staking_contract, "stake",
            {"staker": staker, "amount": amount, "pool_id": pool_id},
        )
        if refusal is not None:
            return refusal

        pool = await self._pools.get_pool(pool_id)
        pool_min = float(pool.get("min_stake", self._min_stake))

        key = (staker, pool_id)
        position = self._positions.get(key)
        is_new = position is None

        if is_new:
            # New position: enforce minimum
            if amount < pool_min:
                raise ValueError(
                    f"Minimum stake is {pool_min} ETH, got {amount}"
                )
            now = int(time.time())
            position = {
                "staker": staker,
                "pool_id": pool_id,
                "staked_amount": 0.0,
                "pending_rewards": 0.0,
                "total_rewards_earned": 0.0,
                "total_commission_paid": 0.0,
                "staked_at": now,
                "last_reward_at": now,
            }
            # NOT published to self._positions yet — see the ordering note below.

        # Accrue pending rewards before changing stake
        await self._accrue_rewards(position, pool)

        # ORDERING, forced by NEW-94. `add_stake` can now refuse, so the pool
        # accounting is attempted BEFORE the position is credited or published.
        # The old order credited the position first and discarded whatever
        # `add_stake` returned; with a refusable callee that would leave a
        # staker holding a balance the pool never recorded — a partial state
        # nothing downstream could detect. The refusal is bound and checked
        # rather than discarded (D10).
        # NEW-95: `new_staker` is passed because only the service knows whether
        # this stake OPENS a position. The counter used to increment on every
        # call, so one address staking three times counted as three stakers.
        pool_update = await self._pools.add_stake(
            pool_id, amount, new_staker=is_new,
        )
        if pool_update is not None:
            return pool_update

        if is_new:
            self._positions[key] = position

        position["staked_amount"] += amount
        position["last_staked_at"] = int(time.time())

        logger.info(
            "Staked: staker=%s pool=%s amount=%.6f total=%.6f",
            staker, pool_id, amount, position["staked_amount"],
        )
        return self._sanitize_position(position)

    async def unstake(
        self,
        staker: str,
        amount: float,
        pool_id: str = "default",
    ) -> dict:
        """Unstake tokens from a pool.

        Args:
            staker: Address of the staker.
            amount: Amount to unstake.
            pool_id: Pool to unstake from.

        Returns:
            Updated position record, or an honest refusal while undeployed.
        """
        # NEW-94. Gated ahead of the position lookup, so an undeployed domain
        # refuses without first disclosing whether a position exists.
        refusal = staking_not_deployed(
            self._web3, self._staking_contract, "unstake",
            {"staker": staker, "amount": amount, "pool_id": pool_id},
        )
        if refusal is not None:
            return refusal

        key = (staker, pool_id)
        position = self._positions.get(key)
        if not position:
            raise ValueError(f"No staking position found for {staker} in pool {pool_id}")
        if amount <= 0:
            raise ValueError("Unstake amount must be positive")
        if amount > position["staked_amount"]:
            raise ValueError(
                f"Cannot unstake {amount}; only {position['staked_amount']} staked"
            )

        pool = await self._pools.get_pool(pool_id)

        # Check lock period
        lock_period = int(pool.get("lock_period", 0))
        if lock_period > 0:
            elapsed = int(time.time()) - position.get("staked_at", 0)
            if elapsed < lock_period:
                remaining = lock_period - elapsed
                raise ValueError(
                    f"Lock period not elapsed. {remaining}s remaining."
                )

        # Accrue rewards before unstaking
        await self._accrue_rewards(position, pool)

        # ORDERING, forced by NEW-94 — the mirror of the note in `stake`.
        # `remove_stake` can now refuse, so the pool accounting is attempted
        # before the position is debited. Bound and checked, not discarded (D10).
        # NEW-95: `staker_exited` mirrors the cleanup condition below, computed
        # before the debit so the pool counter and the position store agree.
        # `_accrue_rewards` has already run, so pending_rewards is final here.
        will_exit = (
            (position["staked_amount"] - amount) <= 0
            and position["pending_rewards"] <= 0
        )
        pool_update = await self._pools.remove_stake(
            pool_id, amount, staker_exited=will_exit,
        )
        if pool_update is not None:
            return pool_update

        position["staked_amount"] -= amount
        position["last_unstaked_at"] = int(time.time())

        # Clean up empty positions
        if position["staked_amount"] <= 0 and position["pending_rewards"] <= 0:
            del self._positions[key]

        logger.info(
            "Unstaked: staker=%s pool=%s amount=%.6f",
            staker, pool_id, amount,
        )
        return self._sanitize_position(position)

    async def claim_rewards(
        self,
        staker: str,
        pool_id: str = "default",
    ) -> dict:
        """Claim pending staking rewards.

        The platform takes a 5 % flat commission on rewards.
        Staker receives 95 %.

        Args:
            staker: Address of the staker.
            pool_id: Pool to claim from.

        Returns:
            Claim record with gross/net amounts, or an honest refusal while
            undeployed.
        """
        # NEW-94.
        refusal = staking_not_deployed(
            self._web3, self._staking_contract, "claim_rewards",
            {"staker": staker, "pool_id": pool_id},
        )
        if refusal is not None:
            return refusal

        key = (staker, pool_id)
        position = self._positions.get(key)
        if not position:
            raise ValueError(
                f"No staking position found for {staker} in pool {pool_id}"
            )

        pool = await self._pools.get_pool(pool_id)
        await self._accrue_rewards(position, pool)

        gross = position["pending_rewards"]
        if gross <= 0:
            return {
                "status": "no_rewards",
                "staker": staker,
                "pool_id": pool_id,
                "gross_reward": 0.0,
                "commission": 0.0,
                "net_reward": 0.0,
            }

        commission = gross * (self._commission_pct / 100.0)
        net = gross - commission

        position["pending_rewards"] = 0.0
        position["total_rewards_earned"] += gross
        position["total_commission_paid"] += commission
        position["last_claimed_at"] = int(time.time())

        # Record commission
        self._commissions.append({
            "staker": staker,
            "pool_id": pool_id,
            "gross_reward": round(gross, 6),
            "commission": round(commission, 6),
            "net_reward": round(net, 6),
            "platform_wallet": self._platform_wallet,
            "timestamp": int(time.time()),
        })

        logger.info(
            "Rewards claimed: staker=%s pool=%s gross=%.6f commission=%.6f net=%.6f",
            staker, pool_id, gross, commission, net,
        )
        return {
            "status": "claimed",
            "staker": staker,
            "pool_id": pool_id,
            "gross_reward": round(gross, 6),
            "commission": round(commission, 6),
            "commission_pct": self._commission_pct,
            "net_reward": round(net, 6),
            "platform_wallet": self._platform_wallet,
        }

    async def get_position(
        self,
        staker: str,
        pool_id: str = "default",
    ) -> dict:
        """Get staking position for a staker in a pool.

        GATED, AND THIS IS THE COUNTEREXAMPLE THAT SHAPES THE WHOLE DOMAIN.

        NEW-94 exempts five methods from the staking gate. The exemption is an
        ENUMERATED LIST rather than the rule "reads are safe", and the reason is
        this method: eight lines down it calls ``self._accrue_rewards``, which
        credits ``pending_rewards`` from elapsed wall-clock time. A method whose
        name promises a read MINTS BALANCE as a side effect of being called.
        Poll it in a loop and the position grows, with no stake, no claim, and
        no caller intent beyond "show me my position".

        So the read/write distinction is not a safety boundary in this
        codebase, and ``get_position`` is the proof. If you are adding
        ``get_rewards_preview()`` and reasoning "it's a getter, getters are
        safe" — that reasoning is what this docstring exists to stop. Put the
        new method on ``STAKING_GATED`` or on ``STAKING_UNGATED_READS`` in
        arming.py after reading its body; the structural test in
        tests/test_staking_arming.py will not let you skip the choice.

        Returns:
            Position record, or an honest refusal while undeployed.
        """
        refusal = staking_not_deployed(
            self._web3, self._staking_contract, "get_position",
            {"staker": staker, "pool_id": pool_id},
        )
        if refusal is not None:
            return refusal

        key = (staker, pool_id)
        position = self._positions.get(key)
        if not position:
            return {
                "staker": staker,
                "pool_id": pool_id,
                "staked_amount": 0.0,
                "pending_rewards": 0.0,
                "status": "no_position",
            }

        pool = await self._pools.get_pool(pool_id)
        await self._accrue_rewards(position, pool)

        result = self._sanitize_position(position)

        # Include APY info
        apy_data = await self._apy.calculate_apy(pool_id)
        result["current_apy"] = apy_data.get("current_apy", 0.0)

        return result

    # ------------------------------------------------------------------
    # Reward accrual
    # ------------------------------------------------------------------

    async def _accrue_rewards(
        self, position: dict[str, Any], pool: dict[str, Any],
    ) -> None:
        """Accrue rewards for a position based on time elapsed."""
        now = int(time.time())
        last = position.get("last_reward_at", now)
        elapsed = max(0, now - last)

        if elapsed == 0 or position["staked_amount"] <= 0:
            return

        reward_rate = float(pool.get("reward_rate", 0.0))
        total_staked = float(pool.get("total_staked", 1.0))

        if total_staked <= 0:
            return

        # Pro-rata share of pool rewards
        share = position["staked_amount"] / total_staked
        period_rewards = reward_rate * (elapsed / 86400.0)  # daily rate
        earned = period_rewards * share

        position["pending_rewards"] += earned
        position["last_reward_at"] = now

    @staticmethod
    def _sanitize_position(position: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of the position with rounded floats."""
        return {
            k: round(v, 6) if isinstance(v, float) else v
            for k, v in position.items()
        }
