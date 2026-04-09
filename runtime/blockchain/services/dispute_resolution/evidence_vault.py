from __future__ import annotations

"""
EvidenceVault — immutable evidence storage with hash verification.

Evidence is serialised, hashed (SHA-256) and stored so that neither
party can tamper with submitted materials after the fact. The hash
acts as an IPFS-style content identifier.
"""

import hashlib
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class EvidenceVault:
    """Immutable evidence store backed by content-addressed hashing."""

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}
        # In production this would be IPFS / Arweave; here we use an
        # in-memory map keyed by content hash.
        self._store: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def store(self, dispute_id: str, evidence: dict) -> dict:
        """Persist evidence and return its content hash.

        Args:
            dispute_id: The dispute this evidence belongs to.
            evidence: Arbitrary evidence payload (must be JSON-serialisable).

        Returns:
            Dict with ``evidence_hash``, ``dispute_id`` and ``stored_at``.
        """
        canonical = json.dumps(evidence, sort_keys=True, default=str)
        evidence_hash = hashlib.sha256(canonical.encode()).hexdigest()

        entry = {
            "dispute_id": dispute_id,
            "evidence": evidence,
            "evidence_hash": evidence_hash,
            "stored_at": time.time(),
            "canonical_bytes": len(canonical.encode()),
        }
        self._store[evidence_hash] = entry
        logger.info("Evidence stored — hash=%s dispute=%s", evidence_hash, dispute_id)

        return {
            "evidence_hash": evidence_hash,
            "dispute_id": dispute_id,
            "stored_at": entry["stored_at"],
        }

    async def retrieve(self, evidence_hash: str) -> dict:
        """Retrieve evidence by its content hash.

        Raises:
            KeyError: If the hash is not found in the vault.
        """
        if evidence_hash not in self._store:
            raise KeyError(f"Evidence not found: {evidence_hash}")

        entry = self._store[evidence_hash]
        logger.debug("Evidence retrieved — hash=%s", evidence_hash)
        return {
            "evidence_hash": evidence_hash,
            "dispute_id": entry["dispute_id"],
            "evidence": entry["evidence"],
            "stored_at": entry["stored_at"],
        }

    async def verify_integrity(self, evidence_hash: str) -> bool:
        """Re-hash stored evidence and confirm it matches the key.

        Returns ``True`` when the stored content still matches its hash,
        ``False`` if it has been corrupted, and raises ``KeyError`` if
        the hash is not in the vault at all.
        """
        if evidence_hash not in self._store:
            raise KeyError(f"Evidence not found: {evidence_hash}")

        entry = self._store[evidence_hash]
        canonical = json.dumps(entry["evidence"], sort_keys=True, default=str)
        computed = hashlib.sha256(canonical.encode()).hexdigest()
        is_valid = computed == evidence_hash

        if not is_valid:
            logger.error(
                "Evidence integrity check FAILED — expected=%s got=%s",
                evidence_hash,
                computed,
            )

        return is_valid
