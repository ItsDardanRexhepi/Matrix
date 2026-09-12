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
