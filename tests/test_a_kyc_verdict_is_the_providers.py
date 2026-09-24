"""A KYC attestation says a person passed. The platform now says it only when
the provider did, and it writes nothing about the person but a fixed word.

Three sentences in runtime/blockchain/services/kyc/service.py, each checked
against the code:

* The payload comment said the pass flag was derived rather than asserted,
  reachable only through the screened-verification gate. The gate read a
  `verification_result` dict from the request. A caller who sent
  {"sanctions_screened": True, "review_answer": "GREEN"} reached
  `passed = True`, with the platform's key, on a public registry, from its own
  words. The verdict is now fetched from the provider by the method itself.
* "ONLY a KYC level / pass flag and the holder address go on-chain — NO raw
  PII." `kyc_level` was caller free text, encoded verbatim. It is now one word
  from KYC_LEVELS.
* "only opaque references (applicant_id, review status, an attestation UID /
  KYC level) are returned". Every provider call returned the provider's whole
  response envelope as `provider_response`. Only the fields read from it are
  returned now, and the names of its top-level keys.

What the verdict still does not establish is named rather than hidden: the
applicant is the caller's choice, and nothing ties it to the subject wallet.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import patch

import httpx

from runtime.blockchain.services.kyc import service as kyc_service
from runtime.blockchain.services.kyc.service import KYCService

# Read through getattr so that, against a tree without the vocabulary, each
# check fails on its own assertion instead of the module failing to import.
KYC_LEVELS = getattr(kyc_service, "KYC_LEVELS", None)

_SUBJECT = "0x" + "4" * 40
_CALLERS_OWN_WORDS = {"sanctions_screened": True, "review_answer": "GREEN"}


def _svc() -> KYCService:
    """The shipped config, opted in, with provider credentials. The chain is
    not configured, so a request that gets PAST the verdict gate is answered
    by a chain-config refusal, which is how these tests see that it got past."""
    cfg = json.loads(Path("matrix.config.json.example").read_text())
    cfg.setdefault("services", {})["kyc"] = {
        "enabled": True, "api_key": "k", "secret_key": "s", "provider": "sumsub"}
    return KYCService(cfg)


def _provider_answers(body: dict, served: list | None = None):
    class _C(httpx.AsyncClient):
        def __init__(self, *a, **k):
            def _r(request):
                if served is not None:
                    served.append(request.url.path)
                return httpx.Response(200, json=body)
            k["transport"] = httpx.MockTransport(_r)
            super().__init__(*a, **k)
    return patch.object(httpx, "AsyncClient", _C)


_GREEN = {"reviewResult": {"reviewAnswer": "GREEN"}}
_RED = {"reviewResult": {"reviewAnswer": "RED", "rejectLabels": ["SANCTIONS"]}}


# ── the verdict is the provider's ──────────────────────────────────────────

async def test_the_callers_own_verification_result_is_not_a_verdict():
    """THE REPRODUCTION. No applicant, no provider call, only the request's
    word that the subject was screened and clear."""
    out = await _svc().issue_kyc_credential(
        subject=_SUBJECT, kyc_level="verified",
        verification_result=dict(_CALLERS_OWN_WORDS))
    assert out["status"] == "not_verified", (
        "a verification result written by the caller reached the attestation "
        f"path: {out}")
    assert out.get("refused") is True


async def test_the_request_cannot_overrule_a_red_review():
    """The caller says GREEN; the provider, asked for the same applicant,
    says RED. The provider is the one that is read."""
    served: list = []
    with _provider_answers(_RED, served):
        out = await _svc().issue_kyc_credential(
            subject=_SUBJECT, applicant_id="TEST_ENTITY_001",
            verification_result=dict(_CALLERS_OWN_WORDS))
    assert served == ["/resources/applicants/TEST_ENTITY_001/status"], served
    assert out["status"] == "not_verified", out


async def test_a_review_with_no_screen_is_not_a_pass():
    """GREEN is not enough by itself: check_aml_risk says whether a sanctions
    screen ran, and a review with no adjudication says it did not."""
    with _provider_answers({}):
        out = await _svc().issue_kyc_credential(
            subject=_SUBJECT, applicant_id="TEST_ENTITY_001")
    assert out["status"] == "not_verified", out


async def test_a_screened_green_review_the_platform_fetched_passes_the_gate():
    """Scope pin: the gate must still permit what it should. Past the gate the
    shipped config has no chain, so the answer is a chain-config refusal.

    Given a binding of the applicant to the subject, which the platform does
    not hold for any pair today (tests/test_kyc_issuance_waits_for_a_binding.py
    holds that without one the same review is refused)."""
    svc = _svc()
    svc._applicant_binding = lambda _applicant, _subject: "bound in this test"
    with _provider_answers(_GREEN):
        out = await svc.issue_kyc_credential(
            subject=_SUBJECT, applicant_id="TEST_ENTITY_001")
    assert out["status"] not in ("not_verified", "invalid_request"), out
    assert out.get("missing"), out


# ── nothing about the person but a fixed word reaches the chain ────────────

async def test_a_level_outside_the_vocabulary_is_refused_even_after_a_pass():
    with _provider_answers(_GREEN):
        out = await _svc().issue_kyc_credential(
            subject=_SUBJECT, applicant_id="TEST_ENTITY_001",
            kyc_level="Jane Example, born 1990-01-01")
    assert out["status"] == "invalid_request", out
    assert out.get("refused") is True
    assert KYC_LEVELS is not None and sorted(KYC_LEVELS) == ["verified"]


# ── the provider's envelope is not returned ────────────────────────────────

async def test_check_aml_risk_returns_the_fields_it_read_not_the_envelope():
    body = {**_GREEN, "info": {"firstName": "Jane", "dob": "1990-01-01"}}
    with _provider_answers(body):
        out = await _svc().check_aml_risk(applicant_id="TEST_ENTITY_001")
    assert out["status"] == "checked", out
    assert "provider_response" not in out, out
    assert "Jane" not in json.dumps(out) and "1990-01-01" not in json.dumps(out)
    assert out["provider_response_fields"] == ["info", "reviewResult"]


async def test_start_kyc_returns_the_applicant_not_the_envelope():
    body = {"id": "TEST_ENTITY_001", "info": {"firstName": "Jane"}}
    with _provider_answers(body):
        out = await _svc().start_kyc(external_user_id="user-ref-1")
    assert out["applicant_id"] == "TEST_ENTITY_001", out
    assert "provider_response" not in out, out
    assert "Jane" not in json.dumps(out)


# ── the sentences ──────────────────────────────────────────────────────────

def test_the_reporting_order_sentence_names_the_gate_that_runs_first():
    """ "When both are true the second is the one that must be reported" read
    as covering every refusal. The enablement gate runs first on purpose (a
    disabled service adjudicates nothing), and the comment now says so."""
    src = " ".join(inspect.getsource(KYCService.issue_kyc_credential)
                   .replace("#", " ").split())
    assert "When both are true the second is the one that must be reported" not in src
    assert "enablement gate above runs first" in src


def test_the_docstrings_say_where_the_verdict_comes_from():
    src = inspect.getsource(KYCService.issue_kyc_credential)
    doc = " ".join((KYCService.issue_kyc_credential.__doc__ or "").split())
    assert "verification result supplied with the request is not read" in doc
    assert "nothing ties the applicant to the" in doc
    assert 'params.get("verification_result")' not in src
