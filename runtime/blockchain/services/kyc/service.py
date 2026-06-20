"""
KYC/AML via Sumsub, Persona, or self-sovereign credentials.

This service wires three operations to real protocol integrations:

- ``start_kyc``          → Sumsub applicant creation (off-chain REST API,
                          HMAC-signed with cfg.api_key + cfg.secret_key).
- ``check_aml_risk``     → Sumsub applicant review/AML status lookup
                          (off-chain REST API, same HMAC credentials).
- ``issue_kyc_credential`` → On-chain W3C-style verifiable credential issued
                          as an Ethereum Attestation Service (EAS) attestation,
                          gas paid by the platform paymaster (non-custodial).

PII HANDLING: this service NEVER stores raw PII. Identity documents and
personal data are passed straight through to the KYC provider (Sumsub /
Persona) and only opaque references (applicant_id, review status, an
attestation UID / KYC level) are returned or written on-chain.

NON-CUSTODIAL: the only key this service ever signs with is the platform
paymaster account (via ``Web3Manager.send_transaction``) for the
platform-level EAS attestation in ``issue_kyc_credential``. It never signs,
holds, or moves a user's wallet funds.

Each method gates on its specific missing credential first (returning the
canonical CREDENTIAL-GATED ``not_deployed_response``), then performs the
real protocol call when configured. Heavy imports (httpx, web3) are lazy so
module import / test collection never hard-depends on them.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any

from runtime.blockchain.web3_manager import (
    Web3Manager,
    is_placeholder_value,
    not_deployed_response,
)

logger = logging.getLogger(__name__)

# Sumsub production REST base URL (documented; UNVERIFIED without an app token).
# https://docs.sumsub.com/reference/about-sumsub-api
_SUMSUB_BASE_URL = "https://api.sumsub.com"

# Persona REST base URL (documented; used only if provider == "persona").
# https://docs.withpersona.com/reference
_PERSONA_BASE_URL = "https://withpersona.com/api/v1"

# Minimal EAS attest ABI — only the single function we invoke for the
# on-chain KYC verifiable-credential attestation. (Mirrors eas_client.py.)
_EAS_ATTEST_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "schema", "type": "bytes32"},
                    {
                        "components": [
                            {"name": "recipient", "type": "address"},
                            {"name": "expirationTime", "type": "uint64"},
                            {"name": "revocable", "type": "bool"},
                            {"name": "refUID", "type": "bytes32"},
                            {"name": "data", "type": "bytes"},
                            {"name": "value", "type": "uint256"},
                        ],
                        "name": "data",
                        "type": "tuple",
                    },
                ],
                "name": "request",
                "type": "tuple",
            }
        ],
        "name": "attest",
        "outputs": [{"name": "", "type": "bytes32"}],
        "stateMutability": "payable",
        "type": "function",
    }
]


class KYCService:
    """KYC/AML via Sumsub, Persona, or self-sovereign credentials."""

    service_name = "kyc"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    # ── Config / provider helpers ────────────────────────────────────

    def _cfg(self) -> dict:
        """Return this service's own config sub-dict."""
        return self._config.get("services", {}).get(self.service_name, {})

    def _provider(self) -> str:
        """Return the configured KYC provider name (default: sumsub)."""
        return str(self._cfg().get("provider", "sumsub")).strip().lower()

    def _base_url(self) -> str:
        """Return the REST base URL for the configured provider."""
        cfg = self._cfg()
        explicit = cfg.get("endpoint") or cfg.get("base_url")
        if not is_placeholder_value(explicit):
            return str(explicit).rstrip("/")
        if self._provider() == "persona":
            return _PERSONA_BASE_URL
        return _SUMSUB_BASE_URL

    @staticmethod
    def _import_httpx():
        """Lazily import httpx. Returns the module or None if unavailable."""
        try:
            import httpx  # noqa: PLC0415
            return httpx
        except ImportError:
            return None

    def _sumsub_headers(self, method: str, path: str, body: bytes = b"") -> dict:
        """Build Sumsub HMAC-SHA256 signed request headers.

        Sumsub signs ``ts + METHOD + path + body`` with the secret key and
        sends ``X-App-Token`` / ``X-App-Access-Sig`` / ``X-App-Access-Ts``.
        (Documented scheme; UNVERIFIED end-to-end without a real app token.)
        """
        cfg = self._cfg()
        app_token = str(cfg.get("api_key", ""))
        secret = str(cfg.get("secret_key", "")).encode("utf-8")
        ts = str(int(time.time()))
        payload = ts.encode("utf-8") + method.upper().encode("utf-8") + path.encode("utf-8") + body
        signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        return {
            "X-App-Token": app_token,
            "X-App-Access-Sig": signature,
            "X-App-Access-Ts": ts,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # ── Methods ──────────────────────────────────────────────────────

    async def start_kyc(self, **params: Any) -> dict:
        """Start a KYC verification flow for a user via the configured provider.

        Real path (Sumsub): creates an applicant
        ``POST /resources/applicants?levelName=<level>`` and returns the
        provider applicant id. PII (``external_user_id``) is passed straight
        through to Sumsub and never stored locally.

        Expected params: ``external_user_id`` (str, your opaque user ref),
        optional ``level_name`` (Sumsub verification level).
        """
        cfg = self._cfg()
        api_key = cfg.get("api_key")
        secret_key = cfg.get("secret_key")

        # CREDENTIAL-GATED: need provider app token + secret.
        if is_placeholder_value(api_key):
            return not_deployed_response(self.service_name, extra={
                "method": "start_kyc",
                "missing": "services.kyc.api_key",
                "protocol": "Sumsub" if self._provider() == "sumsub" else "Persona",
            })
        if is_placeholder_value(secret_key):
            return not_deployed_response(self.service_name, extra={
                "method": "start_kyc",
                "missing": "services.kyc.secret_key",
                "protocol": "Sumsub" if self._provider() == "sumsub" else "Persona",
            })

        httpx = self._import_httpx()
        if httpx is None:
            return not_deployed_response(self.service_name, extra={
                "method": "start_kyc",
                "missing": "httpx (python package not installed)",
                "protocol": "Sumsub",
            })

        external_user_id = params.get("external_user_id") or params.get("user_id")
        if is_placeholder_value(external_user_id):
            return {
                "status": "invalid_request",
                "service": self.service_name,
                "method": "start_kyc",
                "error": "external_user_id is required (opaque user reference; no raw PII)",
            }

        provider = self._provider()
        base_url = self._base_url()

        try:
            if provider == "persona":
                # Persona inquiry creation — Bearer auth with the API key.
                # https://docs.withpersona.com/reference/create-an-inquiry  (UNVERIFIED)
                url = f"{base_url}/inquiries"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                }
                json_body = {"data": {"attributes": {
                    "reference-id": str(external_user_id),
                    "inquiry-template-id": cfg.get("template_id", ""),
                }}}
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(url, headers=headers, json=json_body)
                provider_name = "Persona"
            else:
                # Sumsub applicant creation — HMAC-signed.
                level_name = params.get("level_name") or cfg.get("level_name", "basic-kyc-level")
                path = f"/resources/applicants?levelName={level_name}"
                url = f"{base_url}{path}"
                import json as _json  # noqa: PLC0415
                body_bytes = _json.dumps({"externalUserId": str(external_user_id)}).encode("utf-8")
                headers = self._sumsub_headers("POST", path, body_bytes)
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(url, headers=headers, content=body_bytes)
                provider_name = "Sumsub"

            ok = 200 <= resp.status_code < 300
            data = {}
            try:
                data = resp.json()
            except Exception:  # noqa: BLE001
                data = {"raw": resp.text[:500]}

            return {
                "status": "started" if ok else "provider_error",
                "service": self.service_name,
                "method": "start_kyc",
                "provider": provider_name,
                "external_user_id": str(external_user_id),
                "applicant_id": data.get("id") or data.get("data", {}).get("id"),
                "http_status": resp.status_code,
                "provider_response": data,
                "pii_storage": "none (passed through to provider)",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("start_kyc provider call failed: %s", exc)
            return {
                "status": "provider_error",
                "service": self.service_name,
                "method": "start_kyc",
                "error": str(exc),
            }

    async def check_aml_risk(self, **params: Any) -> dict:
        """Check AML / sanctions / PEP risk for an existing applicant.

        Real path (Sumsub): fetches the applicant review status
        ``GET /resources/applicants/<applicantId>/status`` and surfaces the
        review answer (GREEN/RED) + reject labels (sanctions, PEP, etc.).

        Expected params: ``applicant_id`` (provider applicant id from
        ``start_kyc``).
        """
        cfg = self._cfg()
        api_key = cfg.get("api_key")
        secret_key = cfg.get("secret_key")

        # CREDENTIAL-GATED: need provider app token + secret.
        if is_placeholder_value(api_key):
            return not_deployed_response(self.service_name, extra={
                "method": "check_aml_risk",
                "missing": "services.kyc.api_key",
                "protocol": "Sumsub" if self._provider() == "sumsub" else "Persona",
            })
        if is_placeholder_value(secret_key):
            return not_deployed_response(self.service_name, extra={
                "method": "check_aml_risk",
                "missing": "services.kyc.secret_key",
                "protocol": "Sumsub" if self._provider() == "sumsub" else "Persona",
            })

        httpx = self._import_httpx()
        if httpx is None:
            return not_deployed_response(self.service_name, extra={
                "method": "check_aml_risk",
                "missing": "httpx (python package not installed)",
                "protocol": "Sumsub",
            })

        applicant_id = params.get("applicant_id") or params.get("id")
        if is_placeholder_value(applicant_id):
            return {
                "status": "invalid_request",
                "service": self.service_name,
                "method": "check_aml_risk",
                "error": "applicant_id is required (from start_kyc)",
            }

        provider = self._provider()
        base_url = self._base_url()

        try:
            if provider == "persona":
                # Persona inquiry fetch — Bearer auth. (UNVERIFIED)
                url = f"{base_url}/inquiries/{applicant_id}"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                }
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(url, headers=headers)
                provider_name = "Persona"
            else:
                # Sumsub applicant review status — HMAC-signed GET.
                path = f"/resources/applicants/{applicant_id}/status"
                url = f"{base_url}{path}"
                headers = self._sumsub_headers("GET", path, b"")
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(url, headers=headers)
                provider_name = "Sumsub"

            ok = 200 <= resp.status_code < 300
            data = {}
            try:
                data = resp.json()
            except Exception:  # noqa: BLE001
                data = {"raw": resp.text[:500]}

            # Sumsub: reviewResult.reviewAnswer is GREEN (clear) / RED (hit).
            review_result = data.get("reviewResult", {}) if isinstance(data, dict) else {}
            review_answer = review_result.get("reviewAnswer")
            reject_labels = review_result.get("rejectLabels", [])
            if review_answer == "GREEN":
                risk = "low"
            elif review_answer == "RED":
                risk = "high"
            else:
                risk = "unknown"

            return {
                "status": "checked" if ok else "provider_error",
                "service": self.service_name,
                "method": "check_aml_risk",
                "provider": provider_name,
                "applicant_id": str(applicant_id),
                "risk": risk,
                "review_answer": review_answer,
                "reject_labels": reject_labels,
                "http_status": resp.status_code,
                "provider_response": data,
                "pii_storage": "none (passed through to provider)",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("check_aml_risk provider call failed: %s", exc)
            return {
                "status": "provider_error",
                "service": self.service_name,
                "method": "check_aml_risk",
                "error": str(exc),
            }

    async def issue_kyc_credential(self, **params: Any) -> dict:
        """Issue an on-chain KYC verifiable credential as an EAS attestation.

        Real path: writes a W3C-style verifiable credential to the Ethereum
        Attestation Service (EAS) contract. ONLY a KYC level / pass flag and
        the holder address go on-chain — NO raw PII. The transaction is
        signed exclusively by the platform paymaster account
        (``Web3Manager.send_transaction``), so the platform pays gas and the
        operation is non-custodial: the user's wallet is never touched.

        Expected params: ``subject`` / ``recipient`` (holder wallet address),
        optional ``kyc_level`` (str), optional ``expiration`` (unix ts).

        Config keys used:
          - ``blockchain.eas_contract`` — EAS contract address (chain-level)
          - ``blockchain.eas_schema``   — registered KYC schema UID
        """
        bc = self._config.get("blockchain", {})
        eas_contract = bc.get("eas_contract", "")
        eas_schema = bc.get("eas_schema", "")

        # CREDENTIAL-GATED: RPC must be reachable + EAS configured + paymaster set.
        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "issue_kyc_credential",
                "missing": "blockchain.rpc_url (RPC unreachable / web3 offline)",
                "protocol": "EAS (Ethereum Attestation Service) verifiable credential",
            })
        if is_placeholder_value(eas_contract):
            return not_deployed_response(self.service_name, extra={
                "method": "issue_kyc_credential",
                "missing": "blockchain.eas_contract",
                "protocol": "EAS (Ethereum Attestation Service) verifiable credential",
            })
        if is_placeholder_value(eas_schema):
            return not_deployed_response(self.service_name, extra={
                "method": "issue_kyc_credential",
                "missing": "blockchain.eas_schema",
                "protocol": "EAS (Ethereum Attestation Service) verifiable credential",
            })
        if is_placeholder_value(self._web3.paymaster_key):
            return not_deployed_response(self.service_name, extra={
                "method": "issue_kyc_credential",
                "missing": "blockchain.paymaster_private_key",
                "protocol": "EAS (Ethereum Attestation Service) verifiable credential",
            })

        subject = params.get("subject") or params.get("recipient") or params.get("holder")
        if is_placeholder_value(subject):
            return {
                "status": "invalid_request",
                "service": self.service_name,
                "method": "issue_kyc_credential",
                "error": "subject (holder wallet address) is required",
            }

        kyc_level = str(params.get("kyc_level", "verified"))
        expiration = int(params.get("expiration", 0) or 0)

        try:
            from web3 import Web3  # noqa: PLC0415
            from eth_abi import encode  # noqa: PLC0415
        except ImportError as exc:
            return not_deployed_response(self.service_name, extra={
                "method": "issue_kyc_credential",
                "missing": f"web3/eth-abi (python package not installed: {exc})",
                "protocol": "EAS (Ethereum Attestation Service) verifiable credential",
            })

        try:
            recipient = Web3.to_checksum_address(str(subject))
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "invalid_request",
                "service": self.service_name,
                "method": "issue_kyc_credential",
                "error": f"invalid subject address {subject!r}: {exc}",
            }

        try:
            # Encode the credential payload — schema (string kycLevel, bool passed,
            # uint256 issuedAt). NO raw PII is encoded on-chain.
            issued_at = int(time.time())
            encoded_data = encode(
                ["string", "bool", "uint256"],
                [kyc_level, True, issued_at],
            )
            schema_bytes = bytes.fromhex(str(eas_schema).replace("0x", ""))

            contract = self._web3.load_contract(eas_contract, _EAS_ATTEST_ABI)
            tx = contract.functions.attest(
                (
                    schema_bytes,
                    (
                        recipient,
                        expiration,           # expirationTime (0 = none)
                        True,                 # revocable
                        b"\x00" * 32,         # refUID (none)
                        encoded_data,
                        0,                    # value
                    ),
                )
            ).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
                "gasPrice": self._web3.w3.eth.gas_price,
                "nonce": self._web3.w3.eth.get_transaction_count(
                    self._web3.get_account().address
                ),
            })

            # Platform paymaster signs + broadcasts (non-custodial, gas-sponsored).
            tx_hash = await self._web3.send_transaction(tx)

            return {
                "status": "issued",
                "service": self.service_name,
                "method": "issue_kyc_credential",
                "protocol": "EAS verifiable credential",
                "subject": recipient,
                "kyc_level": kyc_level,
                "issued_at": issued_at,
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform paymaster (non-custodial)",
                "pii_storage": "none (only kyc_level + holder address on-chain)",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("issue_kyc_credential attestation failed: %s", exc)
            return {
                "status": "chain_error",
                "service": self.service_name,
                "method": "issue_kyc_credential",
                "error": str(exc),
            }
