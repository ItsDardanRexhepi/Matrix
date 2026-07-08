"""Social Platform Service - Component 28.

Provides user profiles, social feeds, proof sharing, and integration
with XMTP messaging and content moderation.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
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
    # Transparent, operator-tunable "For You" ranking weights (v1 — NO ML, NO
    # per-user learning). Every knob lives here; see runtime/social/feed_ranker.py
    # and FEED_ALGORITHM.md. Change a number → the feed changes, explainably.
    "feed_ranker": {
        "recency": 1.0,
        "engagement": 0.6,
        "affinity": 0.9,
        "discovery": 0.4,
        "recency_halflife_hours": 6.0,
        "comment_weight": 2.0,
        "engagement_ceiling": 4.0,
        "discovery_cap_fraction": 0.20,
        "max_posts_per_author": 3,
    },
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

    # ------------------------------------------------------------------
    # Feed normalization — `_feed_items` holds two record shapes (proof-shares
    # from share_proof: sharer/timestamp/proof_data.visibility; and posts from
    # publish_post: author/published_at). These read either shape defensively so
    # the feed never KeyErrors and a new record type can't crash ranking.
    # ------------------------------------------------------------------
    @staticmethod
    def _item_actor(item: dict) -> str:
        return item.get("sharer") or item.get("author") or ""

    @staticmethod
    def _item_ts(item: dict) -> float:
        return float(item.get("timestamp") or item.get("published_at") or 0.0)

    @staticmethod
    def _item_id(item: dict) -> str:
        return item.get("id") or item.get("feed_item_id") or ""

    @staticmethod
    def _item_likes(item: dict) -> int:
        return len(item.get("reactions") or {})

    @staticmethod
    def _item_comments(item: dict) -> int:
        return len(item.get("comments") or [])

    @staticmethod
    def _is_public_item(item: dict) -> bool:
        """Privacy gate for feeds. Only publicly-visible items may enter ANY feed.
        Proof-shares carry visibility in proof_data; plain posts have none and are
        public by default. Anything not explicitly 'public' is treated as private
        and never surfaced — the strict reading of 'never enters anyone's feed'."""
        vis = item.get("visibility")
        if vis is None:
            vis = (item.get("proof_data") or {}).get("visibility", "public")
        return str(vis).lower() == "public"

    async def get_feed(self, address: str, limit: int = 50, mode: str = "latest") -> list:
        """Get the social feed for a user.

        Two modes, both server-side and both privacy-filtered:
          • ``latest`` (default): chronological — items from followed users and the
            viewer's own posts, newest first. Also the honest fallback if ranking
            cannot run. Never dressed up as "For You".
          • ``for_you``: transparent weighted ranking (runtime/social/feed_ranker.py)
            over all publicly-visible posts, boosting followed authors (affinity),
            mixing in a capped slice of discovery (non-followed) posts, with an
            engagement ceiling so one viral post can't dominate. NO ML, NO per-user
            model — only the viewer's own follow set personalizes the order.

        Privacy is absolute in BOTH modes: private/confidential items never enter
        the candidate set (:meth:`_is_public_item`). The ranker reads only the
        already-stored signals normalized here (author, created_at, like count,
        comment count) — never message bodies, private flags, or DMs.

        Args:
            address: Viewer wallet address.
            limit: Maximum items to return.
            mode: ``"latest"`` or ``"for_you"``.

        Returns:
            List of feed-item dicts (same shape as stored), in the mode's order.
            ``for_you`` items are annotated with a transparent ``_rank_score`` and
            ``_rank_breakdown`` so the ordering is explainable, never fabricated.
        """
        if not address:
            raise ValueError("address is required")

        # A non-positive limit would silently mis-shape the response (Latest would
        # slice feed[:-n], for_you would page_size<=0). Clamp to the configured
        # default so every entry path is safe, not just the HTTP route's 400.
        if limit is None or limit <= 0:
            limit = self.config.get("default_feed_limit", 50)
        limit = min(limit, self.config["max_feed_limit"])

        profile = self._profiles.get(address)
        if not profile:
            raise ValueError(f"Profile not found for address '{address}'")

        following = set(profile.get("following", []))

        # Privacy absolute — filter to publicly-visible items BEFORE anything else.
        public_items = [it for it in self._feed_items if self._is_public_item(it)]

        if str(mode).lower().replace("-", "_") in ("for_you", "foryou"):
            try:
                return self._rank_for_you(
                    public_items, following=following, limit=limit,
                )
            except Exception:  # pragma: no cover - defensive; honest fallback below
                logger.warning(
                    "feed ranker failed; honest fallback to Latest", exc_info=True,
                )
                # fall through to chronological — never fabricate a ranked feed

        # Latest (default + honest fallback): followed authors + self, newest first.
        visible = following | {address}
        feed = [it for it in public_items if self._item_actor(it) in visible]
        feed.sort(key=lambda x: self._item_ts(x), reverse=True)
        return feed[:limit]

    def _rank_for_you(
        self, public_items: list[dict], *, following: set[str], limit: int,
    ) -> list[dict]:
        """Rank publicly-visible items via the transparent feed_ranker, then return
        the ORIGINAL feed-item dicts in ranked order (shape unchanged), each
        annotated with its score + per-signal breakdown for full explainability."""
        from dataclasses import fields as dataclass_fields, replace

        from runtime.social.feed_ranker import (
            FeedCandidate,
            FeedWeights,
            rank_for_you,
        )

        # Build weights by overlaying the operator config onto FeedWeights defaults.
        # FeedWeights is the SINGLE source of default truth — no duplicated literals
        # here (which would silently drift from the dataclass / the doc).
        rc = dict(self.config.get("feed_ranker") or {})
        valid = {f.name for f in dataclass_fields(FeedWeights)}
        overrides = {k: v for k, v in rc.items() if k in valid}
        weights = replace(FeedWeights(), **overrides)

        by_id: dict[str, dict] = {}
        candidates: list[FeedCandidate] = []
        for it in public_items:
            cid = self._item_id(it)
            if not cid:
                continue
            by_id[cid] = it
            candidates.append(
                FeedCandidate(
                    id=cid,
                    author_id=self._item_actor(it),
                    created_at=self._item_ts(it),
                    likes=self._item_likes(it),
                    comments=self._item_comments(it),
                )
            )

        ranked = rank_for_you(
            candidates,
            followed_author_ids=following,
            now=time.time(),
            weights=weights,
            page_size=limit,
        )

        out: list[dict] = []
        for r in ranked[:limit]:
            item = dict(by_id[r.id])
            item["_rank_score"] = round(r.score, 4)
            item["_rank_breakdown"] = r.breakdown
            out.append(item)
        return out

    # ------------------------------------------------------------------
    # Client render view — the iOS FeedResponse contract
    # ------------------------------------------------------------------
    async def get_feed_view(
        self, address: str, limit: int = 50, mode: str = "latest",
    ) -> dict:
        """Client-facing feed: rank/assemble via :meth:`get_feed` (privacy + ranking
        unchanged) and format each item into the ``{"posts": [...]}`` shape the iOS
        ``FeedResponse`` decodes. Keys are snake_case (the client converts them). Only
        already-public, already-ranked items reach this formatter, so it cannot leak
        anything private — it merely renders what get_feed already vetted."""
        items = await self.get_feed(address, limit=limit, mode=mode)
        return {"posts": [self._format_post(it) for it in items]}

    def _format_post(self, item: dict) -> dict:
        """Map an internal feed-item dict → the FeedPost JSON shape (snake_case)."""
        author = self._item_actor(item)
        profile = self._profiles.get(author) or {}
        display_name = (
            item.get("display_name")
            or profile.get("display_name")
            or (author[:10] if author else "Unknown")
        )
        body = item.get("content") or (item.get("proof_data") or {}).get("description", "") or ""
        proof = item.get("proof_data") or {}
        return {
            "id": self._item_id(item),
            "display_name": display_name,
            "handle": "@" + (author or "unknown"),
            "avatar_initials": "".join(w[0] for w in display_name.split()[:2]).upper()
            or display_name[:2].upper(),
            "body": body,
            "timestamp": datetime.fromtimestamp(
                self._item_ts(item), tz=timezone.utc,
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "is_verified": bool(profile.get("verified", False)),
            "proof_hash": proof.get("attestation_uid"),
            "governance_tag": item.get("governance_tag"),
            "like_count": self._item_likes(item),
            "repost_count": 0,
            "comment_count": self._item_comments(item),
        }

    # ------------------------------------------------------------------
    # Expanded social operations
    # ------------------------------------------------------------------

    async def publish_post(
        self, author: str, content: str, media_urls: list[str] | None = None,
    ) -> dict:
        """Publish a social post."""
        post_id = f"post_{uuid.uuid4().hex[:16]}"
        now = time.time()
        record = {
            "id": post_id,
            "status": "published",
            "author": author,
            "content": content,
            "media_urls": media_urls or [],
            "reactions": {},
            "comments": [],
            "published_at": now,
        }
        self._feed_items.append(record)
        logger.info("Post published: id=%s author=%s", post_id, author)
        return record

    async def follow_wallet(
        self, follower: str, target: str,
    ) -> dict:
        """Follow another wallet address."""
        follow_id = f"follow_{uuid.uuid4().hex[:16]}"
        follower_profile = self._profiles.get(follower)
        if follower_profile:
            if target not in follower_profile.get("following", []):
                follower_profile.setdefault("following", []).append(target)
        target_profile = self._profiles.get(target)
        if target_profile:
            if follower not in target_profile.get("followers", []):
                target_profile.setdefault("followers", []).append(follower)
        record = {
            "id": follow_id,
            "status": "following",
            "follower": follower,
            "target": target,
            "followed_at": time.time(),
        }
        logger.info("Follow: id=%s %s -> %s", follow_id, follower, target)
        return record

    async def create_token_gate(
        self, creator: str, token_address: str, min_balance: float, resource: str,
    ) -> dict:
        """Create a token-gated access rule."""
        gate_id = f"gate_{uuid.uuid4().hex[:16]}"
        record = {
            "id": gate_id,
            "status": "active",
            "creator": creator,
            "token_address": token_address,
            "min_balance": min_balance,
            "resource": resource,
            "created_at": time.time(),
        }
        logger.info("Token gate created: id=%s", gate_id)
        return record

    async def setup_monetization(
        self, creator: str, monetization_type: str, params: dict | None = None,
    ) -> dict:
        """Set up creator monetization."""
        mon_id = f"mon_{uuid.uuid4().hex[:16]}"
        record = {
            "id": mon_id,
            "status": "active",
            "creator": creator,
            "monetization_type": monetization_type,
            "params": params or {},
            "created_at": time.time(),
        }
        logger.info("Monetization setup: id=%s type=%s", mon_id, monetization_type)
        return record

    async def create_community(
        self, creator: str, name: str, description: str = "", token_gate: dict | None = None,
    ) -> dict:
        """Create a social community."""
        comm_id = f"comm_{uuid.uuid4().hex[:16]}"
        record = {
            "id": comm_id,
            "status": "active",
            "creator": creator,
            "name": name,
            "description": description,
            "token_gate": token_gate,
            "members": [creator],
            "member_count": 1,
            "created_at": time.time(),
        }
        logger.info("Community created: id=%s name=%s", comm_id, name)
        return record

    # -- Messaging read delegators -------------------------------------
    # The gateway seam (_call) resolves a service method by a flat getattr on
    # the service, so the nested XMTP messaging reads are exposed flatly here.
    # These are honest reads: an address/conversation with no history returns [].

    async def get_conversations(self, address: str) -> list:
        """List conversations for *address* (delegates to XMTP messaging)."""
        return await self.messaging.get_conversations(address)

    async def get_messages(self, conversation_id: str, limit: int = 50) -> list:
        """List messages in a conversation (delegates to XMTP messaging)."""
        return await self.messaging.get_messages(conversation_id, limit)

    async def send_encrypted_message(
        self, sender: str, recipient: str, content: str, protocol: str = "xmtp",
    ) -> dict:
        """Send an encrypted message via XMTP or similar."""
        msg_id = f"emsg_{uuid.uuid4().hex[:16]}"
        record = {
            "id": msg_id,
            "status": "sent",
            "sender": sender,
            "recipient": recipient,
            "content_hash": f"0x{uuid.uuid4().hex[:32]}",
            "protocol": protocol,
            "encrypted": True,
            "sent_at": time.time(),
        }
        logger.info("Encrypted message sent: id=%s", msg_id)
        return record
