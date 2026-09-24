"""What the text says the security seam and the decision framework do is what
this tree runs.

Three statements had outlived the code they describe:

  * the inert gate the seam binds when the closed-source security core is not
    installed (runtime/security/__init__.py, `_NoopMorpheus`) said it "Logs
    that it ran so the invocation is observable". Its `evaluate()` returns an
    allow and logs nothing; the seam logs once, at import, that the backend is
    the no-op;
  * Neo's system prompt and docs/agents.md said a closed-source access
    protection protocol "governs all interactions with Neo". That protocol is
    part of the closed core, so it governs nothing in a deployment that does
    not install it, and a clone of this repository does not;
  * course 01 said "Nothing irreversible executes without your explicit
    approval through Morpheus". The Morpheus trigger in the pre-action stack
    adds a message to the step and stops nothing (docs/agents.md: "Morpheus
    does not block — he informs");
  * docs/what-makes-the-matrix-different.md said every decision of every agent
    passes through the Unified Rexhepi Framework, that it "cannot be bypassed",
    and that every agent response is evaluated. The framework's gate runs on
    the tool calls the reasoning loop dispatches (ProtocolStack.pre_action),
    it is this repository's own code, which a fork can change or remove, and
    docs/unified-rexhepi-framework.md says exactly that.

The premises are measured here: the backend this clone binds, what the no-op
gate logs when it is asked, and where the framework's gate is called from.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import logging
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_NOT_READ = {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}
_OVERCLAIMS = [
    r"can(?:no|')t be bypassed",
    r"governs all (?:interactions|attempts|agent behaviou?r|behaviou?r|decisions)",
    r"governed entirely by",
    r"every agent response is evaluated",
    r"every decision made by every agent passes through",
    r"nothing irreversible executes without",
    # Morpheus as a confirmation step (courses 02 and 03, the agents' prompts,
    # the README and docs/blockchain.md): his note reaches the user with the
    # tool's result, and nothing waits for an answer to it.
    r"\[?morpheus confirms the (?:transaction|deployment)",
    r"through morpheus before approving",
    r"morpheus (?:will )?appears? for confirmation",
    r"morpheus (?:handles|presents)[^.]{0,60}\bconfirmation",
    r"user confirms\. then it executes",
    r"(?:clearly and|then) waits\b",
    r"waits for the user to fix",
    r"nothing below the confirmation",
    r"morpheus explains what's happening first",
]


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).lower()


def test_the_overclaim_scan_catches_the_old_copy():
    old = ("Nothing irreversible executes without your explicit approval through Morpheus. "
           "A multi-layer access protection protocol governs all interactions with Neo. "
           "It governs all attempts to reach Neo. Governed entirely by the Unified Rexhepi "
           "Framework. Every decision made by every agent passes through the Unified Rexhepi "
           "Framework before execution. This is not optional. It cannot be bypassed. Every "
           "agent response is evaluated consistently. [Morpheus confirms the transaction] "
           "[Morpheus confirms the deployment] Each signer sees the exact transaction details "
           "through Morpheus before approving. Morpheus will appear for confirmation before the "
           "deposit. Morpheus presents the deployment details for confirmation. User confirms. Then "
           "it executes. He tells the truth clearly and waits. Morpheus explains what was found and "
           "waits for the user to fix the code. Nothing below the confirmation happens yet. If it's "
           "a first-time use, Morpheus explains what's happening first.")
    hits = {p for p in _OVERCLAIMS if re.search(p, _flat(old))}
    assert hits == set(_OVERCLAIMS), set(_OVERCLAIMS) - hits
    assert not [p for p in _OVERCLAIMS
                if re.search(p, _flat("Every tool call passes through the framework; a fork "
                                      "can change it or take it out. If Morpheus has a note for "
                                      "this action, it arrives with the result. Nothing waits for "
                                      "an answer to it."))]


def _framework_gate_callers() -> set[str]:
    """Modules outside rexhepi_gate.py that construct the framework's gate."""
    callers = set()
    for path in sorted((ROOT / "runtime").rglob("*.py")) + sorted((ROOT / "gateway").rglob("*.py")):
        rel = str(path.relative_to(ROOT))
        if rel == "runtime/protocols/rexhepi_gate.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "RexhepiGate":
                callers.add(rel)
    return callers


