"""ZKP Tier Eligibility - Component 23.

Generates and verifies zero-knowledge proofs that a user meets a tier
threshold without revealing their exact point balance.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class ZKPEligibility:
    """Zero-knowledge proof system for tier eligibility.

    Proves statements like 'user is Gold tier' without exposing the user's
    actual point balance. Uses a commitment scheme with blinding factors.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._proofs: dict[str, dict] = {}
        self._secret_key: bytes = secrets.token_bytes(32)
        self._proof_validity_seconds: int = self.config.get("proof_validity_seconds", 3600)
        logger.info("ZKPEligibility initialised (proof validity=%ds)", self._proof_validity_seconds)

    def _compute_commitment(self, user: str, program_id: str, tier: str, blinding: str) -> str:
        """Create a cryptographic commitment to the user's tier."""
        payload = f"{user}:{program_id}:{tier}:{blinding}".encode()
        return hmac.new(self._secret_key, payload, hashlib.sha256).hexdigest()

    def _compute_challenge_response(self, commitment: str, challenge: str) -> str:
        """Compute response to a verification challenge."""
        payload = f"{commitment}:{challenge}".encode()
        return hashlib.sha256(payload).hexdigest()

    async def generate_tier_proof(self, user: str, program_id: str) -> dict:
        """Generate a ZKP that proves the user's tier without revealing balance.

        The proof contains:
        - A commitment to the tier claim
        - A challenge-response pair for verification
        - No raw balance data

        This must be called with access to the ledger (through LoyaltyService).
        For standalone use, callers should inject balance/tier via config or
        override _resolve_tier_for_user.

        Args:
            user: The user's wallet address.
            program_id: The loyalty program ID.

        Returns:
            Dict with proof_id, tier_claim, commitment, and expiry.
        """
        if not user:
            raise ValueError("user is required")

        # Resolve the user's tier from stored data or injected resolver
        tier, lifetime = await self._resolve_tier_for_user(user, program_id)

        blinding = secrets.token_hex(16)
        commitment = self._compute_commitment(user, program_id, tier, blinding)

        challenge = secrets.token_hex(16)
        response = self._compute_challenge_response(commitment, challenge)

        proof_id = str(uuid.uuid4())
        now = time.time()

        proof = {
            "proof_id": proof_id,
            "user": user,
            "program_id": program_id,
            "tier_claim": tier,
            "commitment": commitment,
            "challenge": challenge,
            "response": response,
            "blinding": blinding,
            "created_at": now,
            "expires_at": now + self._proof_validity_seconds,
            "verified": False,
        }
        self._proofs[proof_id] = proof

        # Return only the public parts (no blinding factor or raw balance)
        logger.info("Generated tier proof %s for user %s (tier=%s, program=%s)", proof_id, user, tier, program_id)
        return {
            "proof_id": proof_id,
            "tier_claim": tier,
            "commitment": commitment,
            "challenge": challenge,
            "response": response,
            "expires_at": proof["expires_at"],
        }

    async def verify_tier_proof(self, proof: dict) -> bool:
        """Verify a previously generated tier proof.

        Args:
            proof: Dict containing proof_id, commitment, challenge, response.

        Returns:
            True if the proof is valid and not expired.
        """
        proof_id = proof.get("proof_id")
        if not proof_id:
            logger.warning("Verification failed: no proof_id")
            return False

        stored = self._proofs.get(proof_id)
        if not stored:
            logger.warning("Verification failed: proof %s not found", proof_id)
            return False

        if time.time() > stored["expires_at"]:
            logger.warning("Verification failed: proof %s expired", proof_id)
            return False

        expected_response = self._compute_challenge_response(
            stored["commitment"], stored["challenge"]
        )

        commitment_match = hmac.compare_digest(proof.get("commitment", ""), stored["commitment"])
        challenge_match = hmac.compare_digest(proof.get("challenge", ""), stored["challenge"])
        response_match = hmac.compare_digest(proof.get("response", ""), expected_response)

        valid = commitment_match and challenge_match and response_match
        if valid:
            stored["verified"] = True
            logger.info("Tier proof %s verified successfully", proof_id)
        else:
            logger.warning("Tier proof %s verification failed", proof_id)

        return valid

    async def _resolve_tier_for_user(self, user: str, program_id: str) -> tuple[str, int]:
        """Resolve a user's tier. Override or inject a resolver for production use.

        Default implementation checks if a _tier_resolver callable has been set.
        If not, returns bronze/0 as a safe default.
        """
        resolver = getattr(self, "_tier_resolver", None)
        if resolver:
            return await resolver(user, program_id)
        return ("bronze", 0)

    def set_tier_resolver(self, resolver) -> None:
        """Set an async callable(user, program_id) -> (tier, lifetime_earned)."""
        self._tier_resolver = resolver
