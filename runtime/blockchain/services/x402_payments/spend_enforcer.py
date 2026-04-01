"""
SpendEnforcer -- per-agent spend limit enforcement for x402 payments.

Enforces per-transaction, daily, weekly, and monthly spend limits
per agent. Limits are configurable per agent via config.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# Time windows in seconds
WINDOW_DAY = 86_400
WINDOW_WEEK = 604_800
WINDOW_MONTH = 2_592_000  # 30 days

DEFAULT_AGENT_LIMITS: dict[str, float] = {
    "per_transaction": 10_000.0,
    "daily": 50_000.0,
    "weekly": 150_000.0,
    "monthly": 500_000.0,
}


class SpendEnforcer:
    """
    Enforces spend limits for autonomous agents making x402 payments.

    Each agent has per-transaction, daily, weekly, and monthly limits.
    Limits can be customised per agent via config or LimitUpdater.

    Config keys (under config["x402"]):
        default_agent_limits -- default limits for all agents
        agent_limits         -- dict mapping agent_id -> custom limits
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        x402 = config.get("x402", {})

        self.default_limits: dict[str, float] = x402.get(
            "default_agent_limits", DEFAULT_AGENT_LIMITS
        )
        # agent_id -> custom limits
        self._agent_limits: dict[str, dict[str, float]] = dict(
            x402.get("agent_limits", {})
        )

        # agent_id -> list of (timestamp, amount) spend records
        self._spend_log: dict[str, list[tuple[float, float]]] = defaultdict(list)

        logger.info(
            "SpendEnforcer initialised: default_limits=%s custom_agents=%d",
            self.default_limits, len(self._agent_limits),
        )

    async def check_spend(
        self, agent_id: str, amount: float
    ) -> dict[str, Any]:
        """
        Check whether an agent is allowed to spend the given amount.

        Args:
            agent_id: The agent making the payment.
            amount: Proposed spend amount.

        Returns:
            Dict with allowed (bool), reason, and detailed check results.
        """
        limits = self._get_effective_limits(agent_id)
        now = time.time()
        usage = self._compute_usage(agent_id, now)

        blocked = False
        reason = "within limits"
        checks: list[dict[str, Any]] = []

        # Per-transaction check
        tx_limit = limits.get("per_transaction", float("inf"))
        if amount > tx_limit:
            blocked = True
            reason = f"Per-transaction limit exceeded: {amount:.2f} > {tx_limit:.2f}"
        checks.append({
            "window": "per_transaction",
            "limit": tx_limit,
            "proposed": round(amount, 6),
            "exceeds": amount > tx_limit,
        })

        # Window-based checks
        for window_name, window_key in [
            ("daily", "daily"),
            ("weekly", "weekly"),
            ("monthly", "monthly"),
        ]:
            limit = limits.get(window_key, float("inf"))
            used = usage.get(window_name, 0.0)
            remaining = max(0.0, limit - used)
            would_exceed = (used + amount) > limit

            checks.append({
                "window": window_name,
                "limit": limit,
                "used": round(used, 6),
                "remaining": round(remaining, 6),
                "proposed": round(amount, 6),
                "would_exceed": would_exceed,
            })

            if would_exceed and not blocked:
                blocked = True
                reason = (
                    f"{window_name} limit exceeded: used {used:.2f} + "
                    f"proposed {amount:.2f} > limit {limit:.2f}"
                )

        return {
            "allowed": not blocked,
            "agent_id": agent_id,
            "amount": round(amount, 6),
            "reason": reason,
            "checks": checks,
        }

    async def get_spend_summary(self, agent_id: str) -> dict[str, Any]:
        """
        Get a summary of an agent's current spend across all windows.

        Args:
            agent_id: The agent identifier.

        Returns:
            Dict with usage, limits, and remaining budget per window.
        """
        limits = self._get_effective_limits(agent_id)
        now = time.time()
        usage = self._compute_usage(agent_id, now)

        summary: dict[str, Any] = {
            "agent_id": agent_id,
            "windows": {},
            "total_all_time": sum(amt for _, amt in self._spend_log.get(agent_id, [])),
        }

        for window_name in ("daily", "weekly", "monthly"):
            limit = limits.get(window_name, float("inf"))
            used = usage.get(window_name, 0.0)
            summary["windows"][window_name] = {
                "limit": limit,
                "used": round(used, 6),
                "remaining": round(max(0.0, limit - used), 6),
                "utilization_pct": round((used / limit) * 100, 2) if limit > 0 else 0.0,
            }

        summary["per_transaction_limit"] = limits.get("per_transaction", float("inf"))

        return summary

    async def record_spend(self, agent_id: str, amount: float) -> None:
        """Record a completed spend for an agent."""
        self._spend_log[agent_id].append((time.time(), amount))
        self._prune_old_records(agent_id)

    async def reverse_spend(self, agent_id: str, amount: float) -> None:
        """
        Reverse a spend (e.g. for refunds).

        Records a negative spend entry so usage calculations reflect the refund.
        """
        self._spend_log[agent_id].append((time.time(), -amount))
        logger.info("Spend reversed: agent=%s amount=%.6f", agent_id, amount)

    def set_limits(self, agent_id: str, limits: dict[str, float]) -> None:
        """Set custom limits for an agent (called by LimitUpdater)."""
        self._agent_limits[agent_id] = limits.copy()
        logger.info("Agent limits updated: agent=%s limits=%s", agent_id, limits)

    def get_limits(self, agent_id: str) -> dict[str, float]:
        """Get effective limits for an agent."""
        return self._get_effective_limits(agent_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_effective_limits(self, agent_id: str) -> dict[str, float]:
        """Get limits for agent, using custom if set, otherwise defaults."""
        if agent_id in self._agent_limits:
            return self._agent_limits[agent_id]
        return self.default_limits.copy()

    def _compute_usage(self, agent_id: str, now: float) -> dict[str, float]:
        """Compute spend usage for each time window."""
        log = self._spend_log.get(agent_id, [])

        daily = sum(amt for ts, amt in log if ts >= now - WINDOW_DAY)
        weekly = sum(amt for ts, amt in log if ts >= now - WINDOW_WEEK)
        monthly = sum(amt for ts, amt in log if ts >= now - WINDOW_MONTH)

        return {
            "daily": max(0.0, daily),
            "weekly": max(0.0, weekly),
            "monthly": max(0.0, monthly),
        }

    def _prune_old_records(self, agent_id: str) -> None:
        """Remove records older than 30 days to bound memory usage."""
        cutoff = time.time() - WINDOW_MONTH
        self._spend_log[agent_id] = [
            (ts, amt) for ts, amt in self._spend_log[agent_id] if ts >= cutoff
        ]
