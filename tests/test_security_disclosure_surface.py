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
    r"\bno enforcement\b|nothing enforced", re.I)
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
