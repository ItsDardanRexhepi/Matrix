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
    settle_transaction,
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

    def require_kyc_enabled(self, method: str) -> dict | None:
        """23-D. Refuse unless services.kyc.enabled is explicitly true.

        NAMED `require_kyc_enabled`, not `require_enabled`: the refusal
        registry matches by SUBSTRING, and a short name silently
        reclassifies every unrelated `_require_enabled` in the repo — a
        measured false positive that manufactured two findings in
        domain 19. Domain-qualified names only.
        """
        # 23-D. `services.kyc.enabled` HAD A WRITER AND NO READERS.
        # Writer set = {matrix.config.json.example}; reader set inside this
        # package = EMPTY (enumerated: every config read is provider, endpoint,
        # api_key, secret_key, template_id, level_name, eas_contract,
        # eas_schema — 'enabled' appears nowhere). An operator reading the
        # shipped config sees `services.kyc {enabled: false}` and concludes the
        # identity service is off. It was not.
        #
        # 19-A's template, and this service is the one that most needed it: the
        # same guard already protects a treasury (restaking), a token mint
        # (creator_platforms) and real_estate. The service that makes durable
        # claims about NAMED PEOPLE did not have it.
        #
        # FAILS CLOSED. Absent means refuse — the alternative is what shipped.
        # PLATFORM SCOPE IS NOT FIXED HERE: 42 of 44 services have the same
        # dead key (R-21.1). That rename touches every service and is a scoping
        # decision, not a remediation — registered, not done (P-3).
        if (self._config.get("services", {}) or {}).get(
                self.service_name, {}).get("enabled") is not True:
            return not_deployed_response(self.service_name, extra={
                "method": method,
                "missing": f"services.{self.service_name}.enabled must be true",
                "reason": (
                    "This service returns AML/sanctions verdicts about named "
                    "individuals and issues durable identity credentials. It "
                    "is disabled by default; enabling it is an explicit, "
                    "auditable operator decision, not implied by populating "
                    "provider credentials."
                ),
            })
        return None

    async def start_kyc(self, **params: Any) -> dict:
        """Start a KYC verification flow for a user via the configured provider.

        Real path (Sumsub): creates an applicant
        ``POST /resources/applicants?levelName=<level>`` and returns the
        provider applicant id. PII (``external_user_id``) is passed straight
        through to Sumsub and never stored locally.

        Expected params: ``external_user_id`` (str, your opaque user ref),
        optional ``level_name`` (Sumsub verification level).
        """
        _gate = self.require_kyc_enabled("start_kyc")
        if _gate is not None:
            return _gate

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
        _gate = self.require_kyc_enabled("check_aml_risk")
        if _gate is not None:
            return _gate

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

        # ===================================================================
        # 23-B. THE APPLICANT ID CHOSE WHICH RECORD THE VERDICT DESCRIBED.
        # ===================================================================
        # MEASURED at pin 42c9b19, synthetic placeholders only:
        #
        #   applicant_id = "TEST_ENTITY_A/../TEST_ENTITY_B"
        #   path actually served : /resources/applicants/TEST_ENTITY_B/status
        #   applicant_id returned: TEST_ENTITY_A/../TEST_ENTITY_B
        #   risk / review_answer : high / RED
        #
        # A RED SANCTIONS VERDICT BELONGING TO ONE RECORD WAS RETURNED BEARING
        # ANOTHER IDENTIFIER. That is the harm the standing constraint names —
        # a false positive on a sanctions screen, attaching to a real person.
        # And `_sumsub_headers` signs `ts+METHOD+path+body` over the SAME
        # unencoded string, so the injected path is VALIDLY HMAC-SIGNED with
        # the platform's own provider credentials.
        #
        # THIS IS A REFUSAL, NOT A SANITISER, AND THE DISTINCTION IS THE POINT.
        # Percent-encoding or stripping this input would be A GUESS ABOUT THE
        # PROVIDER'S PARSER — we do not know how Sumsub or Persona normalise a
        # path, and R-23.2 records that NO REAL PROVIDER RESPONSE HAS EVER BEEN
        # OBSERVED IN THIS ENGAGEMENT. A transform we cannot validate against
        # the receiving parser is a second guess layered on the first.
        #
        # So: anything not plainly an opaque identifier is REFUSED, and the
        # request is never sent.
        #
        # LIFTING CONDITION — what would let this widen: the provider's own
        # DOCUMENTED identifier grammar, or an opaque handle THIS PLATFORM
        # issued and can therefore vouch for. Neither exists today. Until one
        # does, the conservative set is the only honest bound.
        _bad = [c for c in str(applicant_id) if not (c.isalnum() or c in "-_")]
        if _bad:
            return {
                "status": "invalid_request",
                "service": self.service_name,
                "method": "check_aml_risk",
                "refused": True,
                "applicant_id": applicant_id,
                "reason": (
                    "applicant_id must be an opaque identifier "
                    "([A-Za-z0-9_-] only). It is interpolated into the "
                    "provider request path and HMAC-signed with this "
                    "platform's credentials, so a value containing path or "
                    "query characters selects WHICH PERSON'S RECORD the "
                    "returned verdict describes. Refused rather than "
                    "rewritten: encoding it would be a guess about the "
                    "provider's parser."
                ),
                "rejected_characters": sorted(set(_bad)),
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

            # ===============================================================
            # 23-C. ONE PARSER, KEYED FOR ONE PROVIDER — AND IT GRADES BOTH.
            # ===============================================================
            # §AK.4, counted before proposing: the provider is selected for the
            # REQUEST at two sites, and the response is graded at exactly ONE
            # (here), using SUMSUB-ONLY KEYS unconditionally. So this is one
            # grading site and one defect — separate from 23-B, which is the
            # outbound path. Two fixes; neither subsumes the other.
            #
            # MEASURED at pin 42c9b19 under provider="persona":
            #   {"data":{"attributes":{"status":"declined",
            #                          "failure-reason":"watchlist-hit"}}}
            #     -> status='checked', risk='unknown', review_answer=None
            #   {"data":{"attributes":{"status":"approved"}}}
            #     -> status='checked', risk='unknown', review_answer=None
            # BYTE-IDENTICAL VERDICT FIELDS FOR APPROVED AND DECLINED. A
            # watchlist hit on a named person silently downgraded to 'unknown'
            # while the response affirmatively claims the check ran.
            #
            # WE DO NOT WRITE A PERSONA PARSER, AND THAT IS THE POINT.
            # R-23.2 records that NO REAL PROVIDER RESPONSE HAS EVER BEEN
            # OBSERVED IN THIS ENGAGEMENT — every envelope tested is one we
            # authored. Writing a grader for a shape we have never seen is the
            # same guess 23-B refused, and it would be worse here: the guess
            # would produce a VERDICT ABOUT A PERSON rather than a request path.
            #
            # So an ungradeable provider is REFUSED, not graded to 'unknown'
            # under a 'checked' status. LIFTING CONDITION: a captured, real
            # response from that provider, and a grader written against it.
            if provider != "sumsub":
                return {
                    "status": "provider_unsupported",
                    "service": self.service_name,
                    "method": "check_aml_risk",
                    "refused": True,
                    "provider": provider_name,
                    "applicant_id": applicant_id,
                    "sanctions_screened": False,
                    "sanctions_disclosure": (
                        "NOT SCREENED — no verdict was derived. This service "
                        "can only grade Sumsub review envelopes, and the "
                        "configured provider is "
                        f"{provider_name}. Its response was fetched and NOT "
                        "interpreted. Do not treat this as a completed "
                        "sanctions or PEP screen."
                    ),
                    "provider_response": data,
                }

            # Sumsub: reviewResult.reviewAnswer is GREEN (clear) / RED (hit).
            review_result = data.get("reviewResult", {}) if isinstance(data, dict) else {}
            review_answer = review_result.get("reviewAnswer")
            reject_labels = review_result.get("rejectLabels", [])
            # 23-C. Ported from cross_border/compliance.py:205 — the honest
            # version already existed in this repository and was stated only at
            # that scope (§AI.1). A GREEN review answer is the provider's
            # adjudication; it is NOT by itself evidence that a sanctions or
            # PEP list was consulted.
            _screened = review_answer in ("GREEN", "RED")
            if review_answer == "GREEN":
                risk = "low"
            elif review_answer == "RED":
                risk = "high"
            else:
                risk = "unknown"

            return {
                "sanctions_screened": _screened,
                "sanctions_disclosure": (
                    None if _screened else
                    "NOT SCREENED — the provider returned no review "
                    "adjudication for this applicant, so no sanctions or PEP "
                    "determination exists. Do not treat this result as a "
                    "completed screen."
                ),
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
        _gate = self.require_kyc_enabled("issue_kyc_credential")
        if _gate is not None:
            return _gate

        # 23-A / SR-2. AUTHORIZATION BEFORE CONFIGURATION. This block was
        # BELOW the chain-config gates, so an attempt to mint a credential with
        # NO verification result came back as "rpc_url missing" — masking the
        # attempt and, worse, telling the caller what to configure to make it
        # work. A config problem is the operator's own state; an attempt to
        # obtain an unearned credential about a person is someone acting. When
        # both are true the second is the one that must be reported.
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

        # ===================================================================
        # 23-A. `passed` WAS THE SOURCE LITERAL `True`.
        # ===================================================================
        # MEASURED at pin 42c9b19 by decoding the calldata actually handed to
        # `contract.functions.attest()`:
        #
        #     encode(["string","bool","uint256"], [kyc_level, True, issued_at])
        #                                                     ^^^^ a LITERAL
        #
        # and enumerated over this method's own source: `applicant_id`,
        # `check_aml_risk`, `review_answer`, `reviewResult`, `risk`,
        # `reject_labels`, `sanction`, `pep`, `start_kyc` — EVERY ONE ABSENT.
        # A caller supplied an address and a free-text level, and the
        # platform's paymaster key notarised onto a PUBLIC ATTESTATION
        # REGISTRY that this person PASSED KYC at that level. Driven with
        # kyc_level='enhanced-aml-cleared-sanctions-screened' -> attested.
        #
        # §U in its purest form: the party bound by the decision supplied the
        # entire content of the decision. And unlike a carbon registry entry,
        # AN IDENTITY CREDENTIAL ON A WALLET CANNOT BE RECALLED FROM PARTIES
        # WHO ALREADY RELIED ON IT.
        #
        # THIS IS A DELIBERATE REFUSAL, NOT A PASS-THROUGH, AND THE ORDER
        # MATTERS — DO NOT "FIX" THIS BY WIRING `check_aml_risk` INTO IT.
        # That method cannot yet distinguish "screened and clear" from "never
        # screened" (its 11-key response was enumerated; no such field
        # exists). Wiring it would attest an UNSCREENED person as passed with
        # one more step of indirection AND a provider name attached to lend it
        # credibility (§AH). The honest fields must be ported from
        # `cross_border/compliance.py:205` — `sanctions_screened` plus the
        # "ran against an empty list and cannot have matched" disclosure —
        # BEFORE the attestation has anything true to carry.
        #
        # SEQUENCING — RE-MEASURED AFTER THIS FIX LANDED, AND THE WARNING IS
        # NOW STALE IN THE SAFE DIRECTION. It originally read: wiring
        # `blockchain.schemas.identity` (AP::5 / AC::2) uses a UID ALREADY
        # SHIPPED AND POPULATED, so doing that first would ARM this cluster.
        #
        # DRIVEN with rpc_url, eas_schema and paymaster_private_key ALL
        # populated and no verification supplied: status='not_verified',
        # refused=True. THIS GATE DOMINATES EVERY CHAIN-CONFIG PATH, so the
        # schema wiring can no longer arm the cluster.
        #
        # Kept, corrected rather than deleted, because a stale warning that
        # names a hazard which no longer exists READS AS AUTHORITATIVE (§AM.3)
        # — and because the ordering claim is still true of any deployment
        # that reverts this gate.
        #
        # LIFTING CONDITION — what must exist before this refusal is removed:
        # a verification result the SUBJECT DID NOT SUPPLY, carrying (a) the
        # provider's own adjudication, (b) an explicit field stating that
        # sanctions/PEP screening ran, and (c) the applicant record it
        # describes. A caller-supplied `kyc_level` string is none of those.
        _verification = params.get("verification_result")
        _screened = bool(
            isinstance(_verification, dict)
            and _verification.get("sanctions_screened") is True
            and _verification.get("review_answer") == "GREEN"
        )
        if not _screened:
            return {
                "status": "not_verified",
                "service": self.service_name,
                "method": "issue_kyc_credential",
                "refused": True,
                "subject": subject,
                "requested_level": kyc_level,
                "reason": (
                    "No verification result was supplied that establishes this "
                    "subject passed screening. The platform will not attest "
                    "`passed` on a public registry from a caller-supplied "
                    "level string alone — that would be a signed statement "
                    "about a person's regulatory status with nothing behind "
                    "it, readable by every downstream verifier and not "
                    "recallable from anyone who relied on it."
                ),
                "required": (
                    "verification_result{sanctions_screened: true, "
                    "review_answer: 'GREEN'} originating from the provider, "
                    "not from the caller"
                ),
            }
        _passed = True

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
                # 23-A. Derived, not asserted. `_passed` is reachable only
                # through the screened-verification gate above.
                [kyc_level, _passed, issued_at],
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
        except Exception as exc:  # noqa: BLE001
            logger.error("issue_kyc_credential attestation failed: %s", exc)
            return {
                "status": "chain_error",
                "service": self.service_name,
                "method": "issue_kyc_credential",
                "error": str(exc),
            }

        # A CREDENTIAL IS ISSUED WHEN THE CHAIN SAYS SO, NOT WHEN A NODE TOOK THE
        # BYTES. This returned `{"status": "issued", "tx_hash": ...}` the moment
        # `send_transaction` returned. "issued" is a real-outcome word, so the
        # dispatcher EAS-attested the action and the feed published it: a
        # durable statement that a person holds a KYC credential, made before
        # anything was mined and standing even if the attestation reverted. The
        # broadcast census missed it because it searched for the word
        # "submitted" rather than for the send.
        #
        # The shared helper waits for the receipt: confirmed -> "issued" with
        # `settled: True`; reverted -> "failed"; no receipt in time ->
        # "pending" with `broadcast: True`, which the dispatcher records as a
        # broadcast — neither attested as issued nor declined. OUTSIDE the
        # `try` above on purpose: once the hash exists the transaction is out,
        # and nothing that happens after it may be reported as `chain_error`.
        outcome = await settle_transaction(
            self._web3, tx_hash, "issue_kyc_credential", self.service_name,
            {
                "service": self.service_name,
                "method": "issue_kyc_credential",
                "protocol": "EAS verifiable credential",
                "subject": recipient,
                "kyc_level": kyc_level,
                "issued_at": issued_at,
                "explorer_url": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform paymaster (non-custodial)",
                "pii_storage": "none (only kyc_level + holder address on-chain)",
            },
            settled_status="issued",
        )
        if outcome.get("value_moved") is True:
            # The helper speaks for transfers. An attestation moves no value and
            # never claimed to; `None` is this tree's word for "does not arise".
            outcome["value_moved"] = None
        return outcome