def _morpheus_trigger_branch_only_adds_a_message() -> bool:
    """In ProtocolStack.pre_action (its body is _pre_action), the Morpheus trigger branch sets
    result["morpheus_message"] and nothing that stops the call."""
    tree = ast.parse((ROOT / "runtime" / "protocols" / "integration.py").read_text(encoding="utf-8"))
    stages = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
              and n.name in ("pre_action", "_pre_action")]
    branches = [n for stage in stages for n in ast.walk(stage) if isinstance(n, ast.If)
                and "_morpheus_triggers" in ast.unparse(n.test)]
    if not branches:
        return False
    body = "\n".join(ast.unparse(b) for b in branches)
    stops = [n for b in branches for n in ast.walk(b) if isinstance(n, (ast.Return, ast.Raise))]
    return "morpheus_message" in body and not stops and "allowed" not in body


def _seam_binds_the_noop_gate() -> bool:
    """The gate this process gets is the seam's inert no-op. Read from the
    gate, not from SECURITY_BACKEND: tests/conftest.py pins that label to
    "noop" for every test, so where the closed core is importable the label
    says noop while the seam hands out the real gate."""
    import runtime.security as seam
    noop = getattr(seam, "_NoopMorpheus", None)
    return noop is not None and isinstance(seam.get_morpheus_security(), noop)


def test_the_premise_reads_the_gate_not_the_label(monkeypatch):
    import runtime.security as seam

    class _RealGate:
        async def evaluate(self, *_a, **_k):
            return {"allow": True, "backend": "morpheus_security"}

    monkeypatch.setattr(seam, "SECURITY_BACKEND", "noop")
    monkeypatch.setattr(seam, "get_morpheus_security", lambda config=None: _RealGate())
    assert not _seam_binds_the_noop_gate()


def test_no_public_text_says_a_layer_governs_everything_or_cannot_be_bypassed():
    assert _morpheus_trigger_branch_only_adds_a_message(), (
        "the Morpheus trigger can stop a call now; re-derive this check")

    # The measured premise: the framework's gate is built only by the tool-call
    # pre-action stack (and by Omega, which nothing calls). The text is read
    # whichever gate this process binds: a clone of this repository does not
    # have the closed core, and the text is written for that clone. (This
    # asserted SECURITY_BACKEND == "noop", which tests/conftest.py pins for
    # every test, so it could not fail.)
    assert _framework_gate_callers() <= {"runtime/protocols/integration.py",
                                         "runtime/protocols/omega.py"}, (
        f"the framework's gate is built elsewhere now: {_framework_gate_callers()}")

    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        flat = _flat((ROOT / rel).read_text(encoding="utf-8"))
        for pattern in _OVERCLAIMS:
            for m in re.finditer(pattern, flat):
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 60):m.end() + 30]}...")
    assert not offenders, "\n".join(offenders)


def test_the_noop_gate_says_what_it_does_when_it_is_asked(caplog):
    import runtime.security as seam

    if not _seam_binds_the_noop_gate():
        pytest.skip("the closed security core is installed; there is no no-op gate here")
    gate = seam.get_morpheus_security()
    caplog.set_level(logging.DEBUG)
    caplog.clear()
    verdict = asyncio.run(gate.evaluate({"tool": "anything"}, {"agent": "neo"}))
    assert verdict["allow"] is True and verdict["backend"] == "noop"
    # The platform's own loggers only: asyncio.run logs its selector at DEBUG.
    logged = [r for r in caplog.records if r.name.startswith(("runtime", "gateway"))]
    doc = " ".join((inspect.getdoc(type(gate)) or "").split()).lower()
    if not logged:
        assert not re.search(r"logs that it ran|invocation is observable|"
                             r"logs (?:each|every) (?:call|evaluation|invocation)", doc), (
            f"the no-op gate logged nothing when asked, and its docstring says: {doc!r}")
