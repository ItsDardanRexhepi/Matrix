"""
SelectiveDisclosure — privacy-preserving credential presentation.

Builds a presentation that reveals the VALUES of a chosen subset of claim
fields. What it does not hide, which this used to leave out: the NAMES of the
undisclosed fields (each appears with a salted commitment, and in the
disclosure metadata), and the credential's id. The salts are discarded, so a
commitment can never be opened.

Verification is against this service's own record: a presentation it made and
still holds, presented unchanged. A presentation made anywhere else does not
verify here — it used to, on a structural check alone — and the derived
credentials carry no issuer proof, so nothing outside this process can check
that a disclosed value is the one the issuer wrote. The proof is a digest, not
a signature (``PROOF_TYPE``).
"""

import hashlib
import logging
import time
import uuid
from typing import Any

from .credential_vault import PROOF_TYPE

logger = logging.getLogger(__name__)

VP_CONTEXT = "https://www.w3.org/ns/credentials/v2"


class SelectiveDisclosure:
    """Creates and verifies selective-disclosure presentations.

    Parameters
    ----------
    config : dict
        Platform configuration.  Reads ``did.disclosure`` sub-key:

        - ``max_credentials_per_presentation`` (int, default 10)
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        disc_cfg = config.get("did", {}).get("disclosure", {})
        self._max_creds: int = disc_cfg.get("max_credentials_per_presentation", 10)

        # presentation_id -> presentation
        self._presentations: dict[str, dict[str, Any]] = {}
        # credential_id -> full credential (populated externally by DIDService)
        self._credential_store: dict[str, dict[str, Any]] = {}

    def register_credential(self, credential: dict) -> None:
        """Register a full credential so it can be used in presentations."""
        cred_id = credential.get("id")
        if cred_id:
            self._credential_store[cred_id] = credential

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_presentation(
        self,
        holder_did: str,
        credential_ids: list,
        disclosed_fields: dict,
    ) -> dict:
        """Create a Verifiable Presentation with selective disclosure.

        Parameters
        ----------
        holder_did : str
            DID of the credential holder creating the presentation.
        credential_ids : list[str]
            IDs of credentials to include.
        disclosed_fields : dict
            Mapping of credential_id -> list of field names to disclose
            from ``credentialSubject``.  Fields not listed are hashed
            (their value is replaced by a commitment hash).

        Returns
        -------
        dict
            A presentation shaped after the W3C data model, with the chosen
            fields' values disclosed (see the module docstring for what is
            not hidden and what the proof is).
        """
        if not holder_did:
            raise ValueError("holder_did is required")
        if not credential_ids:
            raise ValueError("At least one credential_id is required")
        if len(credential_ids) > self._max_creds:
            raise ValueError(
                f"Too many credentials ({len(credential_ids)}), "
                f"max is {self._max_creds}"
            )

        derived_credentials: list[dict] = []
        commitment_proofs: list[dict] = []

        for cred_id in credential_ids:
            cred = self._credential_store.get(cred_id)
            if cred is None:
                raise KeyError(f"Credential {cred_id} not found in store")

            subject = cred.get("credentialSubject", {})
            allowed_fields = set(disclosed_fields.get(cred_id, []))

            # Build derived subject: disclose selected fields, hash the rest
            derived_subject: dict[str, Any] = {"id": subject.get("id", holder_did)}
            field_commitments: dict[str, str] = {}

            for key, value in subject.items():
                if key == "id":
                    continue
                if key in allowed_fields:
                    derived_subject[key] = value
                else:
                    # Create a blinded commitment
                    salt = hashlib.sha256(
                        f"{cred_id}:{key}:{uuid.uuid4().hex}".encode()
                    ).hexdigest()[:16]
                    commitment = hashlib.sha256(
                        f"{salt}:{key}:{value}".encode()
                    ).hexdigest()
                    field_commitments[key] = commitment

            derived_cred = {
                "@context": cred.get("@context", [VP_CONTEXT]),
                "id": cred_id,
                "type": cred.get("type", ["VerifiableCredential"]),
                "issuer": cred.get("issuer"),
                "issuanceDate": cred.get("issuanceDate"),
                "credentialSubject": derived_subject,
            }
            if field_commitments:
                derived_cred["_undisclosedCommitments"] = field_commitments

            derived_credentials.append(derived_cred)
            commitment_proofs.append({
                "credential_id": cred_id,
                "disclosed_fields": sorted(allowed_fields),
                "committed_fields": sorted(field_commitments.keys()),
            })

        presentation_id = f"urn:uuid:{uuid.uuid4()}"
        now = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

        proof_value = hashlib.sha256(
            f"{presentation_id}:{holder_did}:{now}".encode()
        ).hexdigest()

        presentation = {
            "@context": [VP_CONTEXT],
            "id": presentation_id,
            "type": ["VerifiablePresentation"],
            "holder": holder_did,
            "verifiableCredential": derived_credentials,
            "proof": {
                "type": PROOF_TYPE,
                "created": now_iso,
                "verificationMethod": f"{holder_did}#key-0",
                "proofPurpose": "authentication",
                "proofValue": proof_value,
            },
            "_disclosureMetadata": {
                "commitment_proofs": commitment_proofs,
                "created_at": now,
            },
        }

        self._presentations[presentation_id] = presentation

        logger.info(
            "Presentation created: %s by %s with %d credential(s)",
            presentation_id, holder_did, len(derived_credentials),
        )
        return presentation

    async def verify_presentation(self, presentation: dict) -> dict:
        """Verify a presentation against the one this service made.

        Checks structural validity and the holder reference, and that the
        presentation is one this service created and still holds, presented
        unchanged. A presentation from anywhere else does not verify: its proof
        is a digest only its maker can check.
        """
        errors: list[str] = []

        pres_id = presentation.get("id")
        if not pres_id:
            errors.append("Missing presentation 'id'")

        pres_types = presentation.get("type", [])
        if "VerifiablePresentation" not in pres_types:
            errors.append("Must include 'VerifiablePresentation' in type")

        holder = presentation.get("holder")
        if not holder:
            errors.append("Missing 'holder'")

        credentials = presentation.get("verifiableCredential", [])
        if not credentials:
            errors.append("No credentials in presentation")

        proof = presentation.get("proof", {})
        if not proof.get("proofValue"):
            errors.append("Missing proof.proofValue")

        # Verify against the stored presentation. An external one used to be
        # proof_valid on a structural check alone, with no error, so it came
        # back valid; and a stored one was compared on its proof value only,
        # so its disclosed values could be changed without failing.
        proof_valid = False
        if pres_id:
            stored = self._presentations.get(pres_id)
            if stored is None:
                errors.append(
                    "Presentation was not created by this service; its proof "
                    "is a digest only its maker can check")
            elif stored["proof"]["proofValue"] != proof.get("proofValue"):
                errors.append("Proof value does not match")
            elif stored != presentation:
                errors.append(
                    "Presentation content differs from the one this service "
                    "created")
            else:
                proof_valid = True

        # Check each credential has a valid subject
        for i, cred in enumerate(credentials):
            subj = cred.get("credentialSubject", {})
            if not subj.get("id"):
                errors.append(f"Credential [{i}] missing credentialSubject.id")

        is_valid = len(errors) == 0

        # Collect disclosure summary
        disclosure_meta = presentation.get("_disclosureMetadata", {})
        commitment_proofs = disclosure_meta.get("commitment_proofs", [])
        disclosed_summary = []
        for cp in commitment_proofs:
            disclosed_summary.append({
                "credential_id": cp.get("credential_id"),
                "disclosed": cp.get("disclosed_fields", []),
                "hidden": cp.get("committed_fields", []),
            })

        result = {
            "presentation_id": pres_id,
            "valid": is_valid,
            "holder": holder,
            "credential_count": len(credentials),
            "proof_valid": proof_valid,
            "disclosure_summary": disclosed_summary,
            "errors": errors,
            "verified_at": time.time(),
        }
        logger.info(
            "Presentation verified: %s — valid=%s", pres_id, is_valid,
        )
        return result
