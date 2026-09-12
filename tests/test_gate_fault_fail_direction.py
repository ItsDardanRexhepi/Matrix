"""A gate that faults must not read as a gate that approved.

`ProtocolStack.pre_action` consults three things that can REFUSE an action:
Morpheus (the security spine), RexhepiGate (the URF execution gate) and the
Glasswing contract auditor. Morpheus already got its fail-direction right twice
over — an `evaluate` that raises denies anything `could_move_value`, and since
9819e06 so does a gate that failed to CONSTRUCT.

The other two did not. A RexhepiGate.evaluate that raised was logged and fell
through with `approved` still True, so the exact fault that denies a transfer on
the Morpheus branch waved the same transfer through one block later. The same
held for a RexhepiGate that failed to construct (`_rexhepi_gate` left None, read
as "not installed"), and for the auditor: an audit that raised, or an auditor
that never constructed, let a contract tool carrying source code proceed with
no audit — while `ContractAuditor.should_block` itself already blocks an audit
that "could not be performed".

Every control here drives the REAL `ProtocolStack.__init__` / `pre_action` and
injects exactly one fault, so none of them can pass by setting the flag the fix
reads.
"""
from __future__ import annotations

import pytest


def _stack(monkeypatch, *, rexhepi_raises_on_init=False, auditor_raises_on_init=False):
    """A real ProtocolStack whose Morpheus gate allows (so it is not the variable)."""
    if rexhepi_raises_on_init:
        import runtime.protocols.rexhepi_gate as rg

        class _Broken:
            def __init__(self, *a, **k):
                raise RuntimeError("RexhepiGate could not load its reasoning core")

        monkeypatch.setattr(rg, "RexhepiGate", _Broken)
    if auditor_raises_on_init:
        import runtime.security.audit as audit

        class _BrokenAuditor:
            def __init__(self, *a, **k):
                raise RuntimeError("ContractAuditor could not load")

        monkeypatch.setattr(audit, "ContractAuditor", _BrokenAuditor)

    from runtime.protocols.integration import ProtocolStack
    stack = ProtocolStack({"agents": {}, "security": {}}, "neo")

    class _AllowingMorpheus:
        async def evaluate(self, action, context):
            return {"allow": True}

    stack._morpheus_security = _AllowingMorpheus()
    stack._morpheus_init_failed = False
    return stack


class _RaisingRexhepi:
    async def evaluate(self, action, context):
        raise RuntimeError("URF reasoning loop blew up")


TRANSFER = ("stablecoin", {"action": "transfer", "to": "0xTEST_B", "amount": 1})
BALANCE = ("stablecoin", {"action": "balance", "address": "0xTEST_B"})
CTX = {"wallet": "0xTEST_A"}
CONTRACT = "pragma solidity ^0.8.0; contract X { function f() public { } }"


# ── RexhepiGate: evaluate-time fault ─────────────────────────────────────────

async def test_a_rexhepi_evaluate_fault_denies_a_value_moving_action(monkeypatch):
    stack = _stack(monkeypatch)
    stack._rexhepi_gate = _RaisingRexhepi()

    result = await stack.pre_action(*TRANSFER, CTX)
    assert result["approved"] is False, (
        "a RexhepiGate that raised approved a transfer — the fault the Morpheus "
        "branch denies was waved through one block later"
    )
    assert "couldn't be authorized" in result["denial_reason"]


async def test_a_rexhepi_evaluate_fault_still_lets_a_benign_read_through(monkeypatch):
    """Fail-closed must not become fail-always: the same split Morpheus uses."""
    stack = _stack(monkeypatch)
    stack._rexhepi_gate = _RaisingRexhepi()

    result = await stack.pre_action(*BALANCE, CTX)
    assert result["approved"] is True


# ── RexhepiGate: construction-time fault ─────────────────────────────────────

async def test_a_rexhepi_gate_that_failed_to_construct_denies_a_value_moving_action(monkeypatch):
    stack = _stack(monkeypatch, rexhepi_raises_on_init=True)
    assert stack._rexhepi_gate is None, "precondition: the gate did not construct"

    result = await stack.pre_action(*TRANSFER, CTX)
    assert result["approved"] is False, (
        "a RexhepiGate that raised in __init__ read as 'not installed' and allowed a transfer"
    )

    read = await stack.pre_action(*BALANCE, CTX)
    assert read["approved"] is True


# ── Glasswing auditor: the third refusing gate in the same function ──────────

async def test_an_audit_that_raised_does_not_let_contract_source_through(monkeypatch):
    stack = _stack(monkeypatch)
    stack._rexhepi_gate = None  # isolate the auditor

    class _RaisingAuditor:
        def audit(self, source, name=""):
            raise RuntimeError("auditor crashed on this input")

        def should_block(self, report):  # pragma: no cover — never reached
            return False

    stack._auditor = _RaisingAuditor()
    result = await stack.pre_action(
        "platform_action", {"action": "convert_contract", "source_code": CONTRACT}, CTX)
    assert result["approved"] is False, (
        "an audit that could not be performed approved the contract; should_block "
        "already treats 'could not be performed' as a block"
    )


