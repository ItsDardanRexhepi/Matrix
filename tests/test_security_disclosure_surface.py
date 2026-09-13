"""The vulnerability-disclosure surface: reachable, in scope, and honest.

Three properties, each derived from something other than the prose it judges.

1. REACHABLE. The reporting channel is whatever `.github/SECURITY.md` says it is
   (parsed from that file, not restated here). The two documents a contributor
   actually opens — README.md and CONTRIBUTING.md — must each lead to it: a link
   that RESOLVES to that file, or the channel itself. The README's only security
   pointer used to route to the closed-source architecture stub instead.

2. IN SCOPE. The policy declared "the closed-source security layer ... out of
   scope for public disclosure" — the very component SECURITY_STUB.md says does
   the enforcing. A reporter holding a bypass of boundary enforcement was told
   not to send it. The layer's name is read from SECURITY_STUB.md's own title,
   so renaming the stub does not quietly re-open the exclusion.

3. HONEST ABOUT THE DEFAULT, IN BOTH DIRECTIONS. What the seam does without
   the private package is measured, not assumed, and each measured fact rules
   out the statement it contradicts:
     * the gate is asked to evaluate a value-moving action; if it allows it, the
       statements may not say the layer "cannot be bypassed" or "governs all
       agent behavior" and must name OBSERVE;
     * the seam's per-agent boundary is asked whether Trinity may run `bash`;
       if it refuses, the statements may not say a clone "enforces nothing"
       (that understated the public boundary the dispatcher applies on every
       tool call) and must name the per-agent boundary;
     * the no-op gate's evaluate is run under a log capture; if it emits
       nothing, the statements may not say the no-op "logs" every action;
     * `ProtocolStack.pre_action`'s source is read; if a seam-level refusal is
       reached before the gate is evaluated, the statements may not say the
       gate is consulted "first".
   When the private package IS installed the measurements differ, and each
   check stands down on its own measurement rather than on the backend name.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / ".github" / "SECURITY.md"
STUB = ROOT / "SECURITY_STUB.md"


def _section(text: str, heading: str) -> str:
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def _reporting_channel() -> str:
    reporting = _section(POLICY.read_text(encoding="utf-8"), "Reporting a Vulnerability")
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", reporting)
    assert m, "the policy's Reporting section names no address"
    return m.group(0)


def _leads_to_policy(doc: Path) -> bool:
    text = doc.read_text(encoding="utf-8")
    if _reporting_channel() in text:
        return True
    targets = re.findall(r"\]\(([^)\s#]+)", text) + re.findall(r"`([^`\s]+SECURITY\.md)`", text)
    for target in targets:
        resolved = (doc.parent / target).resolve()
        if resolved == POLICY.resolve():
            return True
    return False


def test_readme_leads_a_reporter_to_the_disclosure_channel():
    assert _leads_to_policy(ROOT / "README.md")


def test_contributing_leads_a_reporter_to_the_disclosure_channel():
    assert _leads_to_policy(ROOT / "CONTRIBUTING.md")


def test_policy_does_not_exclude_the_enforcing_layer_from_scope():
    title = STUB.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip().lower()
    assert title, "SECURITY_STUB.md has no title to name the layer by"
    scope = _section(POLICY.read_text(encoding="utf-8"), "Scope")
    assert scope.strip(), "the policy has no Scope section"
    for sentence in re.split(r"(?<=[.!?])\s+", scope):
        s = sentence.lower()
        if "out of scope" in s or "not in scope" in s:
            assert title not in s and "closed-source" not in s and "closed source" not in s, (
                f"the policy excludes the enforcing layer from disclosure: {sentence.strip()!r}")


def _default_gate_allows_value_movement() -> bool:
    from runtime.security import get_morpheus_security, SECURITY_BACKEND
    if SECURITY_BACKEND != "noop":
        return False
    decision = asyncio.run(get_morpheus_security().evaluate(
        {"type": "transfer", "value_moving": True}, {"agent": "trinity"}))
    return bool(decision.get("allow"))


def test_public_security_statements_name_the_observe_default():
    if not _default_gate_allows_value_movement():
        return  # a real backend is installed here; the measured default differs
    statements = {
        "SECURITY_STUB.md": STUB.read_text(encoding="utf-8"),
        "README.md#security": _section((ROOT / "README.md").read_text(encoding="utf-8"),
                                       "The Security Layer"),
    }
    for where, text in statements.items():
        low = text.lower()
        assert "cannot be bypassed" not in low, where
        assert "governs all agent behavior" not in low, where
        assert "observe" in low, f"{where} does not say the default enforces nothing"


# Every document or module docstring that tells a reader what the security seam
# does. Checked as whole files: a statement about the default is just as wrong
# in a code comment an operator reads as in the README.
_STATEMENT_FILES = [
    "SECURITY_STUB.md", "README.md", ".github/SECURITY.md", "CONTRIBUTING.md",
    "CREDENTIALS_NEEDED.md", "runtime/security/SECURITY_INTERFACE.md",
    "runtime/security/__init__.py", "gateway/security_gate.py",
    "runtime/protocols/integration.py", "gateway/server.py", "gateway/doctor.py",
]

_ENFORCES_NOTHING = re.compile(
    r"enforces nothing|nothing (?:listed above )?is enforced|"
    r"\bno enforcement\b|nothing (?:is )?enforc(?:ed|ing)", re.I)
_NOOP_LOGS = re.compile(r"allowed and logged|allows and logs|logs every action", re.I)
_GATE_FIRST = re.compile(r"first in\s+`?ProtocolStack\.pre_action|consulted\s+\*{0,2}first|"
                         r"runs first, so every execution path", re.I)


def _statement_lines(pattern: re.Pattern) -> list[str]:
    hits = []
    for rel in _STATEMENT_FILES:
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        # join wrapped lines so a phrase broken by a newline is still one phrase
        flat = re.sub(r"\s*\n\s*(?:#\s*)?", " ", text)
        for m in pattern.finditer(flat):
            hits.append(f"{rel}: ...{flat[max(0, m.start() - 60):m.end() + 20]}...")
    return hits


def _noop_boundary_refuses_trinity_bash() -> bool:
    from runtime.security import agent_access_allowed, SECURITY_BACKEND
    if SECURITY_BACKEND != "noop":
        return False
    allowed, _ = agent_access_allowed("trinity", "bash")
    return not allowed


def test_public_statements_do_not_say_a_clone_enforces_nothing():
    if not _noop_boundary_refuses_trinity_bash():
        return  # the measured boundary does not refuse; the claim is not contradicted
    hits = _statement_lines(_ENFORCES_NOTHING)
    assert not hits, (
        "without the private package the seam still refuses Trinity `bash` (the public "
        "per-agent boundary), so these statements are false:\n" + "\n".join(hits))
    stub = STUB.read_text(encoding="utf-8").lower()
    readme = _section((ROOT / "README.md").read_text(encoding="utf-8"),
                      "The Security Layer").lower()
    for where, text in (("SECURITY_STUB.md", stub), ("README.md#security", readme)):
        assert "per-agent" in text, f"{where} does not name the boundary that still applies"


def test_public_statements_do_not_say_the_noop_gate_logs_every_action():
    from runtime.security import get_morpheus_security, SECURITY_BACKEND
    if SECURITY_BACKEND != "noop":
        return
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            # only the security code's own loggers: asyncio logs its selector
            if record.name.startswith(("runtime", "gateway", "morpheus")):
                records.append(record)

    handler = _Capture(level=logging.DEBUG)
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        asyncio.run(get_morpheus_security().evaluate(
            {"type": "transfer", "value_moving": True}, {"agent": "trinity"}))
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    if records:
        return  # it does log; the statement is not contradicted
    hits = _statement_lines(_NOOP_LOGS)
    assert not hits, "the no-op gate emits no log record, so these statements are false:\n" + "\n".join(hits)


def test_public_statements_do_not_say_the_gate_is_consulted_first():
    from runtime.protocols.integration import ProtocolStack
    source = inspect.getsource(ProtocolStack.pre_action)
    refusal = source.find("beneficiary_violation(")
    gate = source.find(".evaluate(action, context)")
    assert gate != -1, "pre_action no longer evaluates the gate; re-derive this check"
    if refusal == -1 or refusal > gate:
        return  # nothing refuses before the gate; "first" is not contradicted
    hits = _statement_lines(_GATE_FIRST)
    assert not hits, (
        "pre_action reaches seam-level refusals before it evaluates the gate, so these "
        "statements are false:\n" + "\n".join(hits))


# ── 4. COMPLETE ABOUT WHAT STILL REFUSES ────────────────────────────────────
#
# The phrase checks above rule out statements that UNDERSTATE by a known
# phrase. They could not catch an "only X applies" list that leaves checks
# out: the startup warning said "only the public per-agent tool boundary
# applies" while pre_action also refused through the seam-level refusals, the
# Rexhepi (URF) gate and the Glasswing audit block, and owner verification and
# OTP failed closed. So the set of public components that can refuse is derived
# from code, and every statement of what runs without the private package must
# name each one.
#
# Refusing components of pre_action are found by reading its source: every
# top-level statement that sets result["approved"] = False is attributed to a
# component by a marker in that statement. A refusal no marker explains fails
# the test, so a new refusing check cannot be added without the statements
# being brought up to date.

_REFUSAL_MARKERS = [
    ("beneficiary_violation(", "seam-level refusals"),
    ("_morpheus_init_failed", "morpheus gate"),
    ("_morpheus_security.evaluate(", "morpheus gate"),
    ("_rexhepi_gate", "rexhepi gate"),
    ("_auditor", "glasswing audit block"),
]

# How a statement names each component (lower-cased text).
_COMPONENT_NAMES = {
    "seam-level refusals": r"seam-level",
    "morpheus gate": r"no-op|\bnoop\b|blocks nothing",
    "rexhepi gate": r"rexhepi",
    "glasswing audit block": r"glasswing",
    "per-agent tool boundary": r"per-agent",
    "fail-closed owner verification": r"owner",
    "fail-closed otp": r"\botp\b",
}

_CLOSED_LIST = re.compile(r"only the public (?:per-agent|checks)[^.]*\bappl(?:y|ies)\b", re.I)


def _pre_action_refusing_components() -> set[str]:
    import ast
    import textwrap
    from runtime.protocols.integration import ProtocolStack

    source = textwrap.dedent(inspect.getsource(ProtocolStack.pre_action))
    func = ast.parse(source).body[0]
    found: set[str] = set()
    unexplained: list[str] = []
    for stmt in func.body:
        refuses = any(
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                    and t.slice.value == "approved" for t in node.targets)
            and isinstance(node.value, ast.Constant) and node.value.value is False
            for node in ast.walk(stmt))
        if not refuses:
            continue
        segment = ast.get_source_segment(source, stmt) or ""
        names = [name for marker, name in _REFUSAL_MARKERS if marker in segment]
        if not names:
            unexplained.append(segment.splitlines()[0])
        found.update(names[:1])
    assert not unexplained, (
        "pre_action refuses in a statement no marker explains; add the component to "
        "_REFUSAL_MARKERS and to every statement of what still applies: "
        + "; ".join(unexplained))
    return found


def _measured_refusers_without_the_package() -> set[str]:
    """Components measured to refuse on this checkout's noop backend."""
    from runtime.protocols.integration import ProtocolStack
    from runtime.security import OTPService, OwnerVerification, SECURITY_BACKEND
    if SECURITY_BACKEND != "noop":
        return set()
    measured: set[str] = set()
    if _noop_boundary_refuses_trinity_bash():
        measured.add("per-agent tool boundary")
    if not asyncio.run(OwnerVerification().authorize_owner_action()).get("authorized"):
        measured.add("fail-closed owner verification")
    if not asyncio.run(OTPService().verify()).get("verified"):
        measured.add("fail-closed otp")

    stack = ProtocolStack({}, "neo")

    async def run(tool, args, ctx):
        return await stack.pre_action(tool, args, ctx)

    urf = asyncio.run(run("platform_action",
                          {"action": "transfer_stablecoin", "amount": 1e9, "to": "0xdead"}, {}))
    if not urf["approved"] and str(urf["denial_reason"]).startswith("[URF"):
        measured.add("rexhepi gate")
    vulnerable = ("pragma solidity ^0.8.0; contract A { mapping(address=>uint) b; "
                  "function w() public { msg.sender.call{value: 1}(\"\"); b[msg.sender] = 0; } "
                  "function k() public { selfdestruct(payable(msg.sender)); } }")
    gw = asyncio.run(run("smart_contract", {"action": "deploy", "source_code": vulnerable,
                                            "contract_name": "A"},
                         {"wallet": "0x" + "1" * 40}))
    if not gw["approved"] and "Glasswing" in str(gw["denial_reason"]):
        measured.add("glasswing audit block")
    return measured


