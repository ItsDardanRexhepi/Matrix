"""What a fault on one call does is said for each mode, and for where it is caught.

THE DEFECT. Three public places said that a security gate which came up and
then faults on a single call refuses that call when it could move value and
lets a plain read through: the README's production bullet, the core section of
CREDENTIALS_NEEDED.md and the seam's interface note. That holds in two cases
only: when the gate raises instead of answering, so the seam's own fail
direction decides (gateway/security_gate.py, runtime/protocols/integration.py),
and when the installed core, meeting the fault itself, is in OBSERVE. Under
ENFORCE the installed core answers a call it could not decide with a refusal,
reads included, and the seam applies it: with the core in ENFORCE and a fault
on a balance read, the HTTP gate and the pre-action check both refused it.
Nothing in the three places said so.

THE RULE. A public sentence that says a faulting gate lets a plain read
through names the case it holds for: OBSERVE, or a gate that raises instead
of answering. A file that says it also says that under ENFORCE such a fault
refuses the call, reads included.

CHECKS
  (a) every tracked sentence outside tests/ that says a faulting gate lets a
      plain read through is qualified by mode or by the gate raising
                                                               (the control)
  (b) every tracked file outside tests/ with such a sentence also says that
      under ENFORCE a fault refuses the call, reads included    (the control)
  (c) PIN, the seam's own catch: a gate that reports ENFORCE and raises
      instead of answering has a call that could move value refused and a
      plain read let through, at the HTTP gate and at the pre-action check
  (d) JOINT PIN, with the security core installed: the core's gate in
      ENFORCE, faulting on a balance read, has it refused at the HTTP gate and
      at the pre-action check, while the same read by a caller it can read is
      allowed; in OBSERVE the faulted read goes through and a swap faulted the
      same way is refused. Skipped on the no-op backend.

§CC, measured against the tree at the commit "Under OBSERVE a fault denies for
a call that could change state, not only one that could move value", with
this file added: (a) failed naming README.md, CREDENTIALS_NEEDED.md and
runtime/security/SECURITY_INTERFACE.md, one sentence each; (b) failed naming
the same three files; (c) passed, and (d) passed with the core installed and
was skipped on the no-op backend, since the seam and the core already behaved
as the corrected text says and only the text was wrong. After the change, all
pass.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

import runtime.security as seam

ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {".py", ".md", ".txt", ".rst", ".yml", ".yaml", ".toml", ".cfg", ".ini",
                 ".sh", ".example", ""}

#: A sentence that says a faulting gate lets a plain read through.
_READ_THROUGH = re.compile(r"plain read (?:goes |go )?(?:through|proceeds?)", re.IGNORECASE)
#: What qualifies it: the mode it holds in, or the gate raising instead of
#: answering (the seam's own fail direction, in either mode).
_QUALIFIED = re.compile(r"\bOBSERVE\b|raises instead of answering")
#: The case the three places left out.
_ENFORCE_REFUSES_READS = re.compile(r"under ENFORCE[^.;]*reads included")


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
    lines = (re.sub(r"^\s*(?:#+|//+|\*(?=\s|$))\s?", "", line) for line in text.splitlines())
    return " ".join(" ".join(lines).split())


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+(?=[A-Z`(*])", _folded(text))


def _read_through_sentences() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits = [s for s in _sentences(text) if _READ_THROUGH.search(s)]
        if hits:
            found[str(path.relative_to(ROOT))] = hits
    return found


def test_a_read_let_through_on_a_fault_is_said_with_its_case():
    """(a) THE CONTROL."""
    found = _read_through_sentences()
    assert found, "no public sentence says what a fault does to a read; the check reads nothing"
    unqualified = [f"{path}: {s!r}" for path, hits in found.items()
                   for s in hits if not _QUALIFIED.search(s)]
    assert not unqualified, (
        "a public sentence says a faulting gate lets a plain read through without "
        f"saying when: {unqualified}")


def test_a_file_that_says_so_also_says_enforce_refuses_reads_on_a_fault():
    """(b) THE CONTROL."""
    silent = [path for path in _read_through_sentences()
              if not _ENFORCE_REFUSES_READS.search(_folded((ROOT / path).read_text(
                  encoding="utf-8")))]
    assert not silent, (
        "a public file says a faulting gate lets a plain read through and not that "
        f"under ENFORCE a fault refuses the call, reads included: {sorted(silent)}")


# ── (c) PIN: the seam's own catch, whichever mode the gate reports ─────────────

class _RaisingEnforceGate:
    """A gate that reports ENFORCE and raises instead of answering."""

    mode = seam.MorpheusMode.ENFORCE

    async def evaluate(self, action, context):
        raise RuntimeError("gate fault")


W = "0x" + "ab" * 20
SWAP = ("platform_action", {"action": "swap"})
READ = ("stablecoin", {"action": "balance", "address": "0x" + "cd" * 20})


def _stack(gate):
    from runtime.protocols.integration import ProtocolStack

    stack = ProtocolStack({"agents": {}, "security": {}}, "neo")
    stack._morpheus_security = gate
    stack._morpheus_init_failed = False
    stack._rexhepi_gate = None
    return stack


async def test_a_gate_in_enforce_that_raises_is_decided_by_the_seams_fail_direction(monkeypatch):
    """(c)"""
    from gateway.security_gate import gate_action, is_blocked

    gate = _RaisingEnforceGate()
    monkeypatch.setattr(seam, "get_morpheus_security", lambda *a, **k: gate)
    ctx = {seam.CALLER_IDENTITY_KEY: W}
    assert is_blocked(await gate_action("swap", {}, context=ctx))
    assert not is_blocked(await gate_action("get_balance", {}, context=ctx))
    stack = _stack(gate)
    assert (await stack.pre_action(*SWAP, ctx))["approved"] is False
    assert (await stack.pre_action(*READ, ctx))["approved"] is True


# ── (d) JOINT PIN: the installed core's own answer to a fault ──────────────────

def _bound_to_the_installed_core() -> bool:
    return (importlib.util.find_spec("morpheus_security") is not None
            and seam.MorpheusSecurity.__module__.split(".")[0] != "runtime")


#: A context whose caller is not a string. No entry point binds one: the
#: platform names every caller in one spelling, a string
#: (runtime/auth/identity.py). The core cannot decide a call about it.
UNREADABLE = {seam.CALLER_IDENTITY_KEY: [W]}
READABLE = {seam.CALLER_IDENTITY_KEY: W}


@pytest.fixture
def core_gate():
    if not _bound_to_the_installed_core():
        pytest.skip("the security core is not installed; the no-op backend is in use")
    seam.reset_morpheus_security()
    gate = seam.get_morpheus_security({})
    assert type(gate).__module__.split(".")[0] != "runtime", "the gate is not the core's"
    try:
        yield gate
    finally:
        seam.reset_morpheus_security()


async def test_the_core_in_enforce_refuses_a_read_it_faulted_on(core_gate):
    """(d), ENFORCE"""
    from gateway.security_gate import gate_action, is_blocked

    core_gate.mode = seam.MorpheusMode.ENFORCE
    assert not is_blocked(await gate_action("get_balance", {}, context=READABLE)), (
        "a read by a caller the core can read is refused; the pin below says nothing")
    assert is_blocked(await gate_action("get_balance", {}, context=UNREADABLE))
    stack = _stack(core_gate)
    assert (await stack.pre_action(*READ, READABLE))["approved"] is True
    assert (await stack.pre_action(*READ, UNREADABLE))["approved"] is False


async def test_the_core_in_observe_lets_a_read_it_faulted_on_through(core_gate):
    """(d), OBSERVE"""
    from gateway.security_gate import gate_action, is_blocked

    core_gate.mode = seam.MorpheusMode.OBSERVE
    assert not is_blocked(await gate_action("get_balance", {}, context=UNREADABLE))
    assert not is_blocked(await gate_action("swap", {}, context=READABLE)), (
        "a swap by a caller the core can read is refused; the pin below says nothing")
    assert is_blocked(await gate_action("swap", {}, context=UNREADABLE))
    assert (await _stack(core_gate).pre_action(*READ, UNREADABLE))["approved"] is True
