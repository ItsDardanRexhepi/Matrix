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
from runtime.blockchain.services.staking.pools import StakingPoolManager

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

        pool = await self._pools.get_pool(pool_id)
        pool_min = float(pool.get("min_stake", self._min_stake))

        key = (staker, pool_id)
        position = self._positions.get(key)

        if position is None:
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
            self._positions[key] = position

        # Accrue pending rewards before changing stake
        await self._accrue_rewards(position, pool)

        position["staked_amount"] += amount
        position["last_staked_at"] = int(time.time())

        # Update pool totals
        await self._pools.add_stake(pool_id, amount)

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
            Updated position record.
        """
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

        position["staked_amount"] -= amount
        position["last_unstaked_at"] = int(time.time())

        await self._pools.remove_stake(pool_id, amount)

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
            Claim record with gross/net amounts.
        """
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
        """Get staking position for a staker in a pool."""
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