def _noop_warning_text() -> str:
    import ast
    source = (ROOT / "runtime" / "security" / "__init__.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "warning"
                and node.args and isinstance(node.args[0], ast.Constant)
                and "Security backend: noop" in str(node.args[0].value)):
            return str(node.args[0].value)
    raise AssertionError("the noop startup warning was not found; re-derive this check")


def _what_still_applies_statements() -> dict[str, str]:
    import ast
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    creds = (ROOT / "CREDENTIALS_NEEDED.md").read_text(encoding="utf-8")
    seam = (ROOT / "runtime" / "security" / "__init__.py").read_text(encoding="utf-8")
    statements = {
        "runtime/security/__init__.py startup warning": _noop_warning_text(),
        "runtime/security/__init__.py docstring": ast.get_docstring(ast.parse(seam)) or "",
        "README.md#The Security Layer": _section(readme, "The Security Layer"),
        "SECURITY_STUB.md#What is true today": _section(
            STUB.read_text(encoding="utf-8"), "What is true today"),
        ".github/SECURITY.md#Scope": _section(POLICY.read_text(encoding="utf-8"), "Scope"),
        "runtime/security/SECURITY_INTERFACE.md#Two backends": _section(
            (ROOT / "runtime" / "security" / "SECURITY_INTERFACE.md").read_text(encoding="utf-8"),
            "Two backends"),
        "CREDENTIALS_NEEDED.md noop row": "\n".join(
            line for line in creds.splitlines() if "SECURITY_BACKEND=noop" in line),
    }
    for where, text in statements.items():
        assert text.strip(), f"{where} is empty; re-derive this check"
    return statements


