"""23-A — `passed` was the source literal `True` on a public attestation.

MEASURED at pin 42c9b19 by decoding the calldata handed to
`contract.functions.attest()`:

    encode(["string","bool","uint256"], [kyc_level, True, issued_at])
                                                    ^^^^ a LITERAL

and enumerated over the method's own source: applicant_id, check_aml_risk,
review_answer, reviewResult, risk, reject_labels, sanction, pep, start_kyc —
EVERY ONE ABSENT. A caller supplied an address and a free-text level, and the
platform's paymaster key notarised onto a PUBLIC ATTESTATION REGISTRY that this
person PASSED KYC at that level.

§U in its purest form. And unlike a carbon registry entry, an identity
credential on a wallet CANNOT BE RECALLED from parties who already relied on it.

THE FIRST DOMAIN WITH NO TEST FILE AT ALL — 2851 tests passed with all 50
findings present because ZERO of them touch KYCService. This file is the first.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.blockchain.services.registry import ServiceRegistry


def _svc():
    """The shipped config, PLUS the 23-D opt-in.

    23-D gates all three methods on `services.kyc.enabled`, and it precedes
    everything — a disabled service adjudicates nothing (§AS's bound on SR-2).
    These tests are about the VERIFICATION gate downstream of it, so they opt
    in explicitly rather than testing the enablement refusal by accident."""
    cfg = json.loads(Path("matrix.config.json.example").read_text())
    cfg.setdefault("services", {}).setdefault("kyc", {})["enabled"] = True
    return ServiceRegistry(cfg).get("kyc")


@pytest.mark.asyncio
async def test_a_free_text_level_cannot_mint_a_credential():
    """THE REPRODUCTION — the exact string the census drove."""
    out = await _svc().issue_kyc_credential(
        subject="0xATTACKER", kyc_level="enhanced-aml-cleared-sanctions-screened")
    assert out["status"] == "not_verified"
    assert out.get("refused") is True


@pytest.mark.asyncio
async def test_a_green_result_that_was_never_screened_is_refused():
    """The case the fix exists for. `check_aml_risk` cannot yet distinguish
    "screened and clear" from "never screened", so a GREEN answer alone is not
    evidence of a screen — wiring it in without this would attest an unscreened
    person as passed with one more step of indirection."""
    out = await _svc().issue_kyc_credential(
        subject="0xS", kyc_level="verified",
        verification_result={"sanctions_screened": False, "review_answer": "GREEN"})
    assert out["status"] == "not_verified"


@pytest.mark.asyncio
async def test_a_screened_green_result_passes_the_gate():
    """§AQ class 3 — the guard must still permit what it should. It then falls
    through to the chain-config refusal, which is correct under the shipped
    config."""
    out = await _svc().issue_kyc_credential(
        subject="0xS", kyc_level="verified",
        verification_result={"sanctions_screened": True, "review_answer": "GREEN"})
    assert out["status"] != "not_verified"


@pytest.mark.asyncio
async def test_the_verification_gate_precedes_the_config_gate():
    """SR-2. This block sat BELOW the chain-config gates, so an attempt to mint
    a credential with no verification came back as "rpc_url missing" — masking
    the attempt and telling the caller what to configure to make it work."""
    out = await _svc().issue_kyc_credential(subject="0xATTACKER", kyc_level="x")
    assert out["status"] == "not_verified", (
        "a config refusal is masking an attempt to obtain an unearned "
        "credential about a person"
    )


def test_passed_is_not_a_literal_in_the_attestation_payload():
    """§BC — the return value and the encoded payload are separate claims, and
    only the payload is durable. This asserts the payload."""
    import ast
    import inspect
    import textwrap
    from runtime.blockchain.services.kyc.service import KYCService

    # BY AST, NOT BY SUBSTRING. My first version used a regex and it matched
    # the EXPLANATORY COMMENT above the fix — which quotes the old
    # `[kyc_level, True, issued_at]` to show what the defect was. §AT's class,
    # third instance, inside a test written to guard this very payload: a
    # substring test cannot distinguish code from prose about code.
    tree = ast.parse(textwrap.dedent(inspect.getsource(KYCService.issue_kyc_credential)))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and (getattr(n.func, "id", None) == "encode"
                  or getattr(n.func, "attr", None) == "encode")]
    assert len(calls) == 1, f"expected one encode() call, found {len(calls)}"
    args = calls[0].args[1]
    assert isinstance(args, ast.List) and len(args.elts) == 3
    passed = args.elts[1]
    assert not isinstance(passed, ast.Constant), (
        f"`passed` is a source literal ({getattr(passed, 'value', '?')!r}) — the "
        f"platform is asserting a person's regulatory status on its own authority"
    )
    assert isinstance(passed, ast.Name) and passed.id == "_passed"


# ─────────────────────────────── 23-B ───────────────────────────────
# THE FALSE-POSITIVE-ON-A-PERSON PATH.
#
# MEASURED at pin 42c9b19, synthetic placeholders only:
#   applicant_id = "TEST_ENTITY_A/../TEST_ENTITY_B"
#   path served  : /resources/applicants/TEST_ENTITY_B/status
#   returned     : applicant_id=TEST_ENTITY_A/../TEST_ENTITY_B, risk=high, RED
#
# A RED sanctions verdict belonging to one record, returned bearing another
# identifier — and `_sumsub_headers` signs the SAME unencoded string, so the
# injected path is validly HMAC-signed with the platform's own credentials.

def _kyc_armed():
    from runtime.blockchain.services.kyc.service import KYCService
    return KYCService({"services": {"kyc": {
        "enabled": True, "api_key": "k", "secret_key": "s",
        "provider": "sumsub"}}})


def _capture(served):
    import httpx

    class _C(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(self._r)
            super().__init__(*a, **k)

        def _r(self, request):
            served.append(request.url.path)
            return httpx.Response(200, json={"reviewResult": {"reviewAnswer": "RED"}})

    return _C


@pytest.mark.parametrize("bad", [
    "TEST_ENTITY_A/../TEST_ENTITY_B",
    "TEST_ENTITY_V/status?x=/resources/applicants/TEST_ENTITY_O",
    "TEST_ENTITY_A/status",
    "TEST_ENTITY A",
])
@pytest.mark.asyncio
async def test_an_identifier_that_could_select_another_record_is_refused(bad):
    """THE REPRODUCTION, and the request must never be sent."""
    import httpx
    from unittest.mock import patch
    served = []
    with patch.object(httpx, "AsyncClient", _capture(served)):
        out = await _kyc_armed().check_aml_risk(applicant_id=bad)
    assert out["status"] == "invalid_request"
    assert out.get("refused") is True
    assert served == [], "the provider request was sent despite the refusal"


@pytest.mark.asyncio
async def test_an_opaque_identifier_is_still_permitted():
    """§AQ class 3 — the guard must still permit what it permitted."""
    import httpx
    from unittest.mock import patch
    served = []
    with patch.object(httpx, "AsyncClient", _capture(served)):
        out = await _kyc_armed().check_aml_risk(applicant_id="TEST_ENTITY_001")
    assert out["status"] == "checked"
    assert served == ["/resources/applicants/TEST_ENTITY_001/status"]


def test_the_disposition_is_a_refusal_not_a_sanitiser():
    """A transform on an identifier that reaches a third-party screening query
    is a GUESS ABOUT THEIR PARSER — and R-23.2 records that no real provider
    response has ever been observed in this engagement. The value is rejected,
    never rewritten."""
    import inspect
    from runtime.blockchain.services.kyc.service import KYCService
    src = inspect.getsource(KYCService.check_aml_risk)
    for transform in ("quote(", "urlencode(", ".replace(", "unquote("):
        assert transform not in src, (
            f"applicant_id is being rewritten with {transform} — that is a "
            f"guess about the provider's parser, not a control"
        )


# ─────────────────────────────── 23-C ───────────────────────────────

def _body_client(body):
    import httpx

    class _C(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(
                lambda r: httpx.Response(200, json=body))
            super().__init__(*a, **k)

    return _C


def _kyc(provider):
    from runtime.blockchain.services.kyc.service import KYCService
    return KYCService({"services": {"kyc": {
        "enabled": True, "api_key": "k", "secret_key": "s",
        "provider": provider}}})


@pytest.mark.parametrize("body", [
    {"data": {"attributes": {"status": "declined", "failure-reason": "watchlist-hit"}}},
    {"data": {"attributes": {"status": "approved"}}},
])
@pytest.mark.asyncio
async def test_an_ungradeable_provider_is_refused_not_graded_unknown(body):
    """MEASURED before 23-C: under provider="persona" the parser read
    SUMSUB-ONLY keys, so DECLINED and APPROVED were BYTE-IDENTICAL in the
    verdict fields — status 'checked', risk 'unknown'. A watchlist hit on a
    named person silently downgraded, while the response affirmatively claimed
    the check ran.

    We do NOT write a Persona parser: R-23.2 records that no real provider
    response has ever been observed in this engagement, and a grader for a
    shape we have never seen would produce A VERDICT ABOUT A PERSON from a
    guess."""
    import httpx
    from unittest.mock import patch
    with patch.object(httpx, "AsyncClient", _body_client(body)):
        out = await _kyc("persona").check_aml_risk(applicant_id="TEST_ENTITY_001")
    assert out["status"] == "provider_unsupported"
    assert out["sanctions_screened"] is False
    assert "NOT SCREENED" in out["sanctions_disclosure"]
    assert "risk" not in out


@pytest.mark.asyncio
async def test_a_graded_sumsub_verdict_reports_that_it_was_screened():
    """§AQ class 3 — the provider we CAN grade must still be graded."""
    import httpx
    from unittest.mock import patch
    with patch.object(httpx, "AsyncClient",
                      _body_client({"reviewResult": {"reviewAnswer": "GREEN"}})):
        out = await _kyc("sumsub").check_aml_risk(applicant_id="TEST_ENTITY_001")
    assert out["status"] == "checked"
    assert out["risk"] == "low"
    assert out["sanctions_screened"] is True
    assert out["sanctions_disclosure"] is None


@pytest.mark.asyncio
async def test_a_sumsub_response_with_no_adjudication_says_it_was_not_screened():
    """THE FIELD THAT WAS MISSING. Previously indistinguishable from a real
    screen: both returned status 'checked'. Ported from
    cross_border/compliance.py:205, where the honest version already existed
    and was stated only at that scope (§AI.1)."""
    import httpx
    from unittest.mock import patch
    with patch.object(httpx, "AsyncClient", _body_client({})):
        out = await _kyc("sumsub").check_aml_risk(applicant_id="TEST_ENTITY_001")
    assert out["status"] == "checked"
    assert out["risk"] == "unknown"
    assert out["sanctions_screened"] is False
    assert "NOT SCREENED" in out["sanctions_disclosure"]


# ─────────────────────────────── 23-D ───────────────────────────────

@pytest.mark.parametrize("method,kwargs", [
    ("start_kyc", {}),
    ("check_aml_risk", {"applicant_id": "TEST_ENTITY_001"}),
    ("issue_kyc_credential", {"subject": "0xS"}),
])
@pytest.mark.parametrize("enabled", [None, False, "true", 1])
@pytest.mark.asyncio
async def test_every_method_refuses_unless_enabled_is_exactly_true(method, kwargs, enabled):
    """23-D. `services.kyc.enabled` had a WRITER (the shipped config) and NO
    READERS — enumerated: every config read in the package is provider,
    endpoint, api_key, secret_key, template_id, level_name, eas_contract,
    eas_schema. 'enabled' appeared nowhere.

    An operator reading `services.kyc {enabled: false}` concluded the identity
    service was off. It was not. 19-A's template — and this is the service that
    most needed it: the same guard already protects a treasury, a token mint
    and real_estate, while the one making durable claims about NAMED PEOPLE
    had none.

    §AK.2: all THREE methods, not one."""
    from runtime.blockchain.services.kyc.service import KYCService
    cfg = {"services": {"kyc": {"api_key": "k", "secret_key": "s"}}}
    if enabled is not None:
        cfg["services"]["kyc"]["enabled"] = enabled
    out = await getattr(KYCService(cfg), method)(**kwargs)
    assert "enabled must be true" in str(out.get("missing", ""))


@pytest.mark.asyncio
async def test_an_opted_in_operator_is_not_blocked():
    """§AQ class 3 — proven by reaching a DIFFERENT refusal."""
    from runtime.blockchain.services.kyc.service import KYCService
    cfg = {"services": {"kyc": {"enabled": True, "api_key": "k", "secret_key": "s"}}}
    out = await KYCService(cfg).check_aml_risk(applicant_id="TEST_ENTITY_001")
    assert "enabled must be true" not in str(out.get("missing", ""))
