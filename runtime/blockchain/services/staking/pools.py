"""
StakingPool management — create, configure, and query staking pools.

Pool configs: reward_token, reward_rate, lock_period, min_stake.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.staking.arming import (
    resolve_staking_contract,
    staking_not_deployed,
)
from runtime.blockchain.web3_manager import Web3Manager

logger = logging.getLogger(__name__)

_DEFAULT_POOL: dict[str, Any] = {
    "pool_id": "default",
    "name": "Default Staking Pool",
    "reward_token": "ETH",
    "reward_rate": 0.1,       # tokens per day emitted to pool
    "lock_period": 0,         # seconds; 0 = no lock
    "min_stake": 1.0,         # 1 ETH minimum
    "total_staked": 0.0,
    "staker_count": 0,
    "status": "active",
    "created_at": 0,
}


class StakingPoolManager:
    """Manages staking pools.

    Config keys (under ``config["staking"]``):
        default_reward_rate (float): Default daily reward emission.
        default_lock_period (int): Default lock period in seconds.
        min_stake (float): Default minimum stake (1 ETH).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        s_cfg = config.get("staking", {})

        self._default_reward_rate: float = float(
            s_cfg.get("default_reward_rate", 0.1)
        )
        self._default_lock: int = int(s_cfg.get("default_lock_period", 0))
        self._min_stake: float = float(s_cfg.get("min_stake", 1.0))

        # NEW-94: the whole staking domain arms on one switch. See arming.py.
        self._web3 = Web3Manager.get_shared(config)
        self._staking_contract: str = resolve_staking_contract(config)

        # pool_id -> pool record
        self._pools: dict[str, dict[str, Any]] = {}

        # Ensure default pool exists.
        # NOT gated: this seeds an in-memory CONFIG record (rate, lock period,
        # minimum) at construction. It claims no balance and asserts no
        # outcome — `total_staked` and `staker_count` start at zero. The
        # methods that would move those numbers are gated below.
        default = dict(_DEFAULT_POOL)
        default["reward_rate"] = self._default_reward_rate
        default["lock_period"] = self._default_lock
        default["min_stake"] = self._min_stake
        default["created_at"] = int(time.time())
        self._pools["default"] = default

    async def create_pool(self, config: dict) -> dict:
        """Create a new staking pool.

        Args:
            config: Dict with ``name``, ``reward_token``, ``reward_rate``,
                    ``lock_period``, ``min_stake``.

        Returns:
            Created pool record, or an honest refusal while undeployed.
        """
        # NEW-94. This method is the staking domain's single D6 entry: mint a
        # uuid, write it to a store, assert ``status: "active"``, await
        # nothing. A pool that is "active" on no chain is the assertion D6
        # exists to catch, and it was ungated.
        refusal = staking_not_deployed(
            self._web3, self._staking_contract, "create_pool",
            {"requested_pool_id": config.get("pool_id")},
        )
        if refusal is not None:
            return refusal

        pool_id = config.get("pool_id", f"pool_{uuid.uuid4().hex[:12]}")
        if pool_id in self._pools:
            raise ValueError(f"Pool {pool_id} already exists")

        now = int(time.time())
        pool: dict[str, Any] = {
            "pool_id": pool_id,
            "name": config.get("name", f"Pool {pool_id}"),
            "reward_token": config.get("reward_token", "ETH"),
            "reward_rate": float(config.get("reward_rate", self._default_reward_rate)),
            "lock_period": int(config.get("lock_period", self._default_lock)),
            "min_stake": float(config.get("min_stake", self._min_stake)),
            "total_staked": 0.0,
            "staker_count": 0,
            "status": "active",
            "created_at": now,
        }
        self._pools[pool_id] = pool

        logger.info(
            "Pool created: id=%s name=%s rate=%.6f lock=%ds",
            pool_id, pool["name"], pool["reward_rate"], pool["lock_period"],
        )
        return pool

    async def get_pool(self, pool_id: str) -> dict:
        """Retrieve a pool by ID."""
        pool = self._pools.get(pool_id)
        if not pool:
            raise ValueError(f"Pool {pool_id} not found")
        return pool

    async def list_pools(self) -> list:
        """List all staking pools."""
        return list(self._pools.values())

    async def add_stake(
        self, pool_id: str, amount: float, *, new_staker: bool = False,
    ) -> dict | None:
        """Record additional stake in pool totals.

        Parameters
        ----------
        new_staker : bool
            True only when this stake OPENS a position. NEW-95: the counter
            used to increment on every call, so one address staking three
            times counted as three stakers. The caller is the only party that
            knows whether a position is new, so it must say.

        Returns ``None`` on success, or an honest refusal while undeployed.
        The return type changed from ``None`` under NEW-94 so the refusal can
        reach the caller; callers must bind and check it (D10).
        """
        refusal = staking_not_deployed(
            self._web3, self._staking_contract, "add_stake",
            {"pool_id": pool_id, "amount": amount},
        )
        if refusal is not None:
            return refusal

        if amount <= 0:
            raise ValueError(f"Stake amount must be positive, got {amount}")

        pool = self._require_pool(pool_id)
        pool["total_staked"] += amount
        if new_staker:
            pool["staker_count"] = pool.get("staker_count", 0) + 1
        return None

    async def remove_stake(
        self, pool_id: str, amount: float, *, staker_exited: bool = False,
    ) -> dict | None:
        """Record removed stake in pool totals.

        NEW-95. Three defects lived here, and the first is the serious one.

        1. AN UNVALIDATED SIGN TURNED A WITHDRAWAL INTO A DEPOSIT.
           `total_staked = max(0.0, total_staked - amount)` with a negative
           `amount` ADDS. Driven against the live object: 10.0 staked,
           `remove_stake(pool, -20.0)` -> total_staked 30.0. The withdrawal
           path was a deposit path for anyone who could reach it with a
           negative number, and nothing anywhere would contradict the result.

        2. OVER-WITHDRAWAL WAS SILENTLY ABSORBED. `max(0.0, ...)` clamped
           `remove_stake(pool, 100.0)` against 10.0 staked to 0.0 and returned
           normally. The pool then disagreed with the sum of its positions with
           no error, no log and no way to notice. Clamping is not a check; it
           is a check's silence. The `max(0.0, ...)` retained below is now a
           FLOAT-DRIFT FLOOR only — the real check precedes it and raises.

        3. `staker_count` NEVER DECREMENTED. It is now decremented when the
           caller says the position closed. It is written here and read by no
           non-test code in this repo or the iOS client — so this is a
           correctness fix to a PUBLISHED FIELD (it ships inside every
           `get_pool`/`list_pools` record), not to a live denominator.

        Returns ``None`` on success, or an honest refusal while undeployed.
        """
        refusal = staking_not_deployed(
            self._web3, self._staking_contract, "remove_stake",
            {"pool_id": pool_id, "amount": amount},
        )
        if refusal is not None:
            return refusal

        if amount <= 0:
            raise ValueError(
                f"Unstake amount must be positive, got {amount}. A negative "
                "amount here previously INCREASED total_staked."
            )

        pool = self._require_pool(pool_id)

        # Tolerance, not slack. `total_staked` and the sum of positions are
        # updated from the same figures, so they can differ only by float
        # representation error — but that error is RELATIVE TO MAGNITUDE, and
        # the two quantities do not accumulate in the same order: the pool
        # total sums every staker's deposits chronologically while a position
        # sums only its own.
        #
        # THE FIRST VERSION OF THIS CHECK USED A FIXED 1e-9 AND WAS A
        # REGRESSION. An absolute epsilon against an unbounded quantity binds
        # at scale: adversarial review drove 300 single-deposit stakers through
        # the real service, and above a pool peak of roughly 1e6 the LAST
        # staker out was refused a withdrawal of the exact balance
        # `get_position` had just reported them — a call that could not raise
        # at all before NEW-95. The failure lands on an honest staker, whose
        # only workaround is to guess a smaller number and strand dust.
        #
        # A relative floor tracks the error it exists to absorb. The absolute
        # term keeps it meaningful for small pools, where 1e-12 of the total
        # would be narrower than a single ULP.
        tolerance = max(1e-9, abs(pool["total_staked"]) * 1e-12)
        if amount > pool["total_staked"] + tolerance:
            raise ValueError(
                f"Cannot remove {amount} from pool {pool_id}; only "
                f"{pool['total_staked']} is staked"
            )

        # Load-bearing: an amount within `tolerance` of the total is allowed
        # above, so the subtraction can land a few ULPs below zero. This floors
        # exactly that residual — it no longer absorbs over-withdrawal, which
        # now raises before reaching here.
        pool["total_staked"] = max(0.0, pool["total_staked"] - amount)
        if staker_exited:
            pool["staker_count"] = max(0, pool.get("staker_count", 0) - 1)
        return None

    def _require_pool(self, pool_id: str) -> dict[str, Any]:
        """NEW-95: a missing pool was a silent no-op.

        `if pool:` meant `add_stake`/`remove_stake` on an unknown pool returned
        normally having done nothing, so a caller could credit a position
        against a pool that does not exist and see no error. `get_pool` already
        raises for the same input; these now agree with it.
        """
        pool = self._pools.get(pool_id)
        if pool is None:
            raise ValueError(f"Pool {pool_id} not found")
        return pool