def _missing_components(text: str, required: set[str]) -> list[str]:
    low = text.lower()
    return sorted(c for c in required if not re.search(_COMPONENT_NAMES[c], low))


def test_the_completeness_check_catches_the_old_closed_list():
    """Planted positive: the warning as it read before this check names one of
    the components that refuse, and fails; the closed-list phrase is caught."""
    old = ("Security backend: noop. The private morpheus_security package is not "
           "installed; the Morpheus gate is an OBSERVE no-op (it blocks nothing) and "
           "only the public per-agent tool boundary applies.")
    required = set(_COMPONENT_NAMES)
    assert _missing_components(old, required) == sorted(
        required - {"morpheus gate", "per-agent tool boundary"})
    assert _CLOSED_LIST.search(old)


def test_every_statement_of_what_runs_without_the_package_names_every_refusing_check():
    measured = _measured_refusers_without_the_package()
    if not measured:
        return  # a real backend is installed here; the measured default differs
    required = _pre_action_refusing_components() | measured
    # The measurements must agree with the source reading: a check the source
    # says can refuse but that did not refuse here would mean a stale marker.
    for component in ("rexhepi gate", "glasswing audit block"):
        assert component in _pre_action_refusing_components(), component
        assert component in measured, f"{component} did not refuse on the noop backend"
    offenders = []
    for where, text in _what_still_applies_statements().items():
        missing = _missing_components(text, required)
        if missing:
            offenders.append(f"{where} leaves out: {', '.join(missing)}")
        if _CLOSED_LIST.search(text):
            offenders.append(f"{where} presents a closed list: "
                             f"{_CLOSED_LIST.search(text).group(0)!r}")
    assert not offenders, "\n".join(offenders)


