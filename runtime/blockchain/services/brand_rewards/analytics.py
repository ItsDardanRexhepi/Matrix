"""Cohort Analytics - Component 26.

Provides aggregate campaign analytics with strict privacy enforcement.
Individual user data is never exposed. Analytics only available when
cohort size is at least 100 users.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class CohortAnalytics:
    """Privacy-preserving campaign analytics.

    Only returns aggregate data when the cohort has at least 100 users.
    No individual user data is ever exposed to brands.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._min_cohort = self.config.get("min_cohort_size", 100)
        self._campaign_data: dict[str, dict] = {}
        logger.info("CohortAnalytics initialised (min_cohort=%d)", self._min_cohort)

    async def record_distribution(self, campaign_id: str, user: str, amount: float) -> None:
        """Record a distribution event for analytics.

        Args:
            campaign_id: Campaign identifier.
            user: Recipient (stored only for counting, never exposed).
            amount: Distribution amount.
        """
        if campaign_id not in self._campaign_data:
            self._campaign_data[campaign_id] = {
                "total_distributed": 0.0,
                "distribution_count": 0,
                "recipients": set(),
                "amounts": [],
                "timestamps": [],
            }

        data = self._campaign_data[campaign_id]
        data["total_distributed"] += amount
        data["distribution_count"] += 1
        data["recipients"].add(user)
        data["amounts"].append(amount)
        data["timestamps"].append(time.time())

    async def get_campaign_stats(self, campaign_id: str) -> dict:
        """Get aggregate campaign statistics.

        Only returns data when cohort >= min_cohort_size.

        Args:
            campaign_id: Campaign to get stats for.

        Returns:
            Aggregate stats or a privacy notice if cohort is too small.
        """
        data = self._campaign_data.get(campaign_id)
        if not data:
            return {
                "campaign_id": campaign_id,
                "available": False,
                "reason": "No distribution data recorded yet",
            }

        cohort_size = len(data["recipients"])
        if cohort_size < self._min_cohort:
            return {
                "campaign_id": campaign_id,
                "available": False,
                "reason": (
                    f"Cohort size ({cohort_size}) below minimum ({self._min_cohort}). "
                    "Analytics unavailable to protect user privacy."
                ),
                "cohort_size": cohort_size,
                "min_required": self._min_cohort,
            }

        amounts = data["amounts"]
        avg_amount = sum(amounts) / len(amounts) if amounts else 0.0

        return {
            "campaign_id": campaign_id,
            "available": True,
            "cohort_size": cohort_size,
            "total_distributed": round(data["total_distributed"], 2),
            "distribution_count": data["distribution_count"],
            "average_reward": round(avg_amount, 2),
            "min_reward": round(min(amounts), 2),
            "max_reward": round(max(amounts), 2),
        }

    async def get_cohort_insights(self, campaign_id: str) -> dict:
        """Get deeper cohort insights for a campaign.

        Only returns aggregate patterns. No individual user data exposed.

        Args:
            campaign_id: Campaign to analyze.

        Returns:
            Cohort insights or privacy notice.
        """
        data = self._campaign_data.get(campaign_id)
        if not data:
            return {
                "campaign_id": campaign_id,
                "available": False,
                "reason": "No distribution data recorded yet",
            }

        cohort_size = len(data["recipients"])
        if cohort_size < self._min_cohort:
            return {
                "campaign_id": campaign_id,
                "available": False,
                "reason": (
                    f"Cohort size ({cohort_size}) below minimum ({self._min_cohort}). "
                    "Insights unavailable to protect user privacy."
                ),
            }

        amounts = data["amounts"]
        timestamps = data["timestamps"]

        # Distribution bucketing (aggregate only)
        buckets = {"small": 0, "medium": 0, "large": 0}
        for a in amounts:
            if a < 10:
                buckets["small"] += 1
            elif a < 100:
                buckets["medium"] += 1
            else:
                buckets["large"] += 1

        # Engagement velocity
        if len(timestamps) >= 2:
            duration = timestamps[-1] - timestamps[0]
            velocity = data["distribution_count"] / (duration / 3600) if duration > 0 else 0
        else:
            velocity = 0

        # Repeat recipient rate (users who received multiple times)
        from collections import Counter
        # We don't store per-user counts to protect privacy,
        # but we can compare distribution_count vs unique recipients
        repeat_rate = round(
            max(0, (data["distribution_count"] - cohort_size)) / data["distribution_count"] * 100, 1
        ) if data["distribution_count"] > 0 else 0.0

        return {
            "campaign_id": campaign_id,
            "available": True,
            "cohort_size": cohort_size,
            "distribution_buckets": buckets,
            "engagement_velocity_per_hour": round(velocity, 2),
            "repeat_distribution_rate_pct": repeat_rate,
            "total_distributions": data["distribution_count"],
            "note": "All data is aggregate. No individual user data exposed.",
        }
