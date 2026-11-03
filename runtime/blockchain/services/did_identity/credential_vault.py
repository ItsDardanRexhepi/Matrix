"""
CredentialVault — credential issuance, storage, and verification.

Issues credentials shaped after the W3C Verifiable Credentials Data Model,
stores them in an in-memory vault keyed by holder DID, and supports revocation
via a revocation set.

Not conformant with the Data Model v2.0, which this used to say it issued in.
The documents carry the v2 context with the v1.1 date names (issuanceDate,
expirationDate) and a status type no v2 status method registers, and their
proof is not a signature: it is a SHA-256 digest of public inputs, which the
vault records and is the only party able to check. The proof's type says
that (``PROOF_TYPE``); it used to name Ed25519Signature2020, a signature
suite, with no key anywhere to sign with.
"""

import hashlib
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

VC_CONTEXT = "https://www.w3.org/ns/credentials/v2"
VC_CONTEXT_EXAMPLES = "https://www.w3.org/ns/credentials/examples/v2"

CREDENTIAL_TYPES = {
    "VerifiableCredential",
    "KYCCredential",
    "EducationCredential",
    "EmploymentCredential",
    "MembershipCredential",
    "ResidencyCredential",
    "AgeCredential",
    "FinancialCredential",
    "HealthCredential",
    "LicenseCredential",
}

#: What a proof here is: a SHA-256 digest the vault records, checkable only by
#: comparing against that record. Not a signature suite's name, because
#: nothing signs.
PROOF_TYPE = "Sha256VaultDigest"


def _without_status(credential: dict) -> dict:
    return {k: v for k, v in credential.items() if k != "credentialStatus"}