# ── 5. HONEST ABOUT WHICH WAY A FAULT FAILS ────────────────────────────────
#
# SECURITY_STUB.md said of the URF gate "a fault inside the gate is logged and
# the action continues". Measured, a fault fails in two directions: an
# exception inside one of the gate's checks is recorded as a failed check and
# REFUSES the action (RexhepiGate.evaluate), and only an exception escaping the
# gate as a whole is logged by ProtocolStack.pre_action and lets the action
# continue. Both are measured here on the noop backend, and each rules out the
# statement it contradicts.

_GATE_FAULT_CONTINUES = re.compile(
    r"fault (?:inside|in) the (?:urf |rexhepi )?gate is logged and the action continues", re.I)


def _gate_fault_directions() -> tuple[bool, bool]:
    """(a fault in a gate check refuses, a fault escaping the gate continues)."""
    from runtime.protocols.integration import ProtocolStack
    from runtime.protocols.rexhepi_gate import RexhepiGate
    from runtime.security import SECURITY_BACKEND
    if SECURITY_BACKEND != "noop":
        return False, False

    def _raise(*_a, **_k):
        raise RuntimeError("planted fault")

    action = ("platform_action", {"action": "get_stablecoin_balance", "address": "0x" + "1" * 40}, {})
    baseline = asyncio.run(ProtocolStack({}, "neo").pre_action(*action))
    original_check = RexhepiGate._check_safety
    RexhepiGate._check_safety = _raise
    try:
        check_fault = asyncio.run(ProtocolStack({}, "neo").pre_action(*action))
    finally:
        RexhepiGate._check_safety = original_check
    original_eval = RexhepiGate.evaluate

    async def _raise_async(*_a, **_k):
        raise RuntimeError("planted fault")

    RexhepiGate.evaluate = _raise_async
    try:
        escaped = asyncio.run(ProtocolStack({}, "neo").pre_action(*action))
    finally:
        RexhepiGate.evaluate = original_eval
    assert baseline["approved"], ("the probe action is refused without a fault; pick one "
                                  "the gate approves", baseline)
    check_refuses = (not check_fault["approved"]
                     and "Internal error in safety check" in str(check_fault["denial_reason"]))
    return check_refuses, bool(escaped["approved"])


