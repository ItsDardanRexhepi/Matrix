"""The contract auditor decides "is there code here to judge" by reading the
code, in time that grows with the source, and the gate that runs it refuses a
deployment, not a look.

THE DEFECTS (pre-existing on The Matrix ``main``).

1. ``ContractAuditor.has_executable_logic`` scanned to the end of the source
   for every ``function`` token whose braces never balanced, so its cost was
   the square of the source's length: ``"function{" * 10000`` (90 KB) held the
   event loop for about 20 s, on every audit — the convert route a session
   reaches, the ``security_audit`` tool, the Glasswing pre-action gate and the
   badge path. ``implemented_functions`` read the same way.
2. It stripped comments without knowing where a string literal is, so a
   ``"//"`` or ``"/*"`` inside a string erased real code after it (a function
   returning ``"https://x.io"`` read as having no body), and a string that
   spells ``function f() { ... }`` read as a body.
3. The Glasswing gate denied every contract-tool call whose source it could
   not judge, including ``smart_contract`` compile and the read-only
   ``security_audit`` tool, with "fix the vulnerabilities before deploying"
   when there were none: compiling an interface or auditing a Vyper file was
   refused before the tool ran. A source nobody could judge now refuses only a
   call that deploys or signs, with words that say why; for a call that
   deploys nothing the report rides along as context.
"""
from __future__ import annotations

import time

import pytest

from runtime.security.audit import ContractAuditor

INTERFACE = ("pragma solidity 0.8.24;\n"
             "interface IERC20 { function transfer(address,uint256) external returns (bool); }")
CONSTANTS = "pragma solidity 0.8.24;\nlibrary L {\n uint256 internal constant FEE = 30;\n}"
VYPER = "@external\ndef f() -> uint256:\n    return 1\n"
CLEAN = ("pragma solidity 0.8.24;\ncontract C {\n    uint256 public n;\n"
         "    function bump() external { n += 1; }\n}\n")


def _seconds(fn, *args):
    start = time.perf_counter()
    fn(*args)
    return time.perf_counter() - start


@pytest.mark.parametrize("source", [
    "function{" * 6000,                       # braces never balance
    "function{" * 6000 + "}" * 6000,          # balanced, nested
    "function f() " * 6000,                   # no brace and no semicolon at all
])
def test_the_body_reading_is_linear_in_the_source(source):
    """[control] 54 KB: seconds on the previous commit, milliseconds now."""
    for fn in (ContractAuditor.has_executable_logic, ContractAuditor.implemented_functions):
        assert _seconds(fn, source) < 0.5, fn.__name__
    assert _seconds(ContractAuditor().audit, source) < 2.0


def test_a_string_with_comment_marks_does_not_erase_code():
    """[control] A URL in a string read as a comment to the end of the file."""
    src = ('contract C { function u() public pure returns (string memory) '
           '{ return "https://x.io"; } }')
    assert ContractAuditor.has_executable_logic(src) is True
    assert ContractAuditor.implemented_functions(src) == {"u"}
    globbed = ('contract C { string constant P = "contracts/*.sol"; '
               'function f() external { } function g() external { n = 1; } /** @notice */ }')
    assert ContractAuditor.has_executable_logic(globbed) is True
    assert ContractAuditor.implemented_functions(globbed) == {"g"}


@pytest.mark.parametrize("src", [
    'library L { string constant DOC = "function f() { revert(); }"; }',
    "library L { string constant S = 'receive {x}'; }",
    'library L { bytes constant B = hex"00"; string constant E = "say \\"function g() { }\\""; }',
])
def test_a_string_that_spells_a_body_is_not_one(src):
    """[control] Text inside a string literal is not code."""
    assert ContractAuditor.has_executable_logic(src) is False
    assert ContractAuditor.implemented_functions(src) == set()


def test_the_judgements_that_were_right_stay_right():
    """[guard] An interface, a constants library and an empty body are not
    code to judge; a real body is; comments are still not code."""
    assert ContractAuditor.has_executable_logic(INTERFACE) is False
    assert ContractAuditor.has_executable_logic(CONSTANTS) is False
    assert ContractAuditor.has_executable_logic("contract C { function f() external { } }") is False
    assert ContractAuditor.has_executable_logic(CLEAN) is True
    assert ContractAuditor.has_executable_logic(
        "contract C { // function f() { x = 1; }\n /* function g() { y = 2; } */ }") is False
    assert ContractAuditor.implemented_functions(CLEAN) == {"bump"}


def _stack():
    from runtime.protocols.integration import ProtocolStack
    stack = ProtocolStack({}, "neo")
    for name in ("_jarvis", "_ultron", "_friday", "_vision", "_trajectory", "_outcome_learning",
                 "_morpheus_triggers", "_rexhepi_gate"):
        setattr(stack, name, None)
    stack._morpheus_security = None
    stack._morpheus_init_failed = False
    stack._rexhepi_init_failed = False
    stack._auditor = ContractAuditor({})
    return stack


@pytest.mark.parametrize("tool, arguments", [
    ("smart_contract", {"action": "compile", "source_code": INTERFACE}),
    ("smart_contract", {"action": "compile", "source_code": CONSTANTS}),
    ("security_audit", {"source_code": VYPER}),
    ("security_audit", {"source_code": INTERFACE}),
])
async def test_a_look_at_a_source_nobody_can_judge_is_not_refused(tool, arguments):
    """[control] Compile and audit deploy nothing: the report goes with the call."""
    result = await _stack().pre_action(tool, arguments, {})
    assert result["approved"] is True, result.get("denial_reason")
    assert result["audit"]["verdict"] == "not_auditable"


@pytest.mark.parametrize("tool, arguments", [
    ("deploy_contract", {"source_code": INTERFACE}),
    ("smart_contract", {"action": "deploy", "source_code": INTERFACE}),
    ("platform_action", {"action": "deploy_contract", "source_code": CONSTANTS}),
    ("contract_conversion", {"source_code": VYPER}),
])
async def test_a_deployment_of_a_source_nobody_can_judge_is_refused_and_says_why(tool, arguments):
    """[guard, and the words a control] Still refused; no longer told to fix
    vulnerabilities nobody found."""
    result = await _stack().pre_action(tool, arguments, {})
    assert result["approved"] is False
    said = (result["denial_reason"] + " " + result.get("morpheus_message", "")).lower()
    assert "not auditable" in said and "could not be judged" in said, said
    assert "fix the vulnerabilities" not in said


async def test_a_failed_audit_still_refuses_a_compile():
    """[guard] A source with a critical finding is refused on compile as before."""
    critical = ("pragma solidity 0.8.24;\ncontract V {\n    address owner;\n"
                "    function kill() public { selfdestruct(payable(msg.sender)); }\n}\n")
    report = ContractAuditor({}).audit(critical)
    assert report.auditable and not report.passed, "precondition: a critical finding"
    result = await _stack().pre_action("smart_contract", {"action": "compile", "source_code": critical}, {})
    assert result["approved"] is False
    assert "fix the vulnerabilities" in result.get("morpheus_message", "").lower()
