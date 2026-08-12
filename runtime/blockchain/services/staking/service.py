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


# ══════════════════════════════════════════════════════════════════════════
# STAKING ARMING CONDITION                                          (NEW-98)
# ══════════════════════════════════════════════════════════════════════════
#
# ONE KEY ARMS THIS WHOLE DOMAIN. Setting `staking.staking_contract` (or
# `blockchain.staking_contract`) flips all eight gated methods at once — see
# arming.py. That is deliberate: a domain that arms per-method is what NEW-94
# found and removed. It also means this comment is the only thing standing
# between a configuration change and everything below.
#
# DO NOT SET THAT KEY UNTIL EVERY CLAUSE BELOW HOLDS.
#
# Each clause states its own PARTIAL-STATE FAILURE MODE, because seven
# requirements without per-clause consequences invite exactly the incremental
# arming they exist to prevent — someone satisfies three, ships, and the other
# four become "known issues".
#
# ──────────────────────────────────────────────────────────────────────────
# CLAUSE 1 — REWARDS HAVE A DEMONSTRATED FUNDED SOURCE.
#   `_accrue_rewards` computes a real time-weighted pro-rata share from
#   `pool["reward_rate"]`, a pool-creation PARAMETER. There is no treasury, no
#   balance and no payer anywhere in this domain. The accrual therefore creates
#   a balance out of a configuration value, compounding with wall-clock time,
#   with nothing on the other side of the ledger.
#   REQUIRED: a real balance the accrual draws against, and a check that FAILS
#   CLOSED when it cannot cover. Not "a treasury exists" — the accrual must
#   READ it and REFUSE when insufficient.
#   PARTIAL-STATE FAILURE MODE: armed with the accrual unfunded, the first
#   honest thing this service does is calculate a debt. Every staker holds a
#   growing claim the platform never agreed to and cannot pay, and the number
#   grows whether or not anyone ever calls anything — `get_position` alone
#   mints it.
#   THIS IS THE CLAUSE THAT DISTINGUISHES THIS DOMAIN. A royalty split
#   (NEW-91) DESCRIBES a payment someone else could make; recording a
#   description costs nothing if nobody acts on it. An accrual CREATES an
#   obligation, and an obligation is a debt whether or not anyone acts on it.
#
# CLAUSE 2 — `staker` IS BOUND TO AN AUTHENTICATED CALLER IDENTITY.
#   Every method here takes `staker` as a plain string parameter and trusts it.
#   WORKED EXAMPLE, driven during the census: an unrelated caller ran
#   `unstake(staker="0xbob", amount=40.0)`, cut bob's stake from 100 to 60, and
#   received bob's full position record in the response. No authentication, no
#   ownership check, no error.
#   REQUIRED: `staker` derived from the authenticated request principal, never
#   accepted from the caller.
#   PARTIAL-STATE FAILURE MODE: armed with a caller-supplied `staker`, the
#   domain is a withdrawal API for other people's positions. Everything else in
#   this condition is irrelevant if this one is unmet.
#   SCOPE: the root is the dispatcher's missing identity binding — DEFERRED
#   REGISTER ITEM 0 (NEW-82). This clause is that item's worked example with a
#   dollar amount attached, and it is NOT solved inside this domain.
#
# CLAUSE 3 — POSITION STATE IS READ FROM CHAIN, NOT FROM `_positions`.
#   `self._positions` is a process-local dict. It is not durable, not shared
#   between instances, and has no relationship to any on-chain staking state.
#   REQUIRED: balances and reward state read from the deployed contract.
#   PARTIAL-STATE FAILURE MODE: armed while reading `_positions`, two gateway
#   processes disagree about every balance, a restart erases every position,
#   and the contract's view — the only one that governs money — is never
#   consulted. Note the interaction with clause 1: an unfunded accrual stored
#   in a volatile dict is a debt that also cannot be audited.
#
# CLAUSE 4 — THE POOL-ACCOUNTING CORRECTIONS ARE IN PLACE (NEW-95).
#   `remove_stake` treated a negative amount as a deposit (10.0 staked,
#   `remove_stake(-20.0)` -> total 30.0) and silently absorbed over-withdrawal.
#   Both are fixed; this clause exists so a REVERT cannot precede an arming.
#   REQUIRED: tests/test_staking_pool_accounting.py green at arming time.
#   PARTIAL-STATE FAILURE MODE: arming is exactly what makes the sign bug
#   reachable with real money. Unarmed it moves a number in a dict; armed it is
#   a withdrawal endpoint that mints.
#
# CLAUSE 5 — `create_pool`'s STATUS IS DERIVED FROM A RECEIPT.
#   It mints a uuid, writes a dict and asserts `status: "active"` having
#   awaited nothing — the staking domain's single D6 entry.
#   REQUIRED: status derived from a transaction receipt, as
#   `runtime/blockchain/staking.py::_claim_rewards` already does
#   (`"claimed" if receipt["status"] == 1 else "failed"`). The correct pattern
#   is in this repo; it does not need inventing.
#   PARTIAL-STATE FAILURE MODE: a pool reported "active" on no chain, which
#   every downstream reader treats as a place to put money.
#
# CLAUSE 6 — `unstake` DOES NOT RETURN A RECORD FOR A POSITION IT DELETED.
#   It deletes `self._positions[key]` when the position closes and then returns
#   `_sanitize_position(position)` — a full record describing state that no
#   longer exists, built from a local reference that outlived the store entry.
#   REQUIRED: return a settlement receipt, or an explicit closed-position
#   response; not a snapshot of a deleted record.
#   PARTIAL-STATE FAILURE MODE: on a real deployment that response is a
#   receipt for something unverifiable — the caller is handed numbers that
#   cannot be re-read from any store, so a dispute has nothing to check.
#
# CLAUSE 7 — THE FEED SURFACES ARE RE-DERIVED AT ARMING TIME.
#   The feed's current honesty is ACCIDENTAL. `SocialFeedEngine.ingest`
#   resolves `ACTION_LABELS.get(action, f"performed {action}")` with the
#   dispatcher's ACTION name, while `ACTION_LABELS` is keyed by short
#   METHOD-style names — three key vocabularies meet in that map (the labels'
#   own keys, the action names, and `r["event_type"]` at the render site). Most
#   lookups MISS, so most labels fall through to "performed <action>", which
#   happens to be truthful. `ACTION_TO_FEED_EVENT` likewise has no reader.
#   REQUIRED: at arming, re-derive what this domain's actions actually publish,
#   by driving the emission rather than reading the tables.
#   PARTIAL-STATE FAILURE MODE: this is the arming-dead-machinery hazard
#   applied to a label table. Repairing the key mismatch ships every stale
#   label at once, converting silent truth into loud falsehood in one commit —
#   so THE AUDIT OF THE LABEL TABLE MUST PRECEDE THE REPAIR OF ITS KEYS, never
#   the other way round. Tracked as a Phase-6 sweep with that ordering.
#
# ──────────────────────────────────────────────────────────────────────────
# LIFTING CONDITION: all seven, together. Clause 2's root is deferred register
# item 0 and is not this domain's to close.
# ══════════════════════════════════════════════════════════════════════════


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

        # NEW-96: the pool manager is created FIRST and handed to the
        # calculator. Order is load-bearing — the calculator now requires it,
        # and before this the calculator built its own, so the APY was computed
        # from an empty pool while the service held the real totals.
        self._pools = StakingPoolManager(config)
        self._apy = APYCalculator(config, self._pools)

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
                "total_commission_recorded": 0.0,   # NEW-97, was ..._paid
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
        # NEW-97: `total_commission_paid` -> `total_commission_recorded`. This
        # is the NEW-91 `total_royalties_paid` shape in a SECOND domain: the
        # word "paid" over a running total this service computed for itself,
        # with no wallet, balance or payout anywhere to reconcile it against.
        # Recorded as a repeat instance rather than a fresh discovery.
        position["total_commission_recorded"] += commission
        position["last_claimed_at"] = int(time.time())

        # Record commission. NEW-97: the entry names a `platform_wallet` and
        # nothing was ever sent to it, so the disclosure lives on the record —
        # a reader of `self._commissions` must not mistake a computed split for
        # a transfer.
        self._commissions.append({
            "staker": staker,
            "pool_id": pool_id,
            "gross_reward": round(gross, 6),
            "commission": round(commission, 6),
            "net_reward": round(net, 6),
            "platform_wallet": self._platform_wallet,
            "timestamp": int(time.time()),
            "settled": False,
            "value_moved": False,
            "disclosure": (
                "NOT SETTLED. Commission computed and recorded locally. No "
                "transfer was made to the platform wallet and none to the "
                "staker."
            ),
        })

        logger.info(
            "Rewards RECORDED (NOT paid — no value moved): staker=%s pool=%s "
            "gross=%.6f commission=%.6f net=%.6f",
            staker, pool_id, gross, commission, net,
        )
        return {
            # NEW-97. "claimed" means the staker received the rewards. Nothing
            # was transferred: this method zeroes a counter it maintains itself
            # and appends a line item. The 4-vs-6 discriminator says vocabulary
            # rather than removal — strip the outcome claim and the time-
            # weighted accrual, the 5% split and the ledger all remain, and all
            # three are real arithmetic.
            #
            # THE CORRECT PATTERN ALREADY EXISTS IN THIS REPO, in a method of
            # the same name: `runtime/blockchain/staking.py::_claim_rewards`
            # builds a transaction, signs it, sends it, waits for a receipt and
            # returns `"claimed" if receipt["status"] == 1 else "failed"` —
            # status DERIVED from settlement. Two `claim_rewards`, one real and
            # one recording-only, and only the real one earned the word.
            "status": "recorded_unsettled",
            "staker": staker,
            "pool_id": pool_id,
            "gross_reward": round(gross, 6),
            "commission": round(commission, 6),
            "commission_pct": self._commission_pct,
            "net_reward": round(net, 6),
            "platform_wallet": self._platform_wallet,
            "settled": False,
            "value_moved": False,
            "disclosure": (
                "RECORDED, NOT PAID. This service computed a reward split and "
                "cleared its own pending-rewards counter. No value was "
                "transferred to the staker or to the platform wallet, and the "
                "rewards themselves are accrued from a configured rate with no "
                "funded source behind them."
            ),
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

        # NEW-97: this response publishes `pending_rewards`,
        # `total_rewards_earned` and `total_commission_recorded` — every one of
        # them produced by `_accrue_rewards` from a configured rate with no
        # funded source. A reader seeing a rewards balance would reasonably
        # assume someone owes it to them; the disclosure says who does not.
        result["rewards_settled"] = False
        result["rewards_disclosure"] = (
            "Reward figures are ACCRUED, NOT FUNDED. They are computed from "
            "the pool's configured reward_rate and elapsed time. No treasury "
            "or balance backs them and no transfer has been made."
        )

        return result

    # ------------------------------------------------------------------
    # Reward accrual
    # ------------------------------------------------------------------

    async def _accrue_rewards(
        self, position: dict[str, Any], pool: dict[str, Any],
    ) -> None:
        """Accrue rewards for a position based on time elapsed.

        NEW-97 — THE ACCRUAL IS REAL AND THAT IS THE PROBLEM.

        The arithmetic below is a genuine time-weighted pro-rata computation:
        share of pool, daily rate, elapsed seconds. Apply the 4-vs-6
        discriminator — strip the outcome claim and ask what work is left — and
        everything is left, because there is no outcome claim to strip. This is
        category 6, not a fabrication.

        WHAT IS MISSING IS NOT THE COMPUTATION BUT THE FUNDED SOURCE.
        `reward_rate` is a pool-creation parameter. There is no treasury, no
        balance, and no payer anywhere in this domain. So this method CREATES A
        BALANCE OUT OF A CONFIGURATION VALUE, compounding with wall-clock time,
        with nothing on the other side of the ledger.

        That is a different thing from a royalty split, and the distinction is
        why the arming condition has a clause of its own: a split DESCRIBES a
        payment someone else could make, while an accrual CREATES an
        obligation. Recording a description costs nothing if it is never acted
        on. Recording an obligation is a debt whether or not anyone acts on it.

        NO STAKING METHOD MAY BE ARMED UNTIL REWARDS HAVE A DEMONSTRATED FUNDED
        SOURCE — a real balance the accrual draws against, and a check that
        FAILS CLOSED when it cannot cover. Not "a treasury exists", but "the
        accrual reads it and refuses when it cannot cover". Otherwise the first
        honest thing this service does is calculate a debt. This clause belongs
        in the compound arming condition (item 4, not yet written); until then
        the NEW-94 domain gate is what keeps it dark.
        """
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
