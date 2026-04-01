"""
APYCalculator — CANONICAL APY calculator for the 0pnMatrx platform.

Component 20 (dashboard) uses this exclusively. Factors in total staked,
reward rate, and validator performance to compute APY.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Annualisation constant
_SECONDS_PER_YEAR = 365.25 * 86400


class APYCalculator:
    """Canonical APY calculator for staking pools.

    This is the single source of truth for APY numbers across the
    platform.  Component 20 (dashboard) must use this calculator
    exclusively.

    Config keys (under ``config["staking"]``):
        validator_performance (float): 0..1 multiplier (default 0.95).
        compounding_frequency (int): compounds per year (default 365).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        s_cfg = config.get("staking", {})

        self._validator_perf: float = float(
            s_cfg.get("validator_performance", 0.95)
        )
        self._compounding: int = int(
            s_cfg.get("compounding_frequency", 365)
        )

        # Historical APY snapshots: pool_id -> [(timestamp, apy)]
        self._history: dict[str, list[tuple[int, float]]] = {}

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
        try:
            from runtime.blockchain.services.staking.pools import StakingPoolManager
            pm = StakingPoolManager(self._config)
            pool = await pm.get_pool(pool_id)
        except Exception:
            pool = {}

        total_staked = float(pool.get("total_staked", 0))
        reward_rate = float(pool.get("reward_rate", 0))

        if total_staked <= 0 or reward_rate <= 0:
            apy = 0.0
        else:
            # Daily yield per unit staked
            daily_yield = reward_rate / total_staked

            # Apply validator performance
            daily_yield *= self._validator_perf

            # Compound APY
            n = self._compounding
            apy = ((1 + daily_yield / n) ** (n * 365) - 1) * 100.0

            # Cap at reasonable maximum
            apy = min(apy, 10_000.0)

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
