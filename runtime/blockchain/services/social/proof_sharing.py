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
from typing import Any, Callable

logger = logging.getLogger(__name__)

VALID_VISIBILITIES = {"public", "followers", "specific_addresses"}


class ProofSharing:
    """Share attestations and achievements with privacy controls.

    Users can share proofs with different visibility levels:
    - public: visible to everyone
    - followers: visible only to the owner's followers (and the owner)
    - specific_addresses: visible only to specified wallet addresses (and the
      owner)

    "Only to followers" is decided by ``is_follower(owner, viewer)``, which
    SocialService supplies from its follow graph. A followers share used to be
    returned to ANY caller who named a viewer — the check was `if viewer:`,
    beside a comment saying the follower list would be checked "in
    production". With no resolver supplied the answer is the owner alone,
    because a guess about who follows whom is not a privacy control.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        is_follower: Callable[[str, str], bool] | None = None,
    ) -> None:
        self.config = config or {}
        self._is_follower = is_follower
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
                if viewer and (viewer == address or self._follows(address, viewer)):
                    results.append(share)
            elif share["visibility"] == "specific_addresses":
                if viewer and viewer in share["allowed_addresses"]:
                    results.append(share)
                elif viewer == address:
                    results.append(share)  # Owner can always see own shares

        for share in results:
            share["view_count"] += 1

        return results

    def _follows(self, owner: str, viewer: str) -> bool:
        """Does *viewer* follow *owner*? No resolver, or a resolver that
        fails, is a no: the share stays with its owner."""
        if self._is_follower is None:
            return False
        try:
            return bool(self._is_follower(owner, viewer))
        except Exception:  # noqa: BLE001 — a failed lookup is not a yes
            logger.warning("follower lookup failed for owner=%s", owner)
            return False

    async def verify_shared_proof(self, share_id: str) -> dict:
        """Check that a share record is complete.

        What is checked is that the record carries an attestation uid, a
        verification hash and an owner. The attestation is NOT looked up — no
        attestation service or chain is consulted here — so ``verified`` means
        "the record is well-formed", and the note says so. It used to say
        "Attestation verified against on-chain record" on a check that read
        three fields of a local dict.

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
                "Share record is complete (attestation uid, verification "
                "hash and owner present). The attestation itself was not "
                "checked against any chain."
                if is_valid
                else "Verification failed: missing required proof data"
            ),
            "attestation_checked_on_chain": False,
        }

        logger.info("Proof %s verification: %s", share_id, "PASS" if is_valid else "FAIL")
        return verification
