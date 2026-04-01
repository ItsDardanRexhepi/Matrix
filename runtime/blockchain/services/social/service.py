"""Social Platform Service - Component 28.

Provides user profiles, social feeds, proof sharing, and integration
with XMTP messaging and content moderation.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from .messaging import XMTPMessaging
from .content_moderation import ContentModeration
from .proof_sharing import ProofSharing

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "max_bio_length": 500,
    "max_display_name_length": 50,
    "max_feed_limit": 200,
    "default_feed_limit": 50,
    "allowed_proof_types": [
        "attestation", "achievement", "credential", "badge", "verification",
    ],
}


class SocialService:
    """Social platform with profiles, feeds, and proof sharing.

    Users create profiles tied to wallet addresses, share proofs and
    attestations, and interact via XMTP encrypted messaging.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self._profiles: dict[str, dict] = {}
        self._feed_items: list[dict] = []
        self.messaging = XMTPMessaging(self.config)
        self.moderation = ContentModeration(self.config)
        self.proof_sharing = ProofSharing(self.config)
        logger.info("SocialService initialised")

    async def create_profile(self, address: str, display_name: str, bio: str) -> dict:
        """Create a new user profile.

        Args:
            address: Wallet address (unique identifier).
            display_name: Public display name.
            bio: User biography.

        Returns:
            The created profile record.
        """
        if not address:
            raise ValueError("address is required")
        if address in self._profiles:
            raise ValueError(f"Profile already exists for address '{address}'")
        if not display_name:
            raise ValueError("display_name is required")
        if len(display_name) > self.config["max_display_name_length"]:
            raise ValueError(f"display_name cannot exceed {self.config['max_display_name_length']} characters")
        if len(bio) > self.config["max_bio_length"]:
            raise ValueError(f"bio cannot exceed {self.config['max_bio_length']} characters")

        # Check display name for content violations
        name_check = await self.moderation.check_content(display_name, "display_name")
        if name_check["action"] == "block":
            raise ValueError(f"Display name violates content policy: {name_check['reason']}")

        bio_check = await self.moderation.check_content(bio, "bio")
        if bio_check["action"] == "block":
            raise ValueError(f"Bio violates content policy: {bio_check['reason']}")

        now = time.time()
        profile = {
            "address": address,
            "display_name": display_name,
            "bio": bio,
            "avatar_url": None,
            "followers": [],
            "following": [],
            "shared_proofs": [],
            "created_at": now,
            "updated_at": now,
            "status": "active",
        }

        self._profiles[address] = profile
        logger.info("Profile created for address %s (name=%s)", address, display_name)
        return profile

    async def update_profile(self, address: str, updates: dict) -> dict:
        """Update an existing profile.

        Args:
            address: Wallet address.
            updates: Fields to update (display_name, bio, avatar_url).

        Returns:
            The updated profile record.
        """
        profile = self._profiles.get(address)
        if not profile:
            raise ValueError(f"Profile not found for address '{address}'")

        allowed = {"display_name", "bio", "avatar_url"}
        for key, value in updates.items():
            if key not in allowed:
                continue

            if key == "display_name":
                if len(value) > self.config["max_display_name_length"]:
                    raise ValueError(f"display_name too long")
                check = await self.moderation.check_content(value, "display_name")
                if check["action"] == "block":
                    raise ValueError(f"Display name violates content policy")

            if key == "bio":
                if len(value) > self.config["max_bio_length"]:
                    raise ValueError("bio too long")
                check = await self.moderation.check_content(value, "bio")
                if check["action"] == "block":
                    raise ValueError("Bio violates content policy")

            profile[key] = value

        profile["updated_at"] = time.time()
        logger.info("Profile updated for %s", address)
        return profile

    async def get_profile(self, address: str) -> dict:
        """Get a user's profile.

        Args:
            address: Wallet address.

        Returns:
            The profile record.
        """
        profile = self._profiles.get(address)
        if not profile:
            raise ValueError(f"Profile not found for address '{address}'")
        return profile

    async def share_proof(self, sharer: str, proof_type: str, proof_data: dict) -> dict:
        """Share an attestation or proof on the social feed.

        Args:
            sharer: Sharer's wallet address.
            proof_type: Type of proof ('attestation', 'achievement', etc.).
            proof_data: Proof details including attestation_uid.

        Returns:
            The feed item record.
        """
        if not sharer:
            raise ValueError("sharer is required")
        if proof_type not in self.config["allowed_proof_types"]:
            raise ValueError(
                f"Invalid proof_type '{proof_type}'. Must be one of: {self.config['allowed_proof_types']}"
            )

        profile = self._profiles.get(sharer)
        if not profile:
            raise ValueError(f"Profile not found for address '{sharer}'")

        # Content check on any text in proof_data
        description = proof_data.get("description", "")
        if description:
            check = await self.moderation.check_content(description, "proof_description")
            if check["action"] == "block":
                raise ValueError("Proof description violates content policy")

        feed_item_id = f"feed_{uuid.uuid4().hex[:12]}"
        now = time.time()

        feed_item = {
            "feed_item_id": feed_item_id,
            "sharer": sharer,
            "proof_type": proof_type,
            "proof_data": proof_data,
            "display_name": profile["display_name"],
            "timestamp": now,
            "reactions": {},
            "comments": [],
        }

        self._feed_items.append(feed_item)
        profile["shared_proofs"].append(feed_item_id)

        # Create a share record in proof_sharing
        attestation_uid = proof_data.get("attestation_uid", "")
        if attestation_uid:
            visibility = proof_data.get("visibility", "public")
            await self.proof_sharing.create_share(sharer, proof_type, attestation_uid, visibility)

        logger.info("Proof shared by %s (type=%s, id=%s)", sharer, proof_type, feed_item_id)
        return feed_item

    async def get_feed(self, address: str, limit: int = 50) -> list:
        """Get the social feed for a user.

        Returns items from followed users and the user's own posts,
        sorted by most recent first.

        Args:
            address: Wallet address.
            limit: Maximum items to return.

        Returns:
            List of feed items.
        """
        if not address:
            raise ValueError("address is required")

        limit = min(limit, self.config["max_feed_limit"])

        profile = self._profiles.get(address)
        if not profile:
            raise ValueError(f"Profile not found for address '{address}'")

        # Collect from followed users and self
        visible_addresses = set(profile.get("following", []))
        visible_addresses.add(address)

        feed = [
            item for item in self._feed_items
            if item["sharer"] in visible_addresses
        ]

        # Sort by timestamp descending
        feed.sort(key=lambda x: x["timestamp"], reverse=True)
        return feed[:limit]
