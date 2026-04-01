"""Recurring Rewards - Component 27.

Manages reward accrual and distribution per billing period.
Long-term subscribers receive loyalty multipliers.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Loyalty multipliers based on subscription duration
LOYALTY_MULTIPLIERS: dict[int, float] = {
    0: 1.0,       # 0-5 months: 1x
    6: 1.1,       # 6-11 months: 1.1x
    12: 1.25,     # 12+ months: 1.25x
}

SECONDS_PER_MONTH = 2592000  # 30 days


class RecurringRewards:
    """Manages recurring reward calculation and distribution.

    Rewards accrue per billing period with loyalty multipliers for
    long-term subscribers (1.1x after 6 months, 1.25x after 1 year).
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._subscription_rewards: dict[str, dict] = {}
        self._reward_history: dict[str, list] = {}
        logger.info("RecurringRewards initialised")

    async def initialize_subscription(self, subscription_id: str, rewards_config: dict) -> None:
        """Set up reward tracking for a new subscription.

        Args:
            subscription_id: The subscription ID.
            rewards_config: Reward configuration from the plan.
        """
        self._subscription_rewards[subscription_id] = {
            "config": rewards_config,
            "total_distributed": 0.0,
            "distribution_count": 0,
            "started_at": time.time(),
        }
        self._reward_history[subscription_id] = []
        logger.info("Initialised rewards for subscription %s", subscription_id)

    def _get_loyalty_multiplier(self, subscription_id: str) -> float:
        """Calculate the loyalty multiplier based on subscription duration."""
        data = self._subscription_rewards.get(subscription_id)
        if not data:
            return 1.0

        duration_seconds = time.time() - data["started_at"]
        months = int(duration_seconds / SECONDS_PER_MONTH)

        multiplier = 1.0
        for threshold_months, mult in sorted(LOYALTY_MULTIPLIERS.items()):
            if months >= threshold_months:
                multiplier = mult
        return multiplier

    async def calculate_rewards(self, subscription_id: str) -> dict:
        """Calculate rewards for the current billing period.

        Args:
            subscription_id: The subscription to calculate for.

        Returns:
            Dict with base reward, multiplier, and final reward amount.
        """
        data = self._subscription_rewards.get(subscription_id)
        if not data:
            raise ValueError(f"No reward data for subscription '{subscription_id}'")

        config = data["config"]
        base_reward = config.get("base_reward", 0.0)
        reward_type = config.get("type", "points")
        multiplier = self._get_loyalty_multiplier(subscription_id)
        final_reward = round(base_reward * multiplier, 8)

        duration_seconds = time.time() - data["started_at"]
        months = int(duration_seconds / SECONDS_PER_MONTH)

        return {
            "subscription_id": subscription_id,
            "reward_type": reward_type,
            "base_reward": base_reward,
            "loyalty_multiplier": multiplier,
            "final_reward": final_reward,
            "subscription_months": months,
            "next_multiplier_at": self._next_multiplier_milestone(months),
        }

    async def distribute_rewards(self, subscription_id: str) -> dict:
        """Distribute rewards for the current billing period.

        Args:
            subscription_id: The subscription to distribute for.

        Returns:
            Distribution record.
        """
        data = self._subscription_rewards.get(subscription_id)
        if not data:
            raise ValueError(f"No reward data for subscription '{subscription_id}'")

        calculation = await self.calculate_rewards(subscription_id)
        dist_id = f"rdist_{uuid.uuid4().hex[:12]}"
        now = time.time()

        record = {
            "distribution_id": dist_id,
            "subscription_id": subscription_id,
            "reward_type": calculation["reward_type"],
            "amount": calculation["final_reward"],
            "base_amount": calculation["base_reward"],
            "multiplier": calculation["loyalty_multiplier"],
            "distributed_at": now,
            "period_number": data["distribution_count"] + 1,
        }

        data["total_distributed"] = round(data["total_distributed"] + calculation["final_reward"], 8)
        data["distribution_count"] += 1

        self._reward_history.setdefault(subscription_id, []).append(record)

        logger.info(
            "Distributed reward for sub %s: %.2f (base=%.2f, mult=%.2f, period=%d)",
            subscription_id, calculation["final_reward"],
            calculation["base_reward"], calculation["loyalty_multiplier"],
            record["period_number"],
        )
        return record

    async def get_reward_history(self, subscription_id: str) -> list:
        """Get the reward distribution history for a subscription.

        Args:
            subscription_id: The subscription to query.

        Returns:
            List of distribution records.
        """
        history = self._reward_history.get(subscription_id)
        if history is None:
            raise ValueError(f"No reward history for subscription '{subscription_id}'")
        return list(history)

    def _next_multiplier_milestone(self, current_months: int) -> dict | None:
        """Find the next loyalty multiplier milestone."""
        for threshold in sorted(LOYALTY_MULTIPLIERS.keys()):
            if threshold > current_months:
                return {
                    "months": threshold,
                    "multiplier": LOYALTY_MULTIPLIERS[threshold],
                    "months_remaining": threshold - current_months,
                }
        return None  # Already at max