async def test_an_auditor_that_failed_to_construct_does_not_let_contract_source_through(monkeypatch):
    stack = _stack(monkeypatch, auditor_raises_on_init=True)
    stack._rexhepi_gate = None
    assert stack._auditor is None, "precondition: the auditor did not construct"

    result = await stack.pre_action(
        "platform_action", {"action": "convert_contract", "source_code": CONTRACT}, CTX)
    assert result["approved"] is False


async def test_a_missing_auditor_does_not_block_a_call_with_no_source(monkeypatch):
    """The auditor only ever judged calls that CARRY source. Its absence must not
    start refusing calls it never looked at."""
    stack = _stack(monkeypatch, auditor_raises_on_init=True)
    stack._rexhepi_gate = None
    result = await stack.pre_action("platform_action", {"action": "get_balance"}, CTX)
    assert result["approved"] is True


async def test_a_healthy_stack_is_unaffected(monkeypatch):
    """No fault injected: the real RexhepiGate and auditor decide, and a read passes."""
    stack = _stack(monkeypatch)
    assert stack._rexhepi_gate is not None and stack._auditor is not None
    result = await stack.pre_action(*BALANCE, CTX)
    assert result["approved"] is True, result


# ── Round 2 of the same class: the direction itself, and the caller above it ──
#
# 3e704ef routed every gate fault inside pre_action through one helper,
# `_deny_on_gate_fault`, whose direction is `could_move_value`. Two holes stayed:
#
#   1. `could_move_value` trusts any label starting with `list_` as a benign read,
#      and three STATE-MODIFYING actions start with it: list_nft_for_sale
#      (nft_services.list_for_sale), list_marketplace (marketplace.list_item) and
#      list_security (securities_exchange.list_security). Under a raising gate each
#      was approved while a transfer was denied.
#   2. The only caller, ReActLoop.run, wrapped pre_action in
#      `except Exception: logger.exception(...)` and went on to dispatch. Anything
#      that escaped pre_action outside its per-gate try blocks — a function-local
#      import, `allowance_violation` on a `security: null` config — read as
#      approval. So did a ProtocolStack that failed to construct: the loop cached
#      None and ran every tool call with no gate at all.


class _RaisingMorpheus:
    async def evaluate(self, action, context):
        raise RuntimeError("Morpheus seam blew up")


def _state_modifying_actions():
    from runtime.blockchain.services.service_dispatcher import _STATE_MODIFYING_ACTIONS
    return sorted(_STATE_MODIFYING_ACTIONS)


@pytest.mark.parametrize("fault", ["morpheus_evaluate", "morpheus_init",
                                   "rexhepi_evaluate", "rexhepi_init"])
async def test_every_state_modifying_action_is_denied_under_a_gate_fault(monkeypatch, fault):
    """Whatever its prefix. The label is not the classification; the dispatcher's
    own state-modifying set is."""
    if fault == "morpheus_init":
        import runtime.security as seam

        def _broken(*a, **k):
            raise RuntimeError("seam could not construct the gate")

        monkeypatch.setattr(seam, "get_morpheus_security", _broken)
        from runtime.protocols.integration import ProtocolStack
        stack = ProtocolStack({"agents": {}, "security": {}}, "neo")
        assert stack._morpheus_security is None, "precondition: the gate did not construct"
        stack._rexhepi_gate = None  # isolate Morpheus
    else:
        stack = _stack(monkeypatch, rexhepi_raises_on_init=(fault == "rexhepi_init"))
        if fault == "morpheus_evaluate":
            stack._morpheus_security = _RaisingMorpheus()
            stack._rexhepi_gate = None
        elif fault == "rexhepi_evaluate":
            stack._rexhepi_gate = _RaisingRexhepi()
        else:
            assert stack._rexhepi_gate is None, "precondition: the gate did not construct"

    approved = []
    for action in _state_modifying_actions():
        result = await stack.pre_action("platform_action", {"action": action}, CTX)
        if result["approved"]:
            approved.append(action)
    assert approved == [], (
        f"under a {fault} fault these state-modifying actions were approved: {approved}")


def test_no_state_modifying_action_reads_as_a_benign_read():
    from runtime.access_policy import could_move_value
    benign = [a for a in _state_modifying_actions() if not could_move_value(a)]
    assert benign == [], f"could_move_value calls these state changes benign reads: {benign}"


def test_a_null_security_section_refuses_a_platform_key_approve_instead_of_raising():
    """`security:` with no value in YAML is None. allowance_violation called
    `.get` on it, raised, and the raise escaped pre_action."""
    from runtime.security.action_map import allowance_violation
    refusal = allowance_violation("stablecoin", {"action": "approve", "amount": 1},
                                  {"security": None})
    assert refusal and "platform_allowance_cap" in refusal

    # Its sibling reader: ContractAuditor raised on the same config, so every
    # contract call carrying source was refused as an auditor init fault.
    from runtime.security.audit import ContractAuditor
    assert ContractAuditor({"security": None})._block_critical is True


