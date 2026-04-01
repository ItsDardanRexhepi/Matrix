"""Appeal Process - Component 24.

Allows sellers to appeal removed/rejected listings. If appeal is denied,
sellers can escalate to Component 30 dispute resolution.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

VALID_DECISIONS = {"approved", "denied"}
VALID_STATUSES = {"pending", "under_review", "approved", "denied", "escalated"}


class AppealProcess:
    """Manages appeals for rejected or removed marketplace listings.

    Flow:
    1. Seller files an appeal with grounds.
    2. Reviewer examines and approves or denies.
    3. If denied, seller may escalate to Component 30 dispute resolution.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._appeals: dict[str, dict] = {}
        self._max_appeals_per_listing: int = self.config.get("max_appeals_per_listing", 3)
        logger.info("AppealProcess initialised (max_appeals_per_listing=%d)", self._max_appeals_per_listing)

    async def file_appeal(self, listing_id: str, seller: str, grounds: str) -> dict:
        """File an appeal for a rejected or removed listing.

        Args:
            listing_id: The listing being appealed.
            seller: The seller's wallet address.
            grounds: The reason/justification for the appeal.

        Returns:
            The appeal record.
        """
        if not listing_id:
            raise ValueError("listing_id is required")
        if not seller:
            raise ValueError("seller is required")
        if not grounds or len(grounds.strip()) < 10:
            raise ValueError("grounds must be at least 10 characters")

        # Check appeal limit
        existing = [
            a for a in self._appeals.values()
            if a["listing_id"] == listing_id and a["seller"] == seller
        ]
        if len(existing) >= self._max_appeals_per_listing:
            raise ValueError(
                f"Maximum {self._max_appeals_per_listing} appeals per listing reached. "
                "Consider escalating to dispute resolution (Component 30)."
            )

        appeal_id = f"appeal_{uuid.uuid4().hex[:12]}"
        now = time.time()

        appeal = {
            "appeal_id": appeal_id,
            "listing_id": listing_id,
            "seller": seller,
            "grounds": grounds,
            "status": "pending",
            "attempt_number": len(existing) + 1,
            "created_at": now,
            "updated_at": now,
            "reviewer": None,
            "decision": None,
            "decision_reason": None,
            "escalated": False,
            "escalation_reference": None,
        }

        self._appeals[appeal_id] = appeal
        logger.info(
            "Appeal %s filed for listing %s by %s (attempt %d)",
            appeal_id, listing_id, seller, appeal["attempt_number"],
        )
        return appeal

    async def review_appeal(self, appeal_id: str, reviewer: str, decision: str, reason: str = "") -> dict:
        """Review and decide on an appeal.

        Args:
            appeal_id: The appeal to review.
            reviewer: Reviewer's wallet address.
            decision: 'approved' or 'denied'.
            reason: Explanation for the decision.

        Returns:
            The updated appeal record.
        """
        if not reviewer:
            raise ValueError("reviewer is required")
        if decision not in VALID_DECISIONS:
            raise ValueError(f"decision must be one of: {VALID_DECISIONS}")

        appeal = self._appeals.get(appeal_id)
        if not appeal:
            raise ValueError(f"Appeal '{appeal_id}' not found")
        if appeal["status"] not in ("pending", "under_review"):
            raise ValueError(f"Appeal '{appeal_id}' is not pending review (status={appeal['status']})")

        appeal["reviewer"] = reviewer
        appeal["decision"] = decision
        appeal["decision_reason"] = reason
        appeal["status"] = decision
        appeal["updated_at"] = time.time()

        if decision == "denied":
            appeal["can_escalate"] = True
            logger.info(
                "Appeal %s DENIED by %s. Seller may escalate to Component 30.",
                appeal_id, reviewer,
            )
        else:
            appeal["can_escalate"] = False
            logger.info("Appeal %s APPROVED by %s.", appeal_id, reviewer)

        return appeal

    async def escalate_to_dispute(self, appeal_id: str) -> dict:
        """Escalate a denied appeal to Component 30 dispute resolution.

        Args:
            appeal_id: The denied appeal to escalate.

        Returns:
            The updated appeal record with escalation reference.
        """
        appeal = self._appeals.get(appeal_id)
        if not appeal:
            raise ValueError(f"Appeal '{appeal_id}' not found")
        if appeal["status"] != "denied":
            raise ValueError("Only denied appeals can be escalated")
        if appeal.get("escalated"):
            raise ValueError("Appeal has already been escalated")

        escalation_ref = f"dispute_{uuid.uuid4().hex[:12]}"
        appeal["escalated"] = True
        appeal["escalation_reference"] = escalation_ref
        appeal["status"] = "escalated"
        appeal["updated_at"] = time.time()

        logger.info(
            "Appeal %s escalated to dispute resolution: %s",
            appeal_id, escalation_ref,
        )
        return appeal

    async def get_appeal(self, appeal_id: str) -> dict:
        """Get an appeal by ID.

        Returns:
            The appeal record.
        """
        appeal = self._appeals.get(appeal_id)
        if not appeal:
            raise ValueError(f"Appeal '{appeal_id}' not found")
        return appeal
