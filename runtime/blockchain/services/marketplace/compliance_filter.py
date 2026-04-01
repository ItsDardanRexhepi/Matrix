"""Compliance Filter - Component 24.

Scans marketplace listings for prohibited content using keyword and
metadata analysis. Blocks weapons, drugs, stolen property, and counterfeit goods.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

BLOCKED_CATEGORIES = {
    "weapons": [
        "firearm", "gun", "rifle", "pistol", "ammunition", "ammo", "explosive",
        "grenade", "bomb", "switchblade", "brass knuckles", "silencer", "suppressor",
    ],
    "drugs": [
        "cocaine", "heroin", "methamphetamine", "fentanyl", "lsd", "mdma",
        "narcotics", "controlled substance", "illicit drug",
    ],
    "stolen_property": [
        "stolen", "hot goods", "fell off a truck", "no questions asked",
        "burgled", "looted",
    ],
    "counterfeit": [
        "counterfeit", "fake id", "forged", "replica passport", "knock-off",
        "bootleg", "pirated", "unauthorized copy",
    ],
}


class ComplianceFilter:
    """Scans listings for prohibited content and manages flagging.

    Performs keyword-based and metadata scanning against blocked categories.
    Listings that match are rejected or flagged for manual review.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._flags: dict[str, dict] = {}
        self._custom_blocked_keywords: list[str] = self.config.get("custom_blocked_keywords", [])
        logger.info("ComplianceFilter initialised with %d blocked categories", len(BLOCKED_CATEGORIES))

    def _scan_text(self, text: str) -> list[dict]:
        """Scan text against all blocked keyword lists.

        Returns list of matches with category and keyword.
        """
        matches = []
        text_lower = text.lower()
        for category, keywords in BLOCKED_CATEGORIES.items():
            for keyword in keywords:
                if keyword in text_lower:
                    matches.append({"category": category, "keyword": keyword})

        for keyword in self._custom_blocked_keywords:
            if keyword.lower() in text_lower:
                matches.append({"category": "custom_blocked", "keyword": keyword})

        return matches

    async def check_listing(self, listing: dict) -> dict:
        """Check a listing for compliance violations.

        Scans title, description, and metadata fields against blocked keyword lists.

        Args:
            listing: The listing record to check.

        Returns:
            Dict with decision ('approved', 'rejected', or 'flagged'),
            reason, and matched violations.
        """
        metadata = listing.get("metadata", {})
        title = metadata.get("title", "")
        description = metadata.get("description", "")
        tags = " ".join(metadata.get("tags", []))
        combined_text = f"{title} {description} {tags}"

        violations = self._scan_text(combined_text)

        if not violations:
            return {
                "decision": "approved",
                "reason": None,
                "violations": [],
                "checked_at": time.time(),
            }

        # Hard-block categories result in rejection
        hard_block_categories = {"weapons", "drugs", "stolen_property", "counterfeit"}
        hard_violations = [v for v in violations if v["category"] in hard_block_categories]

        if hard_violations:
            reason = (
                f"Listing contains prohibited content: "
                f"{', '.join(set(v['category'] for v in hard_violations))}"
            )
            logger.warning(
                "Listing %s REJECTED: %s",
                listing.get("listing_id", "unknown"),
                reason,
            )
            return {
                "decision": "rejected",
                "reason": reason,
                "violations": hard_violations,
                "checked_at": time.time(),
            }

        # Soft matches are flagged for review
        reason = f"Listing flagged for review: {', '.join(set(v['category'] for v in violations))}"
        return {
            "decision": "flagged",
            "reason": reason,
            "violations": violations,
            "checked_at": time.time(),
        }

    async def flag_listing(self, listing_id: str, reason: str, reporter: str) -> dict:
        """Manually flag a listing for review.

        Args:
            listing_id: The listing to flag.
            reason: Why the listing is being flagged.
            reporter: Wallet address of the reporter.

        Returns:
            The flag record.
        """
        if not listing_id:
            raise ValueError("listing_id is required")
        if not reason:
            raise ValueError("reason is required")
        if not reporter:
            raise ValueError("reporter is required")

        flag_id = f"flag_{uuid.uuid4().hex[:12]}"
        flag = {
            "flag_id": flag_id,
            "listing_id": listing_id,
            "reason": reason,
            "reporter": reporter,
            "status": "pending_review",
            "created_at": time.time(),
        }
        self._flags[flag_id] = flag
        logger.info("Listing %s flagged by %s: %s", listing_id, reporter, reason)
        return flag
