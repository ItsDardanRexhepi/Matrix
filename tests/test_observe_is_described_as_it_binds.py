"""What still binds under OBSERVE is said as it is.

THE DEFECT. The public tree said the security gate's deny binds only under
ENFORCE and that OBSERVE never blocks: ProtocolStack.pre_action's comment
("binding only in ENFORCE mode; OBSERVE logs without blocking"), the
hand-off's docstring (the gate "does not hard-block until human review enables
ENFORCE") and its comment ("(in ENFORCE) can deny"), the seam's interface note
("default OBSERVE — logs, never hard-blocks") and the operator's walkthrough
("OBSERVE: logs, allows"). None of it was true. The seam applies whatever
``allow`` the gate answers, whichever mode the gate reports, and a gate in
OBSERVE still answers a deny for a fault on a call that could move value, and
for App Attest when it is enforced. A gate that faults in the seam's own hands
is refused the same way, whatever its mode.

THE RULE. Under OBSERVE a verdict's deny is not applied; a fault on a call
that could move value and App Attest, when it is enforced, still deny, and the
seam applies every deny it is handed. The public tree says so, and nowhere
that a deny binds only under ENFORCE.

CHECKS
  (a) no tracked file outside tests/ says a deny binds only under ENFORCE, or
      that OBSERVE never blocks                                (the control)
  (b) the seam's interface note says which denies still bind under OBSERVE
  (c) PINS: the pre-action check, the hand-off and the HTTP gate each apply a
      deny from a gate that reports OBSERVE, and each refuses a call that
      could move value when such a gate faults; a plain read still proceeds
      after a fault at the pre-action check and the HTTP gate (scope pin)

§CC, measured against the tree at the commit "A measurement a test records names
the commit it was measured against by subject", with this file added: 2 failed
and 7 passed. (a) failed naming CREDENTIALS_NEEDED.md, runtime/agents/handoff.py
twice, runtime/protocols/integration.py twice and
runtime/security/SECURITY_INTERFACE.md; (b) failed because the interface note
said OBSERVE never blocks. The seven pins passed: the seam already behaved as
the corrected text says, and only the text was wrong. After the change, 9
passed.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

import runtime.security as seam

ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {".py", ".md", ".txt", ".rst", ".yml", ".yaml", ".toml", ".cfg", ".ini",
                 ".sh", ".example", ""}

#: Ways of saying that only ENFORCE binds, or that OBSERVE never blocks, each
#: as the public tree had it. Matched case-insensitively on the text with
#: comment markers and line breaks folded away.
ONLY_ENFORCE_BINDS = (
    r"binding only in enforce",
    r"only binding when mode ?== ?enforce",
    r"observe logs without blocking",
    r"never hard-blocks?",
    r"does not hard-block",
    r"\(in enforce\) can deny",
    r"observe: logs, allows",
)
_ONLY_ENFORCE = re.compile("|".join(ONLY_ENFORCE_BINDS), re.IGNORECASE)


def _tracked_text_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                             check=True, timeout=60).stdout.decode("utf-8", "replace")
        paths = [ROOT / p for p in out.split("\0") if p]
    except (OSError, subprocess.SubprocessError):
        paths = [p for p in ROOT.rglob("*") if ".git" not in p.parts]
    return [p for p in paths
            if p.is_file() and p.suffix in TEXT_SUFFIXES
            and p.relative_to(ROOT).parts[0] != "tests"]


def _folded(text: str) -> str:
    """*text* with each line's comment marker dropped and every run of
    whitespace, line breaks included, made one space."""
    lines = (re.sub(r"^\s*(?:#+|//+|\*)\s?", "", line) for line in text.splitlines())
    return " ".join(" ".join(lines).split())


def test_nothing_says_a_deny_binds_only_under_enforce():
    """(a) THE CONTROL."""
    said = []
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        said += [f"{path.relative_to(ROOT)}: {m.group(0)!r}"
                 for m in _ONLY_ENFORCE.finditer(_folded(text))]
    assert not said, f"the public tree says a deny binds only under ENFORCE: {sorted(said)}"


def test_the_interface_note_says_which_denies_still_bind_under_observe():
    """(b)"""
    note = _folded((ROOT / "runtime" / "security" / "SECURITY_INTERFACE.md").read_text(
        encoding="utf-8"))
    assert re.search(r"OBSERVE[^.]*a verdict's deny is not applied", note), note
    assert re.search(r"a fault on a call that could move value[^.]*App Attest, when it is "
                     r"enforced, still deny", note), note


# ── (c) PINS: what the corrected text says, driven ───────────────────────────

class _ObserveGate:
    """A gate that reports OBSERVE and answers the decision it is given, or
    raises when it is given none."""

    mode = seam.MorpheusMode.OBSERVE

    def __init__(self, decision: dict | None):
        self.decision = decision

    async def evaluate(self, action, context):
        if self.decision is None:
            raise RuntimeError("gate fault")
        return dict(self.decision)


#: A deny the gate reached under OBSERVE (a fault's, or App Attest's).
DENY = {"allow": False, "would_block": True, "mode": "observe", "route": "fail-closed",
        "reason": "denied under observe"}
SWAP = ("platform_action", {"action": "swap"})
READ = ("stablecoin", {"action": "balance", "address": "0x" + "cd" * 20})
CTX = {"wallet": "0x" + "ab" * 20}


def _stack(gate: _ObserveGate):
    from runtime.protocols.integration import ProtocolStack

    stack = ProtocolStack({"agents": {}, "security": {}}, "neo")
    stack._morpheus_security = gate
    stack._morpheus_init_failed = False
    stack._rexhepi_gate = None
    return stack


async def test_the_pre_action_check_applies_a_deny_from_a_gate_in_observe():
    result = await _stack(_ObserveGate(DENY)).pre_action(*SWAP, CTX)
    assert result["approved"] is False, result


async def test_the_pre_action_check_refuses_a_value_moving_call_when_a_gate_in_observe_faults():
    stack = _stack(_ObserveGate(None))
    assert (await stack.pre_action(*SWAP, CTX))["approved"] is False
    assert (await stack.pre_action(*READ, CTX))["approved"] is True, "scope pin: a read proceeds"


async def test_the_hand_off_applies_a_deny_from_a_gate_in_observe(monkeypatch):
    from runtime.agents.handoff import AgentHandoff

    monkeypatch.setattr(seam, "get_morpheus_security", lambda *a, **k: _ObserveGate(DENY))
    out = json.loads(await AgentHandoff({}, None).as_tool("swap", {}))
    assert out["approved"] is False, out


async def test_the_hand_off_refuses_when_a_gate_in_observe_faults(monkeypatch):
    from runtime.agents.handoff import AgentHandoff

    monkeypatch.setattr(seam, "get_morpheus_security", lambda *a, **k: _ObserveGate(None))
    out = json.loads(await AgentHandoff({}, None).as_tool("swap", {}))
    assert out["approved"] is False, out


async def test_the_http_gate_applies_a_deny_from_a_gate_in_observe(monkeypatch):
    from gateway.security_gate import gate_action, is_blocked

    monkeypatch.setattr(seam, "get_morpheus_security", lambda *a, **k: _ObserveGate(DENY))
    assert is_blocked(await gate_action("swap", {}, context=CTX))


async def test_the_http_gate_refuses_a_value_moving_call_when_a_gate_in_observe_faults(monkeypatch):
    from gateway.security_gate import gate_action, is_blocked

    monkeypatch.setattr(seam, "get_morpheus_security", lambda *a, **k: _ObserveGate(None))
    assert is_blocked(await gate_action("swap", {}, context=CTX))
    assert not is_blocked(await gate_action("get_balance", {}, context=CTX)), (
        "scope pin: a read proceeds")


def test_the_pins_drive_a_gate_that_reports_observe():
    """The pins above say nothing unless their gate is in OBSERVE."""
    assert _ObserveGate(DENY).mode == seam.MorpheusMode.OBSERVE
    assert _ObserveGate(DENY).mode != seam.MorpheusMode.ENFORCE
