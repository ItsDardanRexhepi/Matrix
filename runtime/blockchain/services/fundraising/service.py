"""
FundraisingService — community fundraising with milestone-based fund
release, vesting schedules, and automatic refunds.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.fundraising.milestone_verification import (
    MilestoneVerification,
)
from runtime.blockchain.services.fundraising.refunds import RefundManager
from runtime.blockchain.services.fundraising.vesting import VestingManager

logger = logging.getLogger(__name__)

_VALID_STATUSES = (
    "active", "funded", "milestone_in_progress",
    "completed", "failed", "refunding",
)


class FundraisingService:
    """Community fundraising service with milestone-based releases.

    Config keys (under ``config["fundraising"]``):
        max_campaign_days (int): Maximum campaign duration in days (default 90).
        min_goal (float): Minimum fundraising goal (default 100).
        max_milestones (int): Maximum milestones per campaign (default 10).
        All keys from VestingManager, MilestoneVerification, and
        RefundManager are also supported.
    """

    def __init__(self, config: dict, oracle_service: Any = None) -> None:
        self._config = config
        f_cfg: dict[str, Any] = config.get("fundraising", {})

        self._max_days: int = int(f_cfg.get("max_campaign_days", 90))
        self._min_goal: float = float(f_cfg.get("min_goal", 100.0))
        self._max_milestones: int = int(f_cfg.get("max_milestones", 10))

        self._vesting = VestingManager(config)
        self._milestones = MilestoneVerification(config, oracle_service)
        self._refunds = RefundManager(config)

        # campaign_id -> campaign record
        self._campaigns: dict[str, dict[str, Any]] = {}
        # campaign_id -> {contributor: total_amount}
        self._contributions: dict[str, dict[str, float]] = {}

        logger.info(
            "FundraisingService initialised (max_days=%d, min_goal=%.2f).",
            self._max_days, self._min_goal,
        )

    @property
    def vesting(self) -> VestingManager:
        return self._vesting

    @property
    def milestone_verification(self) -> MilestoneVerification:
        return self._milestones

    @property
    def refund_manager(self) -> RefundManager:
        return self._refunds

    # ------------------------------------------------------------------
    # Campaign lifecycle
    # ------------------------------------------------------------------

    async def create_campaign(
        self,
        creator: str,
        title: str,
        goal: float,
        deadline_days: int,
        milestones: list,
    ) -> dict:
        """Create a new fundraising campaign.

        Args:
            creator: Campaign creator wallet address.
            title: Campaign title.
            goal: Fundraising goal amount.
            deadline_days: Days until campaign deadline.
            milestones: List of milestone dicts, each with 'title',
                        'description', and 'release_pct' (percentage of
                        funds released upon verification).

        Returns:
            Campaign record.
        """
        if not creator:
            raise ValueError("Creator address is required")
        if not title:
            raise ValueError("Campaign title is required")
        if goal < self._min_goal:
            raise ValueError(f"Goal must be at least {self._min_goal}")
        if deadline_days <= 0:
            raise ValueError("Deadline must be positive")
        if deadline_days > self._max_days:
            raise ValueError(
                f"Campaign duration cannot exceed {self._max_days} days"
            )
        if not milestones:
            raise ValueError("At least one milestone is required")
        if len(milestones) > self._max_milestones:
            raise ValueError(
                f"Maximum {self._max_milestones} milestones allowed"
            )

        # Validate milestone release percentages sum to 100
        total_pct = sum(m.get("release_pct", 0) for m in milestones)
        if abs(total_pct - 100.0) > 0.01:
            raise ValueError(
                f"Milestone release percentages must sum to 100, got {total_pct}"
            )

        campaign_id = str(uuid.uuid4())
        now = int(time.time())

        processed_milestones = []
        for i, m in enumerate(milestones):
            processed_milestones.append({
                "idx": i,
                "title": m.get("title", f"Milestone {i + 1}"),
                "description": m.get("description", ""),
                "release_pct": m.get("release_pct", 100 / len(milestones)),
                "status": "pending",
                "released_amount": 0.0,
            })

        campaign = {
            "campaign_id": campaign_id,
            "creator": creator,
            "title": title,
            "goal": goal,
            "raised": 0.0,
            "released": 0.0,
            "contributor_count": 0,
            "deadline": now + (deadline_days * 86400),
            "deadline_days": deadline_days,
            "milestones": processed_milestones,
            "status": "active",
            "created_at": now,
            "funded_at": None,
            "completed_at": None,
        }

        self._campaigns[campaign_id] = campaign
        self._contributions[campaign_id] = {}

        logger.info(
            "Campaign created: id=%s title='%s' goal=%.2f deadline=%dd milestones=%d",
            campaign_id, title, goal, deadline_days, len(milestones),
        )
        return dict(campaign)

    async def contribute(
        self, campaign_id: str, contributor: str, amount: float
    ) -> dict:
        """Contribute funds to a campaign.

        Args:
            campaign_id: Target campaign.
            contributor: Contributor wallet address.
            amount: Contribution amount.

        Returns:
            Contribution record.
        """
        campaign = self._campaigns.get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        if campaign["status"] != "active":
            raise ValueError(
                f"Campaign is {campaign['status']}, not accepting contributions"
            )
        if amount <= 0:
            raise ValueError("Contribution amount must be positive")

        now = int(time.time())
        if now > campaign["deadline"]:
            # Check if goal was met
            if campaign["raised"] < campaign["goal"]:
                campaign["status"] = "failed"
                raise ValueError(
                    "Campaign deadline has passed without meeting goal"
                )

        # Record contribution
        contribs = self._contributions[campaign_id]
        prev = contribs.get(contributor, 0.0)
        contribs[contributor] = prev + amount

        if prev == 0:
            campaign["contributor_count"] += 1

        campaign["raised"] += amount

        # Check if goal reached
        if campaign["raised"] >= campaign["goal"] and campaign["funded_at"] is None:
            campaign["funded_at"] = now
            campaign["status"] = "funded"
            logger.info("Campaign funded: id=%s raised=%.2f", campaign_id, campaign["raised"])

        contribution = {
            "contribution_id": str(uuid.uuid4()),
            "campaign_id": campaign_id,
            "contributor": contributor,
            "amount": amount,
            "total_contributed": contribs[contributor],
            "campaign_raised": campaign["raised"],
            "campaign_goal": campaign["goal"],
            "progress_pct": (campaign["raised"] / campaign["goal"] * 100),
            "contributed_at": now,
        }

        logger.info(
            "Contribution: campaign=%s contributor=%s amount=%.4f total_raised=%.4f",
            campaign_id, contributor, amount, campaign["raised"],
        )
        return contribution

    async def get_campaign(self, campaign_id: str) -> dict:
        """Get full campaign details.

        Includes auto-fail check if deadline passed without meeting goal.

        Returns:
            Campaign record with contributions summary.
        """
        campaign = self._campaigns.get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        # Auto-fail check
        now = int(time.time())
        if (campaign["status"] == "active"
                and now > campaign["deadline"]
                and campaign["raised"] < campaign["goal"]):
            campaign["status"] = "failed"
            logger.info("Campaign auto-failed: id=%s", campaign_id)

        result = dict(campaign)
        result["milestones"] = [dict(m) for m in campaign["milestones"]]

        contribs = self._contributions.get(campaign_id, {})
        result["contributions_summary"] = {
            "total_contributors": len(contribs),
            "total_raised": campaign["raised"],
            "goal": campaign["goal"],
            "progress_pct": (campaign["raised"] / campaign["goal"] * 100) if campaign["goal"] > 0 else 0,
        }

        return result

    async def list_campaigns(self, status: str | None = None) -> list:
        """List all campaigns, optionally filtered by status.

        Returns:
            List of campaign summaries.
        """
        results = []
        now = int(time.time())

        for campaign in self._campaigns.values():
            # Auto-fail check
            if (campaign["status"] == "active"
                    and now > campaign["deadline"]
                    and campaign["raised"] < campaign["goal"]):
                campaign["status"] = "failed"

            if status is not None and campaign["status"] != status:
                continue

            results.append({
                "campaign_id": campaign["campaign_id"],
                "title": campaign["title"],
                "creator": campaign["creator"],
                "goal": campaign["goal"],
                "raised": campaign["raised"],
                "progress_pct": (campaign["raised"] / campaign["goal"] * 100) if campaign["goal"] > 0 else 0,
                "contributor_count": campaign["contributor_count"],
                "status": campaign["status"],
                "deadline": campaign["deadline"],
                "created_at": campaign["created_at"],
            })

        results.sort(key=lambda c: c["created_at"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # Milestone-triggered fund release
    # ------------------------------------------------------------------

    async def release_milestone_funds(
        self, campaign_id: str, milestone_idx: int
    ) -> dict:
        """Release funds for a verified milestone.

        Only releases if the milestone has been verified.

        Returns:
            Release record.
        """
        campaign = self._campaigns.get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        if milestone_idx < 0 or milestone_idx >= len(campaign["milestones"]):
            raise ValueError(f"Invalid milestone index {milestone_idx}")

        milestone = campaign["milestones"][milestone_idx]
        if milestone["status"] == "released":
            raise ValueError(f"Milestone {milestone_idx} funds already released")

        # Check verification status via MilestoneVerification
        ms_status = self._milestones.get_milestone_status(campaign_id, milestone_idx)
        if not ms_status or ms_status["status"] != "verified":
            raise ValueError(
                f"Milestone {milestone_idx} must be verified before funds can be released"
            )

        release_amount = campaign["raised"] * (milestone["release_pct"] / 100.0)
        milestone["status"] = "released"
        milestone["released_amount"] = release_amount
        campaign["released"] += release_amount

        # Check if all milestones completed
        all_released = all(m["status"] == "released" for m in campaign["milestones"])
        if all_released:
            campaign["status"] = "completed"
            campaign["completed_at"] = int(time.time())
            logger.info("Campaign completed: id=%s", campaign_id)

        logger.info(
            "Milestone funds released: campaign=%s idx=%d amount=%.4f",
            campaign_id, milestone_idx, release_amount,
        )
        return {
            "campaign_id": campaign_id,
            "milestone_idx": milestone_idx,
            "release_amount": release_amount,
            "total_released": campaign["released"],
            "remaining": campaign["raised"] - campaign["released"],
            "campaign_status": campaign["status"],
        }

    async def trigger_refunds(self, campaign_id: str) -> dict:
        """Trigger refunds for a failed campaign.

        Auto-refund if campaign failed, or pro-rata if milestone failed.

        Returns:
            Bulk refund result.
        """
        campaign = self._campaigns.get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        if campaign["status"] not in ("failed", "milestone_failed", "refunding"):
            # Check auto-fail
            now = int(time.time())
            if (campaign["status"] == "active"
                    and now > campaign["deadline"]
                    and campaign["raised"] < campaign["goal"]):
                campaign["status"] = "failed"
            else:
                raise ValueError(
                    f"Campaign {campaign_id} is {campaign['status']}, "
                    f"refunds only available for failed campaigns"
                )

        campaign["status"] = "refunding"

        contribs = self._contributions.get(campaign_id, {})
        result = await self._refunds.process_refunds(
            campaign_id,
            contributions=contribs,
            total_raised=campaign["raised"],
            total_released=campaign["released"],
        )

        logger.info(
            "Refunds triggered: campaign=%s refunded=%d",
            campaign_id, result["contributors_refunded"],
        )
        return result
