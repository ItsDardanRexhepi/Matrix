"""RUN-3 — the contract converter must not issue a green light on a stub.

The pipeline is pure regex: parser.py -> IR -> generator.py, no model. It
recovers names, state variables, and function signatures correctly, but it does
not synthesise function bodies. Fed a pseudocode declaration it produces a
syntactically valid, behaviorally inert contract — functions that exist and do
nothing — and the old code reported that as:

    status: "success"
    audit: {passed: true, critical_count: 0, high_count: 0}

The audit passed precisely because an empty contract has no vulnerabilities. A
user was told their rental agreement converted successfully and cleared security
review, when what they got would accept no rent and terminate nothing.

These tests cover the two things that matter:
  part 1 — `payable` (written after the parens, the normal way) survives to the
           generated Solidity.
  parts 2 & 3 — a stub-only conversion returns neither status "success" nor
           audit.passed == true, and instead names what it left empty.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.contract_conversion.service import (
    ContractConversionService,
)

RENTAL_PSEUDOCODE = """contract Rental
state landlord: address
state rentAmount: uint256
function payRent() payable
function terminate()"""

# A contract whose functions carry real bodies — must remain a clean success.
IMPLEMENTED_PSEUDOCODE = """contract Counter
state count: uint256
function increment()
    count = count + 1
function get() view returns uint256
    return count"""


@pytest.fixture
def service():
    return ContractConversionService(config={})


# ── part 1: modifiers survive ──────────────────────────────────────────────

def _signature_block(src: str, func_name: str) -> str:
    """The rendered signature of *func_name* — the `function NAME(...)` line
    plus following lines up to the opening brace, since the generator wraps
    qualifiers onto their own line."""
    lines = src.splitlines()
    for i, ln in enumerate(lines):
        if f"function {func_name}(" in ln:
            block = [ln]
            for nxt in lines[i + 1:]:
                block.append(nxt)
                if "{" in nxt:
                    break
            return "\n".join(block)
    return ""


async def test_payable_modifier_survives_to_solidity(service):
    """`function payRent() payable` must generate a payable function."""
    result = await service.convert(RENTAL_PSEUDOCODE, "pseudocode")
    src = result["generated_source"]
    assert "payRent" in src, "payRent function was dropped"

    pay_block = _signature_block(src, "payRent")
    assert "payable" in pay_block, (
        f"payable was dropped from payRent:\n{pay_block!r}\n"
        "The mutability sniff used to stop at the closing paren, so a qualifier "
        "written after the parens was invisible."
    )
    # And it must be specific to payRent — terminate() must NOT be payable.
    assert "payable" not in _signature_block(src, "terminate"), (
        "payable leaked onto terminate(), which was not declared payable"
    )


async def test_function_named_view_is_not_misclassified(service):
    """A function merely NAMED like a qualifier keeps nonpayable mutability."""
    src_pseudo = "contract X\nfunction viewBalance() returns uint256"
    result = await service.convert(src_pseudo, "pseudocode")
    payline = next(
        (ln for ln in result["generated_source"].splitlines()
         if "function viewBalance" in ln),
        "",
    )
    # It must NOT be tagged `view` just because "view" is a substring of its name.
    assert " view " not in f" {payline} ", (
        f"viewBalance was misread as a view function: {payline!r}"
    )


# ── parts 2 & 3: no green light on a stub ──────────────────────────────────

async def test_stub_conversion_is_not_reported_as_success(service):
    """A bodyless conversion must be status 'partial', not 'success'."""
    result = await service.convert(RENTAL_PSEUDOCODE, "pseudocode")
    assert result["status"] != "success", (
        f"a contract with empty function bodies was reported {result['status']!r}"
    )
    assert result["status"] == "partial"
    assert set(result["unimplemented"]) == {"payRent", "terminate"}, (
        f"expected both functions listed as unimplemented, got "
        f"{result['unimplemented']!r}"
    )


async def test_stub_conversion_does_not_claim_audit_passed(service):
    """THE HAZARD: no passed==true security verdict on a bodyless contract."""
    result = await service.convert(RENTAL_PSEUDOCODE, "pseudocode")

    assert result["audit_passed"] is not True, (
        "the converter issued a passing security verdict on a contract with no "
        "executable logic — the false green light RUN-3 is about"
    )
    audit = result["audit"]
    assert audit.get("verdict") == "not_applicable", (
        f"expected verdict not_applicable, got {audit!r}"
    )
    assert "passed" not in audit or audit["passed"] is not True


async def test_empty_declaration_yields_not_applicable(service):
    """Prose fed as pseudocode yields a name-only contract — also N/A."""
    result = await service.convert(
        "contract Rental { landlord receives 2000 monthly from tenant }",
        "pseudocode",
    )
    # Whatever the parser recovers, with no real function bodies the audit must
    # not pass and the status must not be success.
    assert result["status"] != "success"
    assert result["audit_passed"] is not True


# ── the honest-success path must still work ────────────────────────────────

async def test_implemented_contract_is_still_a_clean_success(service):
    """A conversion whose functions carry real bodies stays a success.

    Guards against the fix over-firing: `partial`/`not_applicable` must be
    reserved for genuinely bodyless output, not applied to everything.
    """
    result = await service.convert(IMPLEMENTED_PSEUDOCODE, "pseudocode")
    assert result["status"] == "success", (
        f"an implemented contract was downgraded to {result['status']!r}; "
        f"unimplemented={result.get('unimplemented')!r}"
    )
    assert result["unimplemented"] == []
    # With real logic present the audit renders a real verdict again.
    assert "verdict" not in result["audit"] or result["audit"].get("verdict") != "not_applicable"
