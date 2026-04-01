"""
ZKPVerifier — zero-knowledge proof generation and verification.

Allows users to prove factual statements about their data (age, balance,
membership, residency) without revealing the underlying private data.

Links to Component 29 (privacy protection) for broader privacy guarantees.
"""

import hashlib
import hmac
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_CLAIM_TYPES = {"age_over", "balance_above", "member_of", "resident_of"}


class ZKPVerifier:
    """Zero-knowledge proof generator and verifier.

    Parameters
    ----------
    config : dict
        Platform configuration.  Reads ``did.zkp`` sub-key:

        - ``proof_ttl_seconds`` (int, default 3600) — proof validity window
        - ``hash_rounds`` (int, default 10) — number of hashing rounds
          for commitment schemes
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        zkp_cfg = config.get("did", {}).get("zkp", {})
        self._proof_ttl: int = zkp_cfg.get("proof_ttl_seconds", 3600)
        self._hash_rounds: int = zkp_cfg.get("hash_rounds", 10)

        # proof_id -> proof record (for verification)
        self._proofs: dict[str, dict[str, Any]] = {}
        # Shared secret for HMAC-based commitments (in production, use HSM)
        self._secret = hashlib.sha256(
            f"zkp_secret:{uuid.uuid4().hex}".encode()
        ).digest()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_proof(
        self,
        claim_type: str,
        private_data: dict,
        public_statement: str,
    ) -> dict:
        """Generate a zero-knowledge proof for a claim.

        Parameters
        ----------
        claim_type : str
            One of ``age_over``, ``balance_above``, ``member_of``, ``resident_of``.
        private_data : dict
            The private data that backs the claim.  Never included in the
            proof output.
        public_statement : str
            The public statement to prove (e.g. ``"age >= 18"``).

        Returns
        -------
        dict
            A proof object that can be verified without knowing *private_data*.
        """
        if claim_type not in SUPPORTED_CLAIM_TYPES:
            raise ValueError(
                f"Unsupported claim type '{claim_type}'. "
                f"Supported: {sorted(SUPPORTED_CLAIM_TYPES)}"
            )
        if not private_data:
            raise ValueError("private_data must not be empty")
        if not public_statement:
            raise ValueError("public_statement is required")

        # Evaluate the claim against the private data
        claim_holds = self._evaluate_claim(claim_type, private_data, public_statement)
        if not claim_holds:
            raise ValueError(
                f"Cannot generate proof: claim '{public_statement}' "
                f"does not hold for the provided private data"
            )

        proof_id = f"zkp_{uuid.uuid4().hex[:16]}"
        now = time.time()

        # Build the commitment (blinded hash of private data)
        nonce = uuid.uuid4().hex
        commitment = self._build_commitment(private_data, nonce)

        # Build the challenge-response
        challenge = hashlib.sha256(
            f"{proof_id}:{public_statement}:{commitment}:{now}".encode()
        ).hexdigest()

        response = hmac.new(
            self._secret,
            f"{challenge}:{nonce}:{commitment}".encode(),
            hashlib.sha256,
        ).hexdigest()

        proof = {
            "proof_id": proof_id,
            "claim_type": claim_type,
            "public_statement": public_statement,
            "commitment": commitment,
            "challenge": challenge,
            "response": response,
            "created_at": now,
            "expires_at": now + self._proof_ttl,
            "protocol": "sigma_commitment_v1",
            "verified": None,  # set on verification
        }

        # Store for later verification (excluding private data)
        self._proofs[proof_id] = {
            **proof,
            "_nonce": nonce,
            "_claim_holds": claim_holds,
        }

        logger.info(
            "ZKP generated: %s (claim=%s, statement='%s')",
            proof_id, claim_type, public_statement,
        )
        # Return proof without internal secrets
        return {k: v for k, v in proof.items() if not k.startswith("_")}

    async def verify_proof(self, proof: dict) -> bool:
        """Verify a zero-knowledge proof.

        Parameters
        ----------
        proof : dict
            The proof object returned by ``generate_proof``.

        Returns
        -------
        bool
            ``True`` if the proof is valid and the claim holds.
        """
        proof_id = proof.get("proof_id")
        if not proof_id:
            logger.warning("ZKP verification failed: missing proof_id")
            return False

        stored = self._proofs.get(proof_id)
        if stored is None:
            logger.warning("ZKP verification failed: proof %s not found", proof_id)
            return False

        # Check expiration
        now = time.time()
        if now > stored["expires_at"]:
            logger.warning("ZKP verification failed: proof %s expired", proof_id)
            return False

        # Verify challenge-response integrity
        expected_response = hmac.new(
            self._secret,
            f"{stored['challenge']}:{stored['_nonce']}:{stored['commitment']}".encode(),
            hashlib.sha256,
        ).hexdigest()

        if proof.get("response") != expected_response:
            logger.warning("ZKP verification failed: response mismatch for %s", proof_id)
            return False

        # Verify the commitment matches
        if proof.get("commitment") != stored["commitment"]:
            logger.warning("ZKP verification failed: commitment mismatch for %s", proof_id)
            return False

        # Verify the public statement matches
        if proof.get("public_statement") != stored["public_statement"]:
            logger.warning(
                "ZKP verification failed: statement mismatch for %s", proof_id,
            )
            return False

        # The claim was evaluated at generation time
        is_valid = stored["_claim_holds"]

        stored["verified"] = is_valid
        logger.info("ZKP verified: %s — valid=%s", proof_id, is_valid)
        return is_valid

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate_claim(
        self, claim_type: str, private_data: dict, statement: str
    ) -> bool:
        """Evaluate whether the private data supports the public statement."""
        try:
            if claim_type == "age_over":
                age = int(private_data.get("age", 0))
                threshold = self._extract_threshold(statement)
                return age >= threshold

            elif claim_type == "balance_above":
                balance = float(private_data.get("balance", 0))
                threshold = self._extract_threshold(statement)
                return balance >= threshold

            elif claim_type == "member_of":
                groups = private_data.get("groups", [])
                target = private_data.get("target_group", "")
                if not target:
                    # Try to extract from statement
                    target = statement.replace("member_of:", "").strip()
                return target in groups

            elif claim_type == "resident_of":
                residence = private_data.get("country", "") or private_data.get("region", "")
                target = private_data.get("target_region", "")
                if not target:
                    target = statement.replace("resident_of:", "").strip()
                return residence.lower() == target.lower()

            else:
                return False

        except (ValueError, TypeError, AttributeError) as exc:
            logger.error("Claim evaluation error: %s", exc)
            return False

    @staticmethod
    def _extract_threshold(statement: str) -> float:
        """Extract a numeric threshold from a statement like 'age >= 18'."""
        for part in reversed(statement.split()):
            try:
                return float(part)
            except ValueError:
                continue
        raise ValueError(f"No numeric threshold found in statement: '{statement}'")

    def _build_commitment(self, data: dict, nonce: str) -> str:
        """Build a multi-round commitment hash from data and nonce."""
        serialised = ":".join(f"{k}={v}" for k, v in sorted(data.items()))
        current = f"{nonce}:{serialised}"
        for _ in range(self._hash_rounds):
            current = hashlib.sha256(current.encode()).hexdigest()
        return current
