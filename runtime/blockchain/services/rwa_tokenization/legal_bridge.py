"""
LegalBridge — connects on-chain RWA tokens to off-chain legal entities.

Supports creating legal wrappers (SPVs / LLCs), verifying legal standing,
and attaching notarised or certified document hashes to token records.
"""

import hashlib
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_JURISDICTIONS = {
    "US-DE", "US-WY", "US-NV", "US-CA", "US-NY",
    "UK", "CH", "SG", "AE-DIFC", "KY", "BVI", "LI",
    "EU-LU", "EU-IE", "EU-MT",
}

LEGAL_ENTITY_TYPES = {"llc", "spv", "trust", "foundation", "cooperative"}

DOCUMENT_TYPES = {
    "title_deed", "appraisal", "insurance", "inspection",
    "legal_opinion", "regulatory_approval", "certificate_of_incorporation",
    "operating_agreement", "valuation_report", "audit_report", "other",
}


class LegalBridge:
    """Bridge between on-chain tokens and off-chain legal structures.

    Parameters
    ----------
    config : dict
        Platform configuration.  Reads ``rwa.legal`` sub-key for defaults.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        legal_cfg = config.get("rwa", {}).get("legal", {})
        self._default_jurisdiction: str = legal_cfg.get("default_jurisdiction", "US-DE")
        # token_id -> legal wrapper
        self._wrappers: dict[str, dict[str, Any]] = {}
        # token_id -> list of attached documents
        self._documents: dict[str, list[dict]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_legal_wrapper(
        self, token_id: str, jurisdiction: str, legal_entity: dict
    ) -> dict:
        """Create an off-chain legal wrapper linked to *token_id*.

        Parameters
        ----------
        token_id : str
            The RWA token to wrap.
        jurisdiction : str
            Jurisdiction code (e.g. ``"US-DE"``).
        legal_entity : dict
            Must include ``name`` (str) and ``entity_type`` (str).
            Optional: ``registration_number``, ``registered_agent``, ``formation_date``.
        """
        if jurisdiction not in SUPPORTED_JURISDICTIONS:
            raise ValueError(
                f"Unsupported jurisdiction '{jurisdiction}'. "
                f"Supported: {sorted(SUPPORTED_JURISDICTIONS)}"
            )

        entity_type = legal_entity.get("entity_type", "").lower()
        if entity_type not in LEGAL_ENTITY_TYPES:
            raise ValueError(
                f"Unsupported entity type '{entity_type}'. "
                f"Supported: {sorted(LEGAL_ENTITY_TYPES)}"
            )

        name = legal_entity.get("name")
        if not name:
            raise ValueError("Legal entity must have a 'name'")

        if token_id in self._wrappers:
            raise ValueError(f"Legal wrapper already exists for token {token_id}")

        wrapper_id = f"legal_{uuid.uuid4().hex[:12]}"
        now = time.time()

        wrapper = {
            "wrapper_id": wrapper_id,
            "token_id": token_id,
            "jurisdiction": jurisdiction,
            "entity_type": entity_type,
            "entity_name": name,
            "registration_number": legal_entity.get("registration_number"),
            "registered_agent": legal_entity.get("registered_agent"),
            "formation_date": legal_entity.get("formation_date"),
            "status": "pending_verification",
            "created_at": now,
            "updated_at": now,
            "verification_hash": hashlib.sha256(
                f"{wrapper_id}:{token_id}:{jurisdiction}:{name}".encode()
            ).hexdigest(),
        }
        self._wrappers[token_id] = wrapper
        self._documents.setdefault(token_id, [])

        logger.info(
            "Legal wrapper %s created for token %s in %s (%s: %s)",
            wrapper_id, token_id, jurisdiction, entity_type, name,
        )
        return wrapper

    async def verify_legal_status(self, token_id: str) -> dict:
        """Verify the legal standing of the wrapper associated with *token_id*.

        In production this would call a legal-verification oracle or API;
        here we perform structural checks and return the current status.
        """
        wrapper = self._wrappers.get(token_id)
        if wrapper is None:
            raise KeyError(f"No legal wrapper for token {token_id}")

        docs = self._documents.get(token_id, [])
        has_incorporation = any(
            d["doc_type"] == "certificate_of_incorporation" for d in docs
        )
        has_legal_opinion = any(d["doc_type"] == "legal_opinion" for d in docs)

        checks = {
            "wrapper_exists": True,
            "has_incorporation_doc": has_incorporation,
            "has_legal_opinion": has_legal_opinion,
            "entity_name_present": bool(wrapper.get("entity_name")),
            "jurisdiction_valid": wrapper["jurisdiction"] in SUPPORTED_JURISDICTIONS,
        }
        all_passed = all(checks.values())

        if all_passed and wrapper["status"] == "pending_verification":
            wrapper["status"] = "verified"
            wrapper["updated_at"] = time.time()

        result = {
            "token_id": token_id,
            "wrapper_id": wrapper["wrapper_id"],
            "status": wrapper["status"],
            "checks": checks,
            "all_passed": all_passed,
            "verified_at": time.time() if all_passed else None,
        }
        logger.info(
            "Legal verification for token %s: status=%s, all_passed=%s",
            token_id, wrapper["status"], all_passed,
        )
        return result

    async def attach_document(
        self, token_id: str, doc_hash: str, doc_type: str
    ) -> dict:
        """Attach a document hash to the legal wrapper for *token_id*.

        Parameters
        ----------
        token_id : str
            The RWA token.
        doc_hash : str
            SHA-256 hash of the document contents.
        doc_type : str
            One of the supported document types.
        """
        if token_id not in self._wrappers:
            raise KeyError(f"No legal wrapper for token {token_id}")

        if doc_type not in DOCUMENT_TYPES:
            raise ValueError(
                f"Unsupported document type '{doc_type}'. "
                f"Supported: {sorted(DOCUMENT_TYPES)}"
            )

        if not doc_hash or len(doc_hash) < 16:
            raise ValueError("doc_hash must be a non-empty hash string (>= 16 chars)")

        # Prevent duplicate attachment of the same hash
        existing = self._documents.get(token_id, [])
        for d in existing:
            if d["doc_hash"] == doc_hash:
                raise ValueError(f"Document with hash {doc_hash[:16]}... already attached")

        doc_record = {
            "document_id": f"doc_{uuid.uuid4().hex[:12]}",
            "token_id": token_id,
            "doc_hash": doc_hash,
            "doc_type": doc_type,
            "attached_at": time.time(),
            "anchor_hash": hashlib.sha256(
                f"{token_id}:{doc_hash}:{doc_type}".encode()
            ).hexdigest(),
        }
        self._documents.setdefault(token_id, []).append(doc_record)

        wrapper = self._wrappers[token_id]
        wrapper["updated_at"] = time.time()

        logger.info(
            "Document (%s) attached to token %s: %s",
            doc_type, token_id, doc_record["document_id"],
        )
        return doc_record
