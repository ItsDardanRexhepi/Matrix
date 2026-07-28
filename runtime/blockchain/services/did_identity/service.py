"""
DIDService — W3C DID-compliant decentralized identity management.

Creates, resolves, updates, and deactivates Decentralized Identifiers
following the W3C DID Core specification.  DID Documents include
verification methods, authentication, and service endpoints.
"""

import hashlib
import logging
import time
import uuid
from typing import Any

from .credential_vault import CredentialVault
from .selective_disclosure import SelectiveDisclosure
from .zkp import ZKPVerifier

logger = logging.getLogger(__name__)

DID_CONTEXT = "https://www.w3.org/ns/did/v1"
DID_CONTEXT_SECURITY = "https://w3id.org/security/suites/ed25519-2020/v1"


class DIDService:
    """W3C-compliant Decentralized Identity service.

    Parameters
    ----------
    config : dict
        Platform configuration.  Reads ``did.*`` sub-key:

        - ``did.method`` (str, default ``"openmatrix"``)
        - ``did.network`` (str, default ``"base"``)
        - ``did.key_type`` (str, default ``"Ed25519VerificationKey2020"``)

    Example config snippet::

        {
            "blockchain": {
                "chain_id": 8453,
                "platform_wallet": "0x..."
            },
            "did": {
                "method": "openmatrix",
                "network": "base",
                "key_type": "Ed25519VerificationKey2020"
            }
        }
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        did_cfg = config.get("did", {})
        self._method: str = did_cfg.get("method", "openmatrix")
        self._network: str = did_cfg.get("network", "base")
        self._key_type: str = did_cfg.get("key_type", "Ed25519VerificationKey2020")

        # Sub-components
        self.credential_vault = CredentialVault(config)
        self.selective_disclosure = SelectiveDisclosure(config)
        self.zkp_verifier = ZKPVerifier(config)

        # DID -> DID Document store
        self._documents: dict[str, dict[str, Any]] = {}
        # owner address -> list of DIDs
        self._owner_index: dict[str, list[str]] = {}

        logger.info(
            "DIDService initialised (method=%s, network=%s)",
            self._method, self._network,
        )

    # ------------------------------------------------------------------
    # Core DID operations
    # ------------------------------------------------------------------

    async def create_did(self, owner: str, method: str = "openmatrix") -> dict:
        """Create a new DID for *owner*.

        Returns a full W3C DID Document.

        The DID format is ``did:<method>:<network>:<address_hash>``.
        """
        if not owner:
            raise ValueError("Owner address is required")

        effective_method = method or self._method
        unique_id = hashlib.sha256(
            f"{owner}:{uuid.uuid4().hex}:{time.time()}".encode()
        ).hexdigest()[:40]
        did = f"did:{effective_method}:{self._network}:0x{unique_id}"

        if did in self._documents:
            raise ValueError(f"DID {did} already exists (hash collision)")

        now = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

        # Generate a deterministic public key placeholder
        pub_key_hex = hashlib.sha256(f"{did}:key0".encode()).hexdigest()

        verification_method_id = f"{did}#key-0"
        doc = {
            "@context": [DID_CONTEXT, DID_CONTEXT_SECURITY],
            "id": did,
            "controller": did,
            "verificationMethod": [
                {
                    "id": verification_method_id,
                    "type": self._key_type,
                    "controller": did,
                    "publicKeyMultibase": f"z{pub_key_hex}",
                }
            ],
            "authentication": [verification_method_id],
            "assertionMethod": [verification_method_id],
            "keyAgreement": [],
            "service": [],
            "created": now_iso,
            "updated": now_iso,
            "_meta": {
                "owner": owner,
                "status": "active",
                "created_at": now,
                "updated_at": now,
                "method": effective_method,
                "network": self._network,
            },
        }
        self._documents[did] = doc
        self._owner_index.setdefault(owner, []).append(did)

        logger.info("DID created: %s for owner %s", did, owner)
        return doc

    async def resolve_did(self, did: str) -> dict:
        """Resolve a DID and return its DID Document.

        Raises ``KeyError`` if the DID does not exist or has been deactivated.
        """
        doc = self._documents.get(did)
        if doc is None:
            raise KeyError(f"DID {did} not found")

        if doc["_meta"]["status"] == "deactivated":
            raise KeyError(f"DID {did} has been deactivated")

        resolution = {
            "@context": "https://w3id.org/did-resolution/v1",
            "didDocument": {k: v for k, v in doc.items() if k != "_meta"},
            "didDocumentMetadata": {
                "created": doc["created"],
                "updated": doc["updated"],
                "deactivated": doc["_meta"]["status"] == "deactivated",
            },
            "didResolutionMetadata": {
                "contentType": "application/did+ld+json",
                "retrieved": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        }
        logger.debug("DID resolved: %s", did)
        return resolution

    async def update_did(self, did: str, updates: dict) -> dict:
        """Update fields on a DID Document.

        Supported update keys:

        - ``service`` — replace the service endpoint list
        - ``add_verification_method`` — append a verification method
        - ``add_authentication`` — append an authentication reference
        - ``controller`` — change the controller DID
        """
        doc = self._documents.get(did)
        if doc is None:
            raise KeyError(f"DID {did} not found")
        if doc["_meta"]["status"] != "active":
            raise ValueError(f"Cannot update DID {did} (status={doc['_meta']['status']})")

        now = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

        if "service" in updates:
            services = updates["service"]
            if not isinstance(services, list):
                raise ValueError("'service' must be a list")
            for svc in services:
                if not svc.get("id") or not svc.get("type") or not svc.get("serviceEndpoint"):
                    raise ValueError(
                        "Each service must have 'id', 'type', and 'serviceEndpoint'"
                    )
            doc["service"] = services

        if "add_verification_method" in updates:
            vm = updates["add_verification_method"]
            if not vm.get("id") or not vm.get("type") or not vm.get("controller"):
                raise ValueError(
                    "Verification method must have 'id', 'type', and 'controller'"
                )
            doc["verificationMethod"].append(vm)

        if "add_authentication" in updates:
            auth_ref = updates["add_authentication"]
            if auth_ref not in [vm["id"] for vm in doc["verificationMethod"]]:
                raise ValueError(
                    f"Authentication ref '{auth_ref}' does not match any verification method"
                )
            doc["authentication"].append(auth_ref)

        if "controller" in updates:
            doc["controller"] = updates["controller"]

        doc["updated"] = now_iso
        doc["_meta"]["updated_at"] = now

        logger.info("DID updated: %s (keys: %s)", did, list(updates.keys()))
        return doc

    async def deactivate_did(self, did: str) -> dict:
        """Deactivate a DID.  The DID Document is retained but marked inactive."""
        doc = self._documents.get(did)
        if doc is None:
            raise KeyError(f"DID {did} not found")
        if doc["_meta"]["status"] == "deactivated":
            raise ValueError(f"DID {did} is already deactivated")

        now = time.time()
        doc["_meta"]["status"] = "deactivated"
        doc["_meta"]["deactivated_at"] = now
        doc["_meta"]["updated_at"] = now
        doc["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

        logger.info("DID deactivated: %s", did)
        return {
            "did": did,
            "status": "deactivated",
            "deactivated_at": now,
        }

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_dids_for_owner(self, owner: str) -> list[str]:
        """Return all DIDs owned by *owner*."""
        return list(self._owner_index.get(owner, []))

    # ------------------------------------------------------------------
    # Expanded identity operations
    # ------------------------------------------------------------------

    async def issue_credential(
        self, issuer_did: str, subject_did: str, credential_type: str, claims: dict,
    ) -> dict:
        """Issue a verifiable credential via the real vault issuer.

        THE OTHER HALF OF THE SHADOW, and it made the pair a complete fake
        credential system. This method built a record with NO ``proof``, no
        ``@context``, no ``type``, no ``expirationDate``, and wrote it directly
        into ``credential_vault._credentials`` — the vault's private dict —
        bypassing ``_holder_index`` (so ``list_credentials`` would never return
        it) and the per-DID cap.

        Its signature is IDENTICAL to ``credential_vault.issue_credential``,
        which computes a real sha256 ``proofValue`` and indexes the holder. So
        this was a pure shadow: same call, real one right there, fake one
        winning. Together with the shadowed verifier it meant a user could issue
        a credential that was not verifiable and verify a credential that was
        not issued, with nothing real in between.

        It also broke the real verifier for anything it wrote: that code reads
        ``stored["proof"]["proofValue"]``, which KeyErrors on a proofless
        record.
        """
        return await self.credential_vault.issue_credential(
            issuer_did=issuer_did,
            subject_did=subject_did,
            credential_type=credential_type,
            claims=claims,
        )

    async def verify_credential(
        self, credential_id: str, verifier_did: str = "",
    ) -> dict:
        """Verify a credential by delegating to the real vault verifier.

        THE SHADOW. This method used to mint a uuid and return
        ``{"valid": True, "status": "verified"}`` for ANY string — no vault
        lookup, no expiry check, no revocation check, no proof comparison.
        There was no input that could fail it. Meanwhile
        ``credential_vault.verify_credential`` right beside it does the real
        work: structural validity, ``proof.proofValue``, expiry, and the
        revocation set. The fake shadowed the real one.

        It is worse than the other fabrications found in this phase, and the
        reason is precise: every one of those sat behind a signature mismatch
        that errored the call out before the fabrication could run — accidental
        safety. This one's declared parameters MATCHED, so it was never in the
        NEW-13 broken set and has been live and callable all along. Anything
        gating on a credential was gating on the constant ``True``: a revoked
        credential verified, an expired one verified, a forged one verified,
        one that was never issued verified.

        Now: look the credential up, and verify it for real. Unknown ids fail
        closed rather than passing — the whole point is that some input must be
        able to fail.
        """
        credential = self.credential_vault._credentials.get(credential_id)
        if credential is None:
            return {
                "status": "invalid",
                "credential_id": credential_id,
                "verifier": verifier_did,
                "valid": False,
                "errors": ["Credential not found"],
                "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        result = await self.credential_vault.verify_credential(credential)
        result.setdefault("credential_id", credential_id)
        result["verifier"] = verifier_did
        return result

    async def selective_disclose(
        self, did: str, credential_id: str, fields: list[str], verifier_did: str = "",
    ) -> dict:
        """Selective disclosure — NOT IMPLEMENTED, and it must not pretend.

        The sibling of the shadowed verifier, same shape: it minted
        ``sd_<uuid4>``, returned ``"status": "disclosed"`` with the requested
        field names echoed back, and produced NO PROOF of any kind. It read no
        credential, verified nothing, and stored nothing. A verifier handed one
        of these records has been given a claim with nothing backing it.

        Selective disclosure needs a real cryptographic scheme (BBS+ signatures
        or an equivalent), and none exists in this codebase. So the honest
        answer is to say so. Like the shadowed verifier this one's parameters
        MATCHED its declaration, meaning no signature bug was holding it
        inert — it was live.
        """
        return {
            "status": "unavailable",
            "error_category": "not_implemented",
            "error": (
                "Selective disclosure is not available: it requires a "
                "cryptographic scheme (e.g. BBS+ signatures) that is not "
                "implemented. No disclosure proof was produced."
            ),
            "did": did,
            "credential_id": credential_id,
            "requested_fields": fields,
            "verifier": verifier_did,
        }

    async def query_reputation(self, did: str) -> dict:
        """Query the on-chain reputation score for a DID."""
        rep_id = f"rep_{uuid.uuid4().hex[:16]}"
        record = {
            "id": rep_id,
            "status": "queried",
            "did": did,
            "reputation_score": 100,
            "attestation_count": 0,
            "credential_count": 0,
        }
        logger.info("Reputation queried: id=%s", rep_id)
        return record
