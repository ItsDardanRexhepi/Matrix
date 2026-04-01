"""Threshold Tracker - Component 25.

Tracks per-user spending against the annual threshold for cashback qualification.
Spending resets at the start of each calendar year.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class ThresholdTracker:
    """Tracks annual spending against the cashback qualification threshold.

    Each user's spending is tracked per calendar year. Once the threshold
    is met, the user qualifies for cashback for the remainder of the year.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._spending: dict[str, float] = {}  # key: "user:year"
        self._threshold = self.config.get("annual_threshold", 10_000.0)
        logger.info("ThresholdTracker initialised (threshold=$%.0f)", self._threshold)

    def _current_year(self) -> int:
        return time.gmtime().tm_year

    def _key(self, user: str, year: int | None = None) -> str:
        return f"{user}:{year or self._current_year()}"

    async def record_spending(self, user: str, amount: float) -> None:
        """Record spending for the current year."""
        key = self._key(user)
        self._spending[key] = self._spending.get(key, 0.0) + amount

    async def check_threshold(self, user: str) -> dict:
        """Check whether a user has met the annual spending threshold.

        Args:
            user: User's wallet address.

        Returns:
            Dict with qualification status, progress percentage, and amounts.
        """
        if not user:
            raise ValueError("user is required")

        year = self._current_year()
        key = self._key(user, year)
        total = self._spending.get(key, 0.0)
        qualified = total >= self._threshold
        remaining = max(0.0, self._threshold - total)
        progress_pct = min(100.0, round((total / self._threshold) * 100, 2)) if self._threshold > 0 else 100.0

        return {
            "user": user,
            "year": year,
            "status": "qualified" if qualified else "not_qualified",
            "total_spending": round(total, 2),
            "threshold": self._threshold,
            "remaining": round(remaining, 2),
            "progress_pct": progress_pct,
        }

    async def get_annual_spending(self, user: str) -> dict:
        """Get the user's annual spending total.

        Args:
            user: User's wallet address.

        Returns:
            Dict with year, total spending, and daily average.
        """
        if not user:
            raise ValueError("user is required")

        year = self._current_year()
        key = self._key(user, year)
        total = self._spending.get(key, 0.0)

        # Calculate days elapsed in current year
        now = time.gmtime()
        day_of_year = now.tm_yday
        daily_avg = round(total / day_of_year, 2) if day_of_year > 0 else 0.0

        # Project annual total
        days_in_year = 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
        projected_annual = round(daily_avg * days_in_year, 2)

        return {
            "user": user,
            "year": year,
            "total_spending": round(total, 2),
            "daily_average": daily_avg,
            "projected_annual": projected_annual,
            "days_elapsed": day_of_year,
            "days_remaining": days_in_year - day_of_year,
        }
