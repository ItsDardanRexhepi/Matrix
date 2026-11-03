"""What the text says the security seam and the decision framework do is what
this tree runs.

Four statements had outlived the code they describe:

  * the inert gate the seam binds when the closed-source security core is not
    installed (runtime/security/__init__.py, `_NoopMorpheus`) said it "Logs
    that it ran so the invocation is observable", and the seam's module
    docstring and runtime/security/SECURITY_INTERFACE.md that under it "every
    action is allowed and logged". Its `evaluate()` returns an allow and logs
    nothing; the seam logs once, at import, that the backend is the no-op;
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

The premises are measured here: what the no-op gate logs when it is asked and
what the seam logs when it is imported, in a fresh interpreter in which the
closed core cannot be imported, read against the three texts in both
directions; and where the framework's gate is called from.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

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


_SAYS_IT_LOGS_EACH_CALL = re.compile(
    r"logs that it ran|invocation is observable"
    r"|logs (?:each|every) (?:call|evaluation|invocation|action)"
    r"|(?:every|each) (?:action|call) is (?:allowed and )?logged"
    r"|allowed and logged")
_SAYS_IT_LOGS_NOTHING_PER_CALL = re.compile(
    r"nothing is logged per (?:action|call)|without logging|logs nothing")
_SAYS_THE_SEAM_LOGS_ONCE_AT_IMPORT = re.compile(r"logs once, at import")


# What the no-op gate logs is measured in a fresh interpreter in which the
# closed core cannot be imported, so the seam binds the no-op whatever this
# process has installed: every record the seam's logger writes while it is
# imported, then every record the platform's loggers write while the gate
# answers one call. The texts are then read against both measurements, in
# both directions: a text may say nothing is logged per call only while
# evaluate() logs nothing, may say the gate logs each call only when it does,
# and may say the seam logs once, at import, only when the import writes
# exactly one record naming the no-op.
_MEASURE_THE_NOOP_GATE = r"""
import asyncio, json, logging, sys
sys.modules["morpheus_security"] = None  # the closed core is not installed
records = []

class _Keep(logging.Handler):
    def emit(self, record):
        records.append([record.name, record.levelname, record.getMessage()])

logging.getLogger().addHandler(_Keep())
logging.getLogger().setLevel(logging.DEBUG)
import runtime.security as seam
at_import = [r for r in records if r[0] == "runtime.security"]
del records[:]
gate = seam.get_morpheus_security()
verdict = asyncio.run(gate.evaluate({"tool": "anything"}, {"agent": "neo"}))
per_call = [r for r in records if r[0].startswith(("runtime", "gateway"))]
print(json.dumps({"backend": seam.SECURITY_BACKEND, "gate": type(gate).__name__,
                  "allow": verdict.get("allow"), "verdict_backend": verdict.get("backend"),
                  "at_import": at_import, "per_call": per_call}))
"""


def _measure_the_noop_gate() -> dict:
    import json
    import os
    import sys
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    out = subprocess.run([sys.executable, "-c", _MEASURE_THE_NOOP_GATE], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


def _noop_gate_texts() -> dict[str, str]:
    """The gate's own docstring, the seam's module docstring and the interface
    document, which all describe the no-op gate, read from source so that the
    no-op branch is read even where the closed core is installed."""
    source = (ROOT / "runtime" / "security" / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    noop = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "_NoopMorpheus")
    return {
        "_NoopMorpheus": ast.get_docstring(noop) or "",
        "runtime/security/__init__.py": ast.get_docstring(tree) or "",
        "runtime/security/SECURITY_INTERFACE.md":
            (ROOT / "runtime" / "security" / "SECURITY_INTERFACE.md").read_text(encoding="utf-8"),
    }


def _statements_the_measurement_contradicts(measured: dict, texts: dict[str, str]) -> list[str]:
    logs_per_call = bool(measured["per_call"])
    noop_records = [r for r in measured["at_import"] if "noop" in r[2].lower()]
    once_at_import = len(noop_records) == 1
    wrong = []
    for where, text in texts.items():
        doc = " ".join(text.split()).lower()
        checks = [
            (_SAYS_IT_LOGS_EACH_CALL, not logs_per_call,
             "the no-op gate logged nothing when asked"),
            (_SAYS_IT_LOGS_NOTHING_PER_CALL, logs_per_call,
             f"the no-op gate logged {measured['per_call']} when asked"),
            (_SAYS_THE_SEAM_LOGS_ONCE_AT_IMPORT, not once_at_import,
             f"importing the seam wrote {measured['at_import']}"),
        ]
        for pattern, contradicted, measured_fact in checks:
            m = pattern.search(doc)
            if m and contradicted:
                wrong.append(f"{measured_fact}, and {where} says: "
                             f"...{doc[max(0, m.start() - 60):m.end() + 30]}...")
    return wrong


def test_the_noop_gate_says_what_it_does_when_it_is_asked():
    measured = _measure_the_noop_gate()
    assert measured["backend"] == "noop" and measured["gate"] == "MorpheusSecurity", measured
    assert measured["allow"] is True and measured["verdict_backend"] == "noop", measured
    texts = _noop_gate_texts()
    # Each text says what the gate does per call and what the seam logs at
    # import; without the statement there is nothing here to read.
    for where, text in texts.items():
        doc = " ".join(text.split()).lower()
        assert (_SAYS_IT_LOGS_EACH_CALL.search(doc) or _SAYS_IT_LOGS_NOTHING_PER_CALL.search(doc)), (
            f"{where} no longer says whether the no-op gate logs a call")
        assert _SAYS_THE_SEAM_LOGS_ONCE_AT_IMPORT.search(doc), (
            f"{where} no longer says what the seam logs at import")
    wrong = _statements_the_measurement_contradicts(measured, texts)
    assert not wrong, "\n".join(wrong)


def test_the_reading_goes_both_ways():
    """Both edits the old check let through are caught: a gate that starts
    logging each call under texts that say it logs nothing, and a seam that
    stops logging at import under texts that say it logs once."""
    texts = _noop_gate_texts()
    quiet_import = [["runtime.security", "WARNING", "Security backend: noop. ..."]]
    logging_gate = {"per_call": [["runtime.security", "INFO", "evaluated"]], "at_import": quiet_import}
    assert len(_statements_the_measurement_contradicts(logging_gate, texts)) == len(texts)
    silent_import = {"per_call": [], "at_import": []}
    assert len(_statements_the_measurement_contradicts(silent_import, texts)) == len(texts)
    assert not _statements_the_measurement_contradicts({"per_call": [], "at_import": quiet_import},
                                                       texts)


def test_the_logging_scan_sees_the_old_sentences():
    for old in ("Logs that it ran so the invocation is observable.",
                "falls back to an inert OBSERVE no-op: every action is allowed and logged, "
                "nothing is enforced.",
                "an inert OBSERVE no-op: every action is allowed and logged, nothing is enforced."):
        assert _SAYS_IT_LOGS_EACH_CALL.search(" ".join(old.split()).lower()), old
    assert not _SAYS_IT_LOGS_EACH_CALL.search(
        "every action is allowed, nothing is enforced, and nothing is logged per action; "
        "the seam logs once, at import, that the backend is the no-op.")
