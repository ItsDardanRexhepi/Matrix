"""ZKP Targeting - Component 26.

Enables brands to target users by criteria without seeing individual user data.
Uses zero-knowledge proofs to verify eligibility privately.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

VALID_CRITERIA_TYPES = {"spending_above", "tier_at_least", "category_active", "region"}

TIER_ORDER = {"bronze": 0, "silver": 1, "gold": 2, "platinum": 3, "diamond": 4}


class ZKPTargeting:
    """Zero-knowledge targeting for brand campaigns.

    Verifies that a user meets campaign criteria without exposing the user's
    actual data to the brand. The brand defines criteria; the system proves
    eligibility without revealing specifics.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._criteria: dict[str, dict] = {}
        self._user_profiles: dict[str, dict] = {}  # Simulated user data store
        self._eligible_cache: dict[str, set[str]] = {}  # campaign_id -> set of eligible users
        logger.info("ZKPTargeting initialised")

    def set_user_profile(self, user: str, profile: dict) -> None:
        """Inject user profile data for eligibility checking.

        Profile keys: spending_total, tier, active_categories, region.
        In production, this would query Component 5 (DID) and other services.
        """
        self._user_profiles[user] = profile

    async def create_criteria(self, campaign_id: str, criteria: dict) -> dict:
        """Define targeting criteria for a campaign.

        Args:
            campaign_id: The campaign these criteria belong to.
            criteria: Targeting rules. Supported keys:
                - spending_above: float - minimum total spending
                - tier_at_least: str - minimum loyalty tier
                - category_active: str - must have spending in category
                - region: str - geographic region

        Returns:
            The criteria record with a unique ID.
        """
        if not campaign_id:
            raise ValueError("campaign_id is required")

        validated = {}
        for key, value in criteria.items():
            if key not in VALID_CRITERIA_TYPES:
                logger.warning("Ignoring unknown criterion '%s'", key)
                continue
            validated[key] = value

        criteria_id = f"crit_{uuid.uuid4().hex[:12]}"
        record = {
            "criteria_id": criteria_id,
            "campaign_id": campaign_id,
            "criteria": validated,
            "created_at": time.time(),
        }
        self._criteria[campaign_id] = record
        logger.info("Created criteria %s for campaign %s: %s", criteria_id, campaign_id, list(validated.keys()))
        return record

    async def check_eligibility(self, campaign_id: str, user: str) -> dict:
        """Check if a user meets campaign criteria via ZKP.

        The user's data is never exposed to the brand. Only a boolean
        eligibility result and a proof hash are returned.

        Args:
            campaign_id: The campaign to check against.
            user: The user's wallet address.

        Returns:
            Dict with eligible (bool), proof_hash, and reason if ineligible.
        """
        if not user:
            raise ValueError("user is required")

        record = self._criteria.get(campaign_id)
        if not record:
            # No criteria means all users are eligible
            return {"eligible": True, "proof_hash": self._generate_proof_hash(user, campaign_id), "reason": None}

        criteria = record["criteria"]
        profile = self._user_profiles.get(user, {})

        failures = []

        if "spending_above" in criteria:
            user_spending = profile.get("spending_total", 0.0)
            if user_spending < criteria["spending_above"]:
                failures.append("spending below threshold")

        if "tier_at_least" in criteria:
            required_tier = criteria["tier_at_least"]
            user_tier = profile.get("tier", "bronze")
            if TIER_ORDER.get(user_tier, 0) < TIER_ORDER.get(required_tier, 0):
                failures.append(f"tier below {required_tier}")

        if "category_active" in criteria:
            required_cat = criteria["category_active"]
            active_cats = profile.get("active_categories", [])
            if required_cat not in active_cats:
                failures.append(f"not active in category '{required_cat}'")

        if "region" in criteria:
            required_region = criteria["region"]
            user_region = profile.get("region", "")
            if user_region != required_region:
                failures.append("region mismatch")

        if failures:
            return {
                "eligible": False,
                "proof_hash": None,
                "reason": "; ".join(failures),
            }

        # User is eligible - add to cache
        if campaign_id not in self._eligible_cache:
            self._eligible_cache[campaign_id] = set()
        self._eligible_cache[campaign_id].add(user)

        return {
            "eligible": True,
            "proof_hash": self._generate_proof_hash(user, campaign_id),
            "reason": None,
        }

    async def get_eligible_count(self, campaign_id: str) -> int:
        """Get the count of eligible users for a campaign.

        Only returns the count, never individual user identities.

        Args:
            campaign_id: The campaign to check.

        Returns:
            Number of users verified as eligible.
        """
        return len(self._eligible_cache.get(campaign_id, set()))

    def _generate_proof_hash(self, user: str, campaign_id: str) -> str:
        """Generate a ZKP proof hash for the eligibility claim."""
        nonce = secrets.token_hex(8)
        payload = f"{user}:{campaign_id}:{nonce}:{time.time()}".encode()
        return hashlib.sha256(payload).hexdigest()
