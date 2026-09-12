"""The §CD sibling-axes pass's findings, pinned.

§CD: a prior fix establishes a CLASS; every sibling axis that class could apply
to is unchecked until someone checks it. These are the axes the pass found
unfixed, each with the control that reproduces it.
"""
from __future__ import annotations

import pytest

from runtime.tools.dispatcher import ToolDispatcher


def _bare_stack():
    """A ProtocolStack with every protocol absent — the shape a checkout without
    the private package produces, built without running __init__ so the test
    controls exactly one variable."""
    from runtime.protocols.integration import ProtocolStack
    stack = ProtocolStack.__new__(ProtocolStack)
    stack.config = {}
    stack.agent_name = "neo"
    stack._auditor = None
    stack._friday = None
    stack._jarvis = None
    stack._morpheus_security = None
    stack._morpheus_triggers = None
    stack._omega = None
    stack._outcome_learning = None
    stack._rexhepi_gate = None
    stack._trajectory = None
    stack._ultron = None
    stack._vision = None
    stack._morpheus_init_failed = False
    return stack

# ── the identity class: derived, never asserted ──────────────────────────────

async def test_a_model_cannot_supply_caller_identity():
    """The HTTP and bridge entry points derive identity from the session. The
    TOOL path registered ServiceDispatcher.execute and called handler(**arguments)
    with the model's own JSON, so a model-authored `caller_identity` bound the
    keyword-only parameter those entry points refuse to accept."""
    seen = {}

    async def fake_execute(action: str, service: str | None = None, params: dict | None = None,
                           *, caller_identity: str = "", caller_source: str = "") -> str:
        seen.update(action=action, caller_identity=caller_identity, caller_source=caller_source)
        return "ok"

    d = ToolDispatcher.__new__(ToolDispatcher)
    d._tools = {"platform_action": fake_execute}
    d._schemas = {}

    outcome = await d.dispatch(
        "platform_action",
        {"action": "get_balance", "caller_identity": "0xTEST_VICTIM", "caller_source": "user"},
        agent_name="neo", caller_identity="0xTEST_REAL", caller_source="agent")
    assert outcome.ok, outcome
    assert seen["caller_identity"] == "0xTEST_REAL", "the model's value must not win"
    assert seen["caller_source"] == "agent"


async def test_a_reserved_arguments_are_stripped_even_with_no_trusted_value():
    seen = {}

    async def fake_execute(action: str, *, caller_identity: str = "") -> str:
        seen["caller_identity"] = caller_identity
        return "ok"

    d = ToolDispatcher.__new__(ToolDispatcher)
    d._tools = {"platform_action": fake_execute}
    d._schemas = {}
    await d.dispatch("platform_action",
                     {"action": "x", "caller_identity": "0xTEST_FORGED"}, agent_name="neo")
    assert seen["caller_identity"] == "", "an unasserted identity is empty, not the model's"


async def test_a_a_handler_without_the_parameter_is_unaffected():
    async def plain(query: str = "") -> str:
        return f"searched {query}"

    d = ToolDispatcher.__new__(ToolDispatcher)
    d._tools = {"web_search": plain}
    d._schemas = {}
    outcome = await d.dispatch("web_search", {"query": "x"}, agent_name="neo",
                               caller_identity="0xTEST_REAL")
    assert outcome.ok and "searched x" in outcome.model_text


# ── the fail-direction class: a fault is not a posture ───────────────────────

async def test_b_a_gate_that_failed_to_construct_fails_closed():
    """The evaluate-time fault fails closed. The INIT-time one skipped the whole
    Morpheus block, so a value-moving call executed ungated."""
    stack = _bare_stack()
    stack._morpheus_init_failed = True

    denied = await stack.pre_action("stablecoin", {"action": "transfer", "amount": 1},
                                    {"wallet": "0xTEST_A"})
    assert denied["approved"] is False
    assert "couldn't be authorized" in denied["denial_reason"]

    allowed = await stack.pre_action("stablecoin", {"action": "balance"}, {"wallet": "0xTEST_A"})
    assert allowed["approved"] is True, "a benign read still passes a transient fault"


async def test_b_an_absent_gate_that_did_not_fail_is_not_treated_as_a_fault():
    """The seam legitimately returns no gate in an open checkout. That is a
    POSTURE, and it must not be confused with a construction failure."""
    stack = _bare_stack()
    stack._morpheus_init_failed = False

    result = await stack.pre_action("stablecoin", {"action": "transfer", "amount": 1},
                                    {"wallet": "0xTEST_A"})
    assert result["approved"] is True
