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
    return ServiceRegistry(
        json.loads(Path("openmatrix.config.json.example").read_text())
    ).get("kyc")


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
        "api_key": "k", "secret_key": "s", "provider": "sumsub"}}})


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
