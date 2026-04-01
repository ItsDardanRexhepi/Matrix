"""
TransferRateLimiter -- enforces transfer volume limits per time window.

Default limits: 50K/day, 200K/week, 500K/month. Supports per-tier
overrides via config.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# Seconds per window
WINDOW_DAY = 86_400
WINDOW_WEEK = 604_800
WINDOW_MONTH = 2_592_000  # 30 days

DEFAULT_LIMITS: dict[str, float] = {
    "daily": 50_000.0,
    "weekly": 200_000.0,
    "monthly": 500_000.0,
}

# Per-tier limit multipliers
DEFAULT_TIER_OVERRIDES: dict[str, dict[str, float]] = {
    "bronze": {"daily": 50_000.0, "weekly": 200_000.0, "monthly": 500_000.0},
    "silver": {"daily": 100_000.0, "weekly": 400_000.0, "monthly": 1_000_000.0},
    "gold": {"daily": 250_000.0, "weekly": 1_000_000.0, "monthly": 2_500_000.0},
    "platinum": {"daily": 500_000.0, "weekly": 2_000_000.0, "monthly": 5_000_000.0},
    "diamond": {"daily": 1_000_000.0, "weekly": 5_000_000.0, "monthly": 10_000_000.0},
}


class TransferRateLimiter:
    """
    Rate limiter for stablecoin transfers.

    Enforces daily, weekly, and monthly volume limits per address.
    Limits are configurable globally and per-tier.

    Config keys (under config["stablecoin"]):
        rate_limits       -- dict with daily/weekly/monthly defaults
        tier_overrides    -- dict mapping tier name -> limit dict
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        sc = config.get("stablecoin", {})

        self.default_limits: dict[str, float] = sc.get("rate_limits", DEFAULT_LIMITS)
        self.tier_overrides: dict[str, dict[str, float]] = sc.get(
            "tier_overrides", DEFAULT_TIER_OVERRIDES
        )

        # address -> list of (timestamp, amount) records
        self._transfer_log: dict[str, list[tuple[float, float]]] = defaultdict(list)
        # address -> tier override
        self._address_tiers: dict[str, str] = {}

        logger.info(
            "TransferRateLimiter initialised: default_limits=%s",
            self.default_limits,
        )

    async def check_limit(
        self, address: str, amount: float
    ) -> dict[str, Any]:
        """
        Check whether a transfer of the given amount is allowed.

        Args:
            address: Sender address.
            amount: Proposed transfer amount.

        Returns:
            Dict with allowed (bool), current usage, limits, and reason if blocked.
        """
        now = time.time()
        limits = await self.get_limits(address)
        usage = self._compute_usage(address, now)

        # Check each window
        checks: list[dict[str, Any]] = []
        blocked = False
        block_reason = ""

        for window_name, window_seconds in [
            ("daily", WINDOW_DAY),
            ("weekly", WINDOW_WEEK),
            ("monthly", WINDOW_MONTH),
        ]:
            limit = limits["limits"].get(window_name, float("inf"))
            used = usage.get(window_name, 0.0)
            remaining = max(0.0, limit - used)
            would_exceed = (used + amount) > limit

            check = {
                "window": window_name,
                "limit": limit,
                "used": round(used, 6),
                "remaining": round(remaining, 6),
                "proposed": round(amount, 6),
                "would_exceed": would_exceed,
            }
            checks.append(check)

            if would_exceed:
                blocked = True
                block_reason = (
                    f"{window_name} limit exceeded: used {used:.2f} + proposed {amount:.2f} "
                    f"> limit {limit:.2f}"
                )

        return {
            "allowed": not blocked,
            "address": address,
            "amount": round(amount, 6),
            "reason": block_reason if blocked else "within limits",
            "checks": checks,
            "tier": limits.get("tier", "default"),
        }

    async def get_limits(self, address: str) -> dict[str, Any]:
        """
        Get the effective rate limits for an address.

        Uses tier-specific overrides if available, otherwise defaults.

        Args:
            address: Wallet address.

        Returns:
            Dict with limits, tier, and source.
        """
        tier = self._address_tiers.get(address)

        if tier and tier in self.tier_overrides:
            limits = self.tier_overrides[tier].copy()
            source = f"tier:{tier}"
        else:
            limits = self.default_limits.copy()
            tier = "default"
            source = "default"

        return {
            "address": address,
            "tier": tier,
            "source": source,
            "limits": limits,
        }

    async def record_transfer(self, address: str, amount: float) -> None:
        """Record a completed transfer for rate-limiting purposes."""
        now = time.time()
        self._transfer_log[address].append((now, amount))

        # Prune entries older than 30 days
        cutoff = now - WINDOW_MONTH
        self._transfer_log[address] = [
            (ts, amt) for ts, amt in self._transfer_log[address] if ts >= cutoff
        ]

    def set_tier(self, address: str, tier: str) -> None:
        """Set the rate-limit tier for an address."""
        self._address_tiers[address] = tier
        logger.info("Rate-limit tier set: %s -> %s", address, tier)

    def _compute_usage(self, address: str, now: float) -> dict[str, float]:
        """Compute usage across all windows for an address."""
        log = self._transfer_log.get(address, [])

        daily = sum(amt for ts, amt in log if ts >= now - WINDOW_DAY)
        weekly = sum(amt for ts, amt in log if ts >= now - WINDOW_WEEK)
        monthly = sum(amt for ts, amt in log if ts >= now - WINDOW_MONTH)

        return {
            "daily": daily,
            "weekly": weekly,
            "monthly": monthly,
        }
