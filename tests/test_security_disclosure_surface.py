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

3. HONEST ABOUT THE DEFAULT. What the seam does without the private package is
   measured, not assumed: the gate is asked to evaluate a value-moving action,
   and if it allows it, the public statements about the layer may not say it
   "cannot be bypassed" or "governs all agent behavior" and must name OBSERVE.
   When the private package IS installed this check stands down, because then
   the measured fact is different.
"""

from __future__ import annotations

import asyncio
import os
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
