"""A fee is reported with the result of the call that took it, not before a
confirmation.

The landing page said Trinity tells you what happened "including any fee
before you confirm", and her prompt said that when a tool result reports a fee
she tells the user the amount "before they confirm". Her hand-off to Neo
(runtime/agents/handoff.py) passes the gate and dispatches in the same call,
with no confirmation step, and a fee comes back in the result of the call that
took it, after the call has run.

The premise is measured by running the hand-off; the texts are then read.

What this cannot see: the promise worded outside the pattern below. The legal
copy is counsel's and is not read here.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_NOT_READ = {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}
_BEFORE_A_CONFIRMATION = re.compile(
    r"\b(?:fees?|amount)[^.]{0,40}\bbefore (?:you|they|the user) confirms?\b", re.I)


def _the_handoff_runs_the_call_when_it_is_asked() -> tuple[list[str], dict]:
    from runtime.agents.handoff import AgentHandoff
    from runtime.protocols.outcome_truth import OUTCOME_FIELD, SUCCESS

    calls: list[str] = []

    class _Dispatcher:
        async def execute(self, action, service=None, params=None, **kwargs):
            calls.append(action)
            return json.dumps({"status": "ok", OUTCOME_FIELD: SUCCESS,
                               "result": {"status": "recorded_unsettled", "fee": 0.1}})

    outcome = asyncio.run(AgentHandoff({}, _Dispatcher()).escalate(
        "transfer_stablecoin", {"token": "USDC", "amount": 100}))
    return calls, outcome


def test_the_scan_catches_the_old_copy():
    for old in ("she hands the work to Neo and tells you what happened, including any fee "
                "before you confirm.",
                "when a tool result reports a fee, Trinity tells the user the amount before "
                "they confirm."):
        assert _BEFORE_A_CONFIRMATION.search(old), old
    assert not _BEFORE_A_CONFIRMATION.search(
        "tells you what happened, including any fee the call took. A fee comes back in the "
        "result of the call that took it, and nothing waits for a confirmation.")


def test_no_text_puts_a_fee_before_a_confirmation():
    calls, outcome = _the_handoff_runs_the_call_when_it_is_asked()
    assert calls == ["transfer_stablecoin"] and outcome.get("approved") is True, (
        f"the hand-off no longer runs the call when it is asked; re-derive this check: {outcome}")
    assert "fee" in str(outcome.get("result")), "the fee no longer comes back with the result"
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", (ROOT / rel).read_text(encoding="utf-8")))
        offenders += [f"{rel}: ...{m.group(0)}..." for m in _BEFORE_A_CONFIRMATION.finditer(flat)]
    assert not offenders, "\n".join(offenders)
