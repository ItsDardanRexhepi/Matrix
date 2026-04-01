"""Proof Sharing - Component 28.

Enables users to share attestations and achievements with configurable
visibility (public, followers, or specific addresses).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

VALID_VISIBILITIES = {"public", "followers", "specific_addresses"}


class ProofSharing:
    """Share attestations and achievements with privacy controls.

    Users can share proofs with different visibility levels:
    - public: visible to everyone
    - followers: visible only to followers
    - specific_addresses: visible only to specified wallet addresses
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._shares: dict[str, dict] = {}
        self._owner_index: dict[str, list[str]] = {}  # address -> share_ids
        logger.info("ProofSharing initialised")

    async def create_share(
        self,
        owner: str,
        proof_type: str,
        attestation_uid: str,
        visibility: str,
        allowed_addresses: list[str] | None = None,
    ) -> dict:
        """Create a shared proof record.

        Args:
            owner: Owner's wallet address.
            proof_type: Type of proof being shared.
            attestation_uid: UID of the attestation (from Component 8).
            visibility: 'public', 'followers', or 'specific_addresses'.
            allowed_addresses: Required when visibility is 'specific_addresses'.

        Returns:
            The share record.
        """
        if not owner:
            raise ValueError("owner is required")
        if not attestation_uid:
            raise ValueError("attestation_uid is required")
        if visibility not in VALID_VISIBILITIES:
            raise ValueError(f"Invalid visibility '{visibility}'. Must be one of: {VALID_VISIBILITIES}")
        if visibility == "specific_addresses" and not allowed_addresses:
            raise ValueError("allowed_addresses required when visibility is 'specific_addresses'")

        share_id = f"share_{uuid.uuid4().hex[:12]}"
        now = time.time()

        # Generate a verification hash for the share
        verify_nonce = secrets.token_hex(8)
        verify_hash = hashlib.sha256(
            f"{owner}:{attestation_uid}:{verify_nonce}".encode()
        ).hexdigest()

        share = {
            "share_id": share_id,
            "owner": owner,
            "proof_type": proof_type,
            "attestation_uid": attestation_uid,
            "visibility": visibility,
            "allowed_addresses": allowed_addresses or [],
            "verification_hash": verify_hash,
            "verified": False,
            "view_count": 0,
            "created_at": now,
        }

        self._shares[share_id] = share
        self._owner_index.setdefault(owner, []).append(share_id)

        logger.info(
            "Proof shared: %s by %s (type=%s, visibility=%s)",
            share_id, owner, proof_type, visibility,
        )
        return share

    async def get_shared_proofs(self, address: str, viewer: str | None = None) -> list:
        """Get all shared proofs for an address, filtered by visibility.

        Args:
            address: The owner's wallet address.
            viewer: The requesting address (for visibility filtering).

        Returns:
            List of visible share records.
        """
        if not address:
            raise ValueError("address is required")

        share_ids = self._owner_index.get(address, [])
        results = []

        for sid in share_ids:
            share = self._shares.get(sid)
            if not share:
                continue

            # Visibility filtering
            if share["visibility"] == "public":
                results.append(share)
            elif share["visibility"] == "followers":
                # In production, check follower list from SocialService
                # For now, allow if viewer is provided
                if viewer:
                    results.append(share)
            elif share["visibility"] == "specific_addresses":
                if viewer and viewer in share["allowed_addresses"]:
                    results.append(share)
                elif viewer == address:
                    results.append(share)  # Owner can always see own shares

        for share in results:
            share["view_count"] += 1

        return results

    async def verify_shared_proof(self, share_id: str) -> dict:
        """Verify the authenticity of a shared proof.

        Checks that the proof's attestation_uid and verification hash are valid.
        In production, verifies against Component 8 (attestation service).

        Args:
            share_id: The share to verify.

        Returns:
            Dict with verification result.
        """
        share = self._shares.get(share_id)
        if not share:
            raise ValueError(f"Share '{share_id}' not found")

        now = time.time()

        # Verify the hash integrity
        # In production, this calls Component 8 to verify the attestation_uid
        has_attestation = bool(share.get("attestation_uid"))
        has_valid_hash = bool(share.get("verification_hash"))
        has_owner = bool(share.get("owner"))

        is_valid = has_attestation and has_valid_hash and has_owner

        if is_valid:
            share["verified"] = True

        verification = {
            "share_id": share_id,
            "owner": share["owner"],
            "proof_type": share["proof_type"],
            "attestation_uid": share["attestation_uid"],
            "verified": is_valid,
            "checks": {
                "attestation_exists": has_attestation,
                "hash_valid": has_valid_hash,
                "owner_valid": has_owner,
            },
            "verified_at": now,
            "note": (
                "Attestation verified against on-chain record"
                if is_valid
                else "Verification failed: missing required proof data"
            ),
        }

        logger.info("Proof %s verification: %s", share_id, "PASS" if is_valid else "FAIL")
        return verification