# ── the caller: ReActLoop.run ────────────────────────────────────────────────

def _loop_with_one_tool_call(tmp_path, tool_name, arguments):
    import json
    import sys

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    from runtime.models.model_interface import ModelResponse
    from runtime.react_loop import ReActLoop
    from runtime.tools.dispatcher import ToolOutcome

    loop = ReActLoop({**SWEEP_CONFIG, "memory_dir": str(tmp_path / "memory")})
    replies = [
        ModelResponse(tool_calls=[{"id": "c1", "function": {
            "name": tool_name, "arguments": json.dumps(arguments)}}]),
        ModelResponse(content="done"),
    ]

    async def complete(**kwargs):
        return replies.pop(0)

    dispatched = []

    async def dispatch(name, args, **kwargs):
        dispatched.append((name, args.get("action")))
        return ToolOutcome.success("ran")

    loop.router.complete = complete
    loop.dispatcher.dispatch = dispatch
    return loop, dispatched


async def _run(loop):
    from runtime.react_loop import Message, ReActContext
    return await loop.run(ReActContext(
        agent_name="neo", conversation=[Message(role="user", content="go")],
        metadata={"user_context": {"wallet_address": "0xTEST_A"}}))


async def test_a_pre_action_that_raises_does_not_dispatch_a_value_moving_call(monkeypatch, tmp_path):
    from runtime.protocols.integration import ProtocolStack

    async def raising(self, tool_name, arguments, context):
        raise AttributeError("'NoneType' object has no attribute 'get'")

    monkeypatch.setattr(ProtocolStack, "pre_action", raising)
    loop, dispatched = _loop_with_one_tool_call(
        tmp_path, "stablecoin", {"action": "transfer", "to": "0xTEST_B", "amount": 1})
    result = await _run(loop)
    assert dispatched == [], "a pre_action that raised read as approval and the transfer ran"
    assert result.tool_calls and result.tool_calls[0]["success"] is False


async def test_a_pre_action_that_raises_still_lets_a_benign_read_through(monkeypatch, tmp_path):
    from runtime.protocols.integration import ProtocolStack

    async def raising(self, tool_name, arguments, context):
        raise RuntimeError("pre_action fault")

    monkeypatch.setattr(ProtocolStack, "pre_action", raising)
    loop, dispatched = _loop_with_one_tool_call(
        tmp_path, "platform_action", {"action": "get_balance"})
    await _run(loop)
    assert dispatched == [("platform_action", "get_balance")]


async def test_the_reviewers_trigger_a_null_security_section_does_not_run_an_approve(tmp_path):
    """No patch at all: the config a bare `security:` YAML key produces."""
    loop, dispatched = _loop_with_one_tool_call(
        tmp_path, "stablecoin", {"action": "approve", "spender": "0xTEST_B", "amount": 1})
    loop.config = {**loop.config, "security": None}
    await _run(loop)
    assert dispatched == []


async def test_a_protocol_stack_that_failed_to_construct_does_not_run_calls_ungated(monkeypatch, tmp_path):
    import runtime.protocols.integration as integration

    class _Broken:
        def __init__(self, *a, **k):
            raise RuntimeError("ProtocolStack could not construct")

    monkeypatch.setattr(integration, "ProtocolStack", _Broken)
    loop, dispatched = _loop_with_one_tool_call(
        tmp_path, "stablecoin", {"action": "transfer", "to": "0xTEST_B", "amount": 1})
    await _run(loop)
    assert dispatched == [], "no stack was read as no gate, and the transfer ran"

    loop, dispatched = _loop_with_one_tool_call(
        tmp_path, "platform_action", {"action": "get_balance"})
    await _run(loop)
    assert dispatched == [("platform_action", "get_balance")]


async def test_an_audit_report_that_cannot_render_still_blocks(monkeypatch):
    """3e704ef moved to_dict()/summary out of the fail-closed try. A block whose
    report raised while rendering must stay a block, and must not raise out of
    pre_action (where it would be the caller's fault path instead)."""
    stack = _stack(monkeypatch)
    stack._rexhepi_gate = None

    class _Unrenderable:
        findings = ["x"]

        def to_dict(self):
            raise RuntimeError("report serialisation failed")

        @property
        def summary(self):
            raise RuntimeError("summary failed")

    class _BlockingAuditor:
        def audit(self, source, name=""):
            return _Unrenderable()

        def should_block(self, report):
            return True

    stack._auditor = _BlockingAuditor()
    result = await stack.pre_action(
        "platform_action", {"action": "get_contract_template", "source_code": CONTRACT}, CTX)
    assert result["approved"] is False
