"""
APYCalculator — CANONICAL APY calculator for the Matrix platform.

Component 20 (dashboard) uses this exclusively. Factors in total staked,
reward rate, and validator performance to compute APY.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

from runtime.blockchain.services.staking.arming import (
    resolve_staking_contract,
    staking_not_deployed,
)
from runtime.blockchain.web3_manager import Web3Manager

logger = logging.getLogger(__name__)

# Annualisation constant
_SECONDS_PER_YEAR = 365.25 * 86400

#: Reported APY ceiling, in percent. Unchanged from the `min(apy, 10_000.0)`
#: this replaces — only the point at which it is applied has moved.
_MAX_APY_PCT = 10_000.0
#: The same ceiling as a growth exponent, so it can bind BEFORE the
#: exponentiation instead of after it: exp(_CAP_LOG_GROWTH) - 1 == 100.0, the
#: growth multiple corresponding to _MAX_APY_PCT percent.
_CAP_LOG_GROWTH = math.log1p(_MAX_APY_PCT / 100.0)


class APYCalculator:
    """Canonical APY calculator for staking pools.

    This is the single source of truth for APY numbers across the
    platform.  Component 20 (dashboard) must use this calculator
    exclusively.

    Config keys (under ``config["staking"]``):
        validator_performance (float): 0..1 multiplier (default 0.95).
        compounding_frequency (int): compounds per year (default 365).
    """

    def __init__(self, config: dict, pool_manager: Any) -> None:
        """NEW-96: the pool manager is INJECTED and required.

        It used to be constructed inside `calculate_apy`, one throwaway per
        call, so the calculator read a pristine manager whose default pool has
        `total_staked: 0.0` while the service's real manager held the actual
        total. Two objects, same class, different state — and the APY was
        always computed from the empty one. `get_position` returned the real
        position and the shadow's yield in a single response.

        Required rather than optional: a default of `None` would let a caller
        construct a calculator that silently reads nothing, which is the
        defect restated as a convenience.
        """
        self._config = config
        self._pools = pool_manager
        s_cfg = config.get("staking", {})

        self._validator_perf: float = float(
            s_cfg.get("validator_performance", 0.95)
        )
        self._compounding: int = int(
            s_cfg.get("compounding_frequency", 365)
        )

        # Historical APY snapshots: pool_id -> [(timestamp, apy)]
        self._history: dict[str, list[tuple[int, float]]] = {}

        # NEW-94: the whole staking domain arms on one switch. See arming.py.
        self._web3 = Web3Manager.get_shared(config)
        self._staking_contract: str = resolve_staking_contract(config)

    async def calculate_apy(self, pool_id: str) -> dict:
        """Calculate current APY for a staking pool.

        Factors:
        - Total staked in pool (higher = lower per-unit reward)
        - Reward rate (tokens emitted per day)
        - Validator performance multiplier

        Returns:
            Dict with ``current_apy``, ``7d_avg``, ``30d_avg``,
            ``pool_id``, ``validator_performance``.
        """
        # NEW-94. Gated because it MUTATES: it appends a snapshot to
        # ``self._history``, which is what ``get_historical_apy`` later serves.
        # An undeployed domain that accumulates a history of yields it never
        # earned is manufacturing evidence.
        refusal = staking_not_deployed(
            self._web3, self._staking_contract, "calculate_apy",
            {"pool_id": pool_id},
        )
        if refusal is not None:
            return refusal

        # NEW-96: reads the SERVICE'S pool manager. The three lines this
        # replaces constructed a fresh StakingPoolManager per call and read its
        # pristine default pool, so `total_staked` was always 0.0 and the APY
        # always 0.0 with it.
        try:
            pool = await self._pools.get_pool(pool_id)
        except ValueError as exc:
            # Previously `except Exception: pool = {}`, which turned an unknown
            # pool into an APY of 0.0 — a NUMBER, indistinguishable from a real
            # yield of zero, and the caller had no way to tell. The swallow
            # existed to absorb the throwaway manager's failures; with the
            # manager injected it would only ever hide a genuine mistake.
            logger.warning("APY requested for unknown pool %s: %s", pool_id, exc)
            return {
                "status": "error",
                "pool_id": pool_id,
                "error": str(exc),
                "current_apy": None,
            }

        total_staked = float(pool.get("total_staked", 0))
        reward_rate = float(pool.get("reward_rate", 0))

        if total_staked <= 0 or reward_rate <= 0:
            apy = 0.0
        else:
            # Daily yield per unit staked
            daily_yield = reward_rate / total_staked

            # Apply validator performance
            daily_yield *= self._validator_perf

            # Compound APY.
            #
            # NEW-96: THIS ARITHMETIC HAD NEVER EXECUTED. While the shadow
            # forced `total_staked` to 0.0 on every call, the `<= 0`
            # short-circuit above fired every time and this branch was dead
            # code for the entire life of the defect. Repointing the calculator
            # at the real pool ran it for the first time — and it raised.
            #
            #   ((1 + daily_yield / n) ** (n * 365) - 1) * 100.0
            #
            # `daily_yield = reward_rate / total_staked` is unbounded, and the
            # cap was applied AFTER the exponentiation, so it could not
            # protect: `min(...)` never sees a value that overflowed on the way
            # in. Measured — stake 1.0 then unstake 0.96 leaves a pool total of
            # 0.04, and `get_position` raised OverflowError where before the
            # repoint it returned (a wrong 0.0). The threshold is
            # `total_staked < ~0.4886 * reward_rate`, so with a configured
            # `default_reward_rate: 100` a healthy 40 ETH pool is inside the
            # band. FIXING A SHADOW ARMS WHATEVER THE SHADOW WAS HIDING — the
            # arming-dead-machinery hazard, reached by repair rather than by
            # configuration.
            #
            # Computed in log space so the cap binds BEFORE the overflow rather
            # than after it. Below the cap this is the same number the original
            # expression produces; above it, the cap was always the intent.
            n = self._compounding
            growth = n * 365 * math.log1p(daily_yield / n)
            if growth >= _CAP_LOG_GROWTH:
                apy = _MAX_APY_PCT
            else:
                apy = min((math.exp(growth) - 1) * 100.0, _MAX_APY_PCT)

        # Record snapshot
        now = int(time.time())
        self._history.setdefault(pool_id, []).append((now, apy))

        # Trim history to 90 days
        cutoff = now - 90 * 86400
        self._history[pool_id] = [
            (t, a) for t, a in self._history[pool_id] if t >= cutoff
        ]

        avg_7d = self._compute_avg(pool_id, 7)
        avg_30d = self._compute_avg(pool_id, 30)

        result = {
            "pool_id": pool_id,
            "current_apy": round(apy, 4),
            "7d_avg": round(avg_7d, 4),
            "30d_avg": round(avg_30d, 4),
            "total_staked": total_staked,
            "reward_rate": reward_rate,
            "validator_performance": self._validator_perf,
            "compounding_frequency": self._compounding,
            "calculated_at": now,
        }

        logger.debug(
            "APY calculated: pool=%s apy=%.4f%% 7d_avg=%.4f%% 30d_avg=%.4f%%",
            pool_id, apy, avg_7d, avg_30d,
        )
        return result

    async def get_historical_apy(
        self, pool_id: str, days: int = 30,
    ) -> list:
        """Get historical APY snapshots for a pool.

        Args:
            pool_id: The staking pool.
            days: Number of days of history to return (default 30).

        Returns:
            List of dicts with ``timestamp`` and ``apy``.
        """
        cutoff = int(time.time()) - days * 86400
        history = self._history.get(pool_id, [])

        return [
            {"timestamp": t, "apy": round(a, 4)}
            for t, a in history
            if t >= cutoff
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_avg(self, pool_id: str, days: int) -> float:
        """Compute average APY over the last *days* days."""
        cutoff = int(time.time()) - days * 86400
        entries = [
            a for t, a in self._history.get(pool_id, [])
            if t >= cutoff
        ]
        if not entries:
            return 0.0
        return sum(entries) / len(entries)