def test_the_fault_sentence_scan_catches_the_old_stub_sentence():
    old = ("an action proceeds only when every check passes; a fault inside the gate is "
           "logged and the action continues (`runtime/protocols/rexhepi_gate.py`)")
    assert _GATE_FAULT_CONTINUES.search(old)


def test_statements_say_which_way_a_gate_fault_fails():
    check_refuses, escape_continues = _gate_fault_directions()
    if check_refuses:
        hits = _statement_lines(_GATE_FAULT_CONTINUES)
        assert not hits, (
            "a fault inside a URF gate check refuses the action, so a statement that a "
            "fault inside the gate lets it continue is false:\n" + "\n".join(hits))
    today = _section(STUB.read_text(encoding="utf-8"), "What is true today")
    urf = next((ln for ln in today.splitlines() if "rexhepi" in ln.lower()), "")
    assert urf, "SECURITY_STUB.md no longer describes the Rexhepi gate; re-derive this check"
    if check_refuses:
        assert re.search(r"fault in (?:one of|any of)[^.;]*checks?[^.;]*refus", urf, re.I), (
            "the stub does not say a fault in a gate check refuses the action", urf)
    if escape_continues:
        assert "runtime/protocols/integration.py" in urf and re.search(
            r"escap[^.;]*continue", urf, re.I), (
            "the stub does not say that a fault escaping the gate lets the action continue, "
            "or does not cite where that happens", urf)
