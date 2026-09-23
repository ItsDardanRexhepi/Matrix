"""The platform key signs no attestation whose subject the caller writes.

THE FINDINGS (register entry::B3-ATTEST-SIBLING and entry::U-ATTEST-AXIS).
Every EAS attestation the platform makes is signed with the platform's key and
encodes ``(platform, action, agent, timestamp)`` plus a recipient. Three of the
model-reachable tools filled those from the request:

  * ``agent_identity.attest_action`` — ``action`` and ``agent`` straight from the
    caller: a public, platform-signed statement that "agent morpheus performed
    <anything>";
  * ``agent_identity.register`` — the agent name from the caller: a platform-
    signed registration for an agent the platform does not run;
  * ``identity.register`` — the recipient from the caller's ``address``: a
    platform-signed identity registration naming an address nobody showed they
    control.

THE SIBLING THE SAME FIX CLOSES (found by a review of the T4 seam). The seam's beneficiary
refusal checked ``onBehalfOf`` / ``on_behalf_of`` / ``beneficiary``, while the
DeFi twin hands Aave its ``user_address`` as onBehalfOf — so a platform-signed
supply or borrow pointed at somebody else passed a check that never looked at
the field that decided it. The refusal now also reads the field each signing
action actually uses.

THE CHANGE. ``attest_action`` is refused: the platform attests an action when it
EXECUTES it (ServiceDispatcher records its own), and has no business signing a
statement the caller composed. ``register`` names only an agent the platform
runs. And the seam binds each action's own beneficiary field to the caller's
identity, the rule it already applied to the generic names.

CONTROL, measured at The Matrix ``main`` b478b51: 12 of the 16 tests fail
there and all 16 pass after. The other 4 — the four cases of
``test_the_callers_own_address_and_reads_still_pass`` — are guards: they pass
before and after, and pin that the caller's own address, an absent field and a
read are not refused. The last test keeps the table from drifting to a field
its tool does not read. The same class on the tools a later review drove (the
general ``eas`` tool, gaming, IP, securities, cross-border) is closed and
censused in tests/test_every_twin_attestation_is_the_platforms_own.py.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re

import pytest

CFG = {"blockchain": {"network": "base-sepolia"}}


@pytest.fixture
def attests(monkeypatch):
    """Every call that would have reached the platform-signed EAS attest."""
    calls = []

    async def spy(self, action, agent, details, recipient="0x" + "0" * 40):
        calls.append({"action": action, "agent": agent, "recipient": recipient})
        return {"status": "skipped", "reason": "test spy"}

    monkeypatch.setattr("runtime.blockchain.eas_client.EASClient.attest", spy)
    return calls


def _run(coro):
    return json.loads(asyncio.run(coro))


# ── agent_identity.attest_action ──────────────────────────────────────────

def test_the_platform_key_does_not_sign_an_action_statement_the_caller_wrote(attests):
    from runtime.blockchain.agent_identity import AgentIdentity
    out = _run(AgentIdentity(CFG).execute(
        action="attest_action", agent_name="morpheus", agent_action="approved_withdrawal_of_all_funds"))
    assert attests == [], f"the platform key was asked to sign {attests}"
    assert out.get("ok") is False and out.get("code") == "denied"


# ── agent_identity.register ───────────────────────────────────────────────

@pytest.mark.parametrize("name", ["morpheus2", "EVIL", "neo; admin", ""])
def test_a_registration_names_only_an_agent_the_platform_runs(attests, name):
    from runtime.blockchain.agent_identity import AgentIdentity
    out = _run(AgentIdentity(CFG).execute(action="register", agent_name=name))
    assert attests == [], f"registered an agent the platform does not run: {attests}"
    assert out.get("ok") is False and out.get("code") == "denied"


def test_a_platform_agent_still_registers(attests):
    from runtime.blockchain.agent_identity import AgentIdentity
    _run(AgentIdentity(CFG).execute(action="register", agent_name=" Neo "))
    assert [c["agent"] for c in attests] == ["neo"], "the legitimate registration must still run"


# ── the seam: each signing action's own beneficiary field ─────────────────

@pytest.mark.parametrize("tool,args", [
    ("identity", {"action": "register", "name": "x", "address": "0xTEST_B"}),
    ("defi", {"action": "supply", "user_address": "0xTEST_B", "amount": 1}),
    ("defi", {"action": "borrow", "user_address": "0xTEST_B", "amount": 1}),
])
def test_an_action_pointed_at_somebody_else_is_refused(tool, args):
    from runtime.security.action_map import beneficiary_violation
    msg = beneficiary_violation(tool, args, "0xTEST_A")
    assert msg and "own address" in msg, f"{tool}.{args['action']} was not refused: {msg!r}"


@pytest.mark.parametrize("tool,args", [
    ("identity", {"action": "register", "name": "x", "address": "0xtest_a"}),
    ("defi", {"action": "supply", "user_address": "0xTEST_A", "amount": 1}),
    ("defi", {"action": "supply", "amount": 1}),              # absent: the platform's own account
    ("identity", {"action": "lookup", "address": "0xTEST_B"}),  # a read
])
def test_the_callers_own_address_and_reads_still_pass(tool, args):
    from runtime.security.action_map import beneficiary_violation
    assert beneficiary_violation(tool, args, "0xTEST_A") is None


def test_an_identity_registration_with_no_bound_identity_is_refused():
    from runtime.security.action_map import beneficiary_violation
    msg = beneficiary_violation("identity", {"action": "register", "address": "0xTEST_B"}, "")
    assert msg and "no identity is bound" in msg


async def test_the_seam_refuses_before_the_gate_sees_it():
    import sys
    sys.path.insert(0, "tests")
    from test_twins_seam import _stack
    stack = _stack()
    result = await stack.pre_action(
        "identity", {"action": "register", "name": "x", "address": "0xTEST_B"}, {"wallet": "0xTEST_A"})
    assert result["approved"] is False and "own address" in result["denial_reason"]
    assert stack._morpheus_security.seen == [], "refused at the seam; the gate never saw it"


def _source_of(tool: str) -> pathlib.Path:
    """The twin module whose ``name`` is *tool*."""
    hits = [f for f in sorted(pathlib.Path("runtime/blockchain").glob("*.py"))
            if re.search(r'def name\(self\)[^:]*:\s*\n\s*return "%s"' % re.escape(tool),
                         f.read_text(encoding="utf-8"))]
    assert len(hits) == 1, f"{tool!r}: {hits}"
    return hits[0]


def test_every_listed_beneficiary_field_is_one_its_tool_reads():
    """The table cannot name a field nobody reads (that was the bug, inverted)."""
    from runtime.security.action_map import ACTION_BENEFICIARY_FIELDS
    for (tool, verb), fields in ACTION_BENEFICIARY_FIELDS.items():
        source = _source_of(tool)
        text = source.read_text(encoding="utf-8")
        for field in fields:
            assert re.search(r'params\.get\(\s*"%s"' % re.escape(field), text), \
                f"{tool}.{verb} lists {field!r}, which {source} never reads"
