"""Brand-to-User Direct Rewards Service - Component 26.

Enables brands to reward users directly with ZERO platform commission.
Enforces 100-user cohort minimum for analytics privacy protection.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from .zkp_targeting import ZKPTargeting
from .analytics import CohortAnalytics

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "min_cohort_size": 100,
    "platform_commission": 0.0,  # ZERO commission
    "max_budget": 10_000_000.0,
    "reward_types": ["token", "nft", "discount", "cashback", "points", "experience"],
    "campaign_statuses": ["draft", "active", "paused", "completed", "cancelled"],
}


class BrandRewardService:
    """Direct brand-to-user rewards with zero commission.

    Brands can create campaigns targeting specific user cohorts via ZKP.
    The platform takes ZERO commission on direct rewards. Analytics only
    available for cohorts of 100+ users for privacy protection.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self._campaigns: dict[str, dict] = {}
        self._distributions: list[dict] = []
        self.targeting = ZKPTargeting(self.config)
        self.analytics = CohortAnalytics(self.config)
        logger.info(
            "BrandRewardService initialised (commission=%.0f%%, min_cohort=%d)",
            self.config["platform_commission"] * 100,
            self.config["min_cohort_size"],
        )

    async def create_campaign(self, brand: str, reward_type: str, budget: float, criteria: dict) -> dict:
        """Create a new reward campaign.

        Args:
            brand: Brand's wallet address or identifier.
            reward_type: Type of reward to distribute.
            budget: Total campaign budget in platform currency.
            criteria: Targeting criteria for ZKP-based user selection.

        Returns:
            The created campaign record.
        """
        if not brand:
            raise ValueError("brand is required")
        if reward_type not in self.config["reward_types"]:
            raise ValueError(f"Invalid reward_type '{reward_type}'. Must be one of: {self.config['reward_types']}")
        if budget <= 0:
            raise ValueError("budget must be positive")
        if budget > self.config["max_budget"]:
            raise ValueError(f"budget cannot exceed {self.config['max_budget']}")

        campaign_id = f"camp_{uuid.uuid4().hex[:12]}"
        now = time.time()

        campaign = {
            "campaign_id": campaign_id,
            "brand": brand,
            "reward_type": reward_type,
            "budget": budget,
            "budget_remaining": budget,
            "criteria": criteria,
            "status": "active",
            "platform_commission": self.config["platform_commission"],
            "total_distributed": 0.0,
            "distribution_count": 0,
            "unique_recipients": set(),
            "created_at": now,
            "updated_at": now,
        }

        self._campaigns[campaign_id] = campaign

        # Set up targeting criteria
        await self.targeting.create_criteria(campaign_id, criteria)

        logger.info(
            "Campaign %s created by brand %s (type=%s, budget=%.2f, commission=0%%)",
            campaign_id, brand, reward_type, budget,
        )
        return self._serialize_campaign(campaign)

    async def distribute_reward(self, campaign_id: str, user: str, amount: float) -> dict:
        """Distribute a reward to a user from a campaign.

        Args:
            campaign_id: The campaign to distribute from.
            user: Recipient's wallet address.
            amount: Reward amount.

        Returns:
            Distribution record with zero-commission confirmation.
        """
        if not user:
            raise ValueError("user is required")
        if amount <= 0:
            raise ValueError("amount must be positive")

        campaign = self._campaigns.get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign '{campaign_id}' not found")
        if campaign["status"] != "active":
            raise ValueError(f"Campaign '{campaign_id}' is not active (status={campaign['status']})")
        if amount > campaign["budget_remaining"]:
            raise ValueError(
                f"Insufficient budget: remaining={campaign['budget_remaining']:.2f}, requested={amount:.2f}"
            )

        # Check eligibility via ZKP
        eligibility = await self.targeting.check_eligibility(campaign_id, user)
        if not eligibility.get("eligible", False):
            raise ValueError(f"User does not meet campaign criteria: {eligibility.get('reason', 'unknown')}")

        # Zero commission: full amount goes to user
        platform_fee = 0.0
        user_receives = amount

        dist_id = f"dist_{uuid.uuid4().hex[:12]}"
        now = time.time()

        distribution = {
            "distribution_id": dist_id,
            "campaign_id": campaign_id,
            "brand": campaign["brand"],
            "user": user,
            "amount": amount,
            "platform_fee": platform_fee,
            "user_receives": user_receives,
            "reward_type": campaign["reward_type"],
            "distributed_at": now,
        }

        campaign["budget_remaining"] = round(campaign["budget_remaining"] - amount, 8)
        campaign["total_distributed"] = round(campaign["total_distributed"] + amount, 8)
        campaign["distribution_count"] += 1
        campaign["unique_recipients"].add(user)
        campaign["updated_at"] = now

        if campaign["budget_remaining"] <= 0:
            campaign["status"] = "completed"
            logger.info("Campaign %s budget exhausted, marked as completed", campaign_id)

        self._distributions.append(distribution)

        # Update analytics
        await self.analytics.record_distribution(campaign_id, user, amount)

        logger.info(
            "Distributed %.2f to user %s from campaign %s (fee=0)",
            amount, user, campaign_id,
        )
        return distribution

    async def get_campaign(self, campaign_id: str) -> dict:
        """Get a campaign by ID.

        Returns:
            The campaign record.
        """
        campaign = self._campaigns.get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign '{campaign_id}' not found")
        return self._serialize_campaign(campaign)

    async def list_campaigns(self, brand: str = None) -> list:
        """List campaigns, optionally filtered by brand.

        Args:
            brand: Filter by brand identifier (optional).

        Returns:
            List of campaign records.
        """
        campaigns = list(self._campaigns.values())
        if brand:
            campaigns = [c for c in campaigns if c["brand"] == brand]
        return [self._serialize_campaign(c) for c in campaigns]

    def _serialize_campaign(self, campaign: dict) -> dict:
        """Serialize campaign for API response (convert set to count)."""
        result = {k: v for k, v in campaign.items() if k != "unique_recipients"}
        result["unique_recipient_count"] = len(campaign.get("unique_recipients", set()))
        return result