class CredentialVault:
    """Manages Verifiable Credentials lifecycle.

    Parameters
    ----------
    config : dict
        Platform configuration.  Reads ``did.credentials`` sub-key:

        - ``max_credentials_per_did`` (int, default 1000)
        - ``default_expiry_days`` (int, default 365)
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        cred_cfg = config.get("did", {}).get("credentials", {})
        self._max_per_did: int = cred_cfg.get("max_credentials_per_did", 1000)
        self._default_expiry_days: int = cred_cfg.get("default_expiry_days", 365)

        # credential_id -> credential
        self._credentials: dict[str, dict[str, Any]] = {}
        # did -> list of credential_ids (holder index)
        self._holder_index: dict[str, list[str]] = {}
        # revoked credential IDs
        self._revoked: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def issue_credential(
        self,
        issuer_did: str,
        subject_did: str,
        credential_type: str,
        claims: dict,
    ) -> dict:
        """Issue a Verifiable Credential.

        Parameters
        ----------
        issuer_did : str
            DID of the credential issuer.
        subject_did : str
            DID of the credential subject (holder).
        credential_type : str
            A recognised credential type string.
        claims : dict
            Claim key-value pairs to include in ``credentialSubject``.

        Returns
        -------
        dict
            A credential document shaped after the W3C VC data model, whose
            proof is a digest this vault records (see the module docstring).
        """
        if not issuer_did or not subject_did:
            raise ValueError("Both issuer_did and subject_did are required")
        if not claims:
            raise ValueError("Claims must not be empty")

        # Allow custom types but validate known ones aren't misspelt
        effective_types = ["VerifiableCredential"]
        if credential_type != "VerifiableCredential":
            effective_types.append(credential_type)

        existing = self._holder_index.get(subject_did, [])
        if len(existing) >= self._max_per_did:
            raise ValueError(
                f"Credential limit ({self._max_per_did}) reached for {subject_did}"
            )

        credential_id = f"urn:uuid:{uuid.uuid4()}"
        now = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        expiry = now + self._default_expiry_days * 86_400
        expiry_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expiry))

        # Build proof
        proof_value = hashlib.sha256(
            f"{credential_id}:{issuer_did}:{subject_did}:{now}".encode()
        ).hexdigest()

        credential = {
            "@context": [VC_CONTEXT, VC_CONTEXT_EXAMPLES],
            "id": credential_id,
            "type": effective_types,
            "issuer": issuer_did,
            "issuanceDate": now_iso,
            "expirationDate": expiry_iso,
            "credentialSubject": {
                "id": subject_did,
                **claims,
            },
            "credentialStatus": {
                "id": f"{credential_id}#status",
                "type": "RevocationList2023",
                "revoked": False,
            },
            "proof": {
                "type": PROOF_TYPE,
                "created": now_iso,
                "verificationMethod": f"{issuer_did}#key-0",
                "proofPurpose": "assertionMethod",
                "proofValue": proof_value,
            },
        }

        self._credentials[credential_id] = credential
        self._holder_index.setdefault(subject_did, []).append(credential_id)

        logger.info(
            "Credential issued: %s (type=%s, issuer=%s, subject=%s)",
            credential_id, credential_type, issuer_did, subject_did,
        )
        return credential

    async def verify_credential(self, credential: dict) -> dict:
        """Verify a credential against the one this vault issued.

        Checks structural validity, expiration and revocation status, and that
        the document presented is the one this vault issued: same proof, same
        content. The proof is a digest only this vault can check, so a
        credential this vault did not issue does not verify here. It used to
        pass ("assume valid if we can't disprove"), and the proof check
        compared the proof value alone, so a stored credential presented with
        its claims changed passed too.
        """
        errors: list[str] = []

        cred_id = credential.get("id")
        if not cred_id:
            errors.append("Missing credential 'id'")

        if "@context" not in credential:
            errors.append("Missing '@context'")

        cred_types = credential.get("type", [])
        if "VerifiableCredential" not in cred_types:
            errors.append("Must include 'VerifiableCredential' in type")

        issuer = credential.get("issuer")
        if not issuer:
            errors.append("Missing 'issuer'")

        subject = credential.get("credentialSubject", {})
        if not subject.get("id"):
            errors.append("Missing credentialSubject.id")

        proof = credential.get("proof", {})
        if not proof.get("proofValue"):
            errors.append("Missing proof.proofValue")

        # Check expiration
        expiry_str = credential.get("expirationDate")
        expired = False
        if expiry_str:
            try:
                expiry_ts = time.mktime(time.strptime(expiry_str, "%Y-%m-%dT%H:%M:%SZ"))
                if time.time() > expiry_ts:
                    expired = True
                    errors.append("Credential has expired")
            except ValueError:
                errors.append(f"Invalid expirationDate format: {expiry_str}")

        # Check revocation
        revoked = False
        if cred_id and cred_id in self._revoked:
            revoked = True
            errors.append("Credential has been revoked")

        # Verify proof integrity: the only record that can vouch for this
        # proof is the vault's own, so the presented document must be the
        # stored one. credentialStatus is left out of the comparison because
        # revocation is decided from the revocation set above.
        proof_valid = False
        if cred_id and issuer and subject.get("id") and proof.get("proofValue"):
            stored = self._credentials.get(cred_id)
            if stored is None:
                errors.append(
                    "Credential was not issued by this vault; its proof is a "
                    "digest only the issuing vault can check")
            elif stored["proof"]["proofValue"] != proof["proofValue"]:
                errors.append("Proof value does not match")
            elif _without_status(stored) != _without_status(credential):
                errors.append(
                    "Credential content differs from the credential this "
                    "vault issued")
            else:
                proof_valid = True

        is_valid = len(errors) == 0

        result = {
            "credential_id": cred_id,
            "valid": is_valid,
            "expired": expired,
            "revoked": revoked,
            "proof_valid": proof_valid,
            "errors": errors,
            "verified_at": time.time(),
        }
        logger.info(
            "Credential verified: %s — valid=%s, errors=%d",
            cred_id, is_valid, len(errors),
        )
        return result

    async def revoke_credential(self, credential_id: str) -> dict:
        """Revoke a previously issued credential."""
        if credential_id not in self._credentials:
            raise KeyError(f"Credential {credential_id} not found")
        if credential_id in self._revoked:
            raise ValueError(f"Credential {credential_id} is already revoked")

        self._revoked.add(credential_id)
        cred = self._credentials[credential_id]
        cred["credentialStatus"]["revoked"] = True

        logger.info("Credential revoked: %s", credential_id)
        return {
            "credential_id": credential_id,
            "revoked": True,
            "revoked_at": time.time(),
        }

    async def list_credentials(self, did: str) -> list:
        """Return all credentials held by *did*."""
        cred_ids = self._holder_index.get(did, [])
        result = []
        for cid in cred_ids:
            cred = self._credentials.get(cid)
            if cred is not None:
                result.append(cred)
        return result
