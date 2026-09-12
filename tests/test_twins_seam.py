"""T4 — the twins' seam (register entry::TWINS-CRITICAL, entry::B3-TWIN-APPROVE,
entry::B3-TWIN-SUPPLY-ONBEHALF, standing rule §DL.4).

Measured at the pin (D-017 drive, register entry::TWINS-CRITICAL): the seam
handed the security gate ``action_type = tool_name``; the gate classifies by
verb, so ``_requires_morpheus`` was False for 18 of the 20 twin tools —
``smart_contract`` deploying caller-supplied Solidity with the platform key
included — and True for two by naming coincidence (``payment``, ``stake``).
``onBehalfOf`` and ``spender`` were whatever the caller wrote.

Now the seam maps every declared (tool, action) to what it DOES. These tests
pin the table's completeness against the registry's own schemas, the refusals,
and — when the private package is importable — the control: every signing
action is a verb the gate requires evaluation for.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from runtime.security.action_map import (
    ALLOWANCE_ACTIONS, BENEFICIARY_FIELDS, READ, SIGNING_ACTIONS, TWIN_TOOLS,
    allowance_violation, beneficiary_violation, canonical_action,
)

ROOT = Path(__file__).resolve().parent.parent
CAPABILITY_DIR = ROOT / "runtime" / "blockchain"


def _declared_actions_from_source() -> dict[str, set[str]]:
    """tool name -> declared action enum, read from each capability's source
    (constructing the classes needs chain config; the schema literal does not)."""
    out: dict[str, set[str]] = {}
    for f in sorted(CAPABILITY_DIR.glob("*.py")):
        text = f.read_text(encoding="utf-8")
        name = re.search(r'return "([a-z_]+)"\s*\n', text)
        enum = re.search(r'"action"\s*:\s*\{[^}]*?"enum"\s*:\s*(\[[^\]]*\])', text, re.S)
        if not (name and enum):
            continue
        out[name.group(1)] = set(ast.literal_eval(enum.group(1)))
    return out


def _registry_tool_names() -> set[str]:
    text = (CAPABILITY_DIR / "registry.py").read_text(encoding="utf-8")
    block = text.split("CAPABILITY_CLASSES = [", 1)[1].split("]", 1)[0]
    classes = re.findall(r"^\s*([A-Za-z]+),", block, re.M)
    names = set()
    for cls in classes:
        for f in CAPABILITY_DIR.glob("*.py"):
            t = f.read_text(encoding="utf-8")
            if re.search(rf"^class {cls}\b", t, re.M):
                m = re.search(r'return "([a-z_]+)"\s*\n', t)
                if m:
                    names.add(m.group(1))
    return names


# ── the code→registration test (§DL) ─────────────────────────────────────────

def test_every_registered_twin_is_in_the_table():
    registered = _registry_tool_names()
    assert len(registered) == 20, registered
    assert registered == TWIN_TOOLS, (registered - TWIN_TOOLS, TWIN_TOOLS - registered)


def test_every_declared_action_of_every_twin_is_classified():
    declared = _declared_actions_from_source()
    assert set(declared) >= TWIN_TOOLS, TWIN_TOOLS - set(declared)
    stale, missing = {}, {}
    for tool in TWIN_TOOLS:
        table = set(SIGNING_ACTIONS[tool])
        if declared[tool] - table:
            missing[tool] = sorted(declared[tool] - table)
        if table - declared[tool]:
            stale[tool] = sorted(table - declared[tool])
    assert not missing, f"declared actions the seam does not classify: {missing}"
    assert not stale, f"table entries no capability declares any more: {stale}"


def test_an_undeclared_twin_action_is_treated_as_signing():
    action_type, signs = canonical_action("smart_contract", {"action": "something_new"})
    assert signs is True and action_type == "send_transaction"


def test_reads_keep_their_verb_and_do_not_sign():
    assert canonical_action("stablecoin", {"action": "balance"}) == ("balance", False)
    assert canonical_action("dashboard", {"action": "gas_price"}) == ("gas_price", False)


def test_signing_actions_map_to_the_gates_vocabulary():
    """Every signing entry is a verb the gate treats as fund-moving. The
    vocabulary is read from the private package when present; otherwise the
    list below is the one measured from it (morpheus.py:84-89 at 0ee3ba9)."""
    try:
        from morpheus_security.morpheus import FUND_MOVING_ACTIONS as vocab
    except Exception:
        vocab = {"transfer", "send", "send_transaction", "send_payment", "pay", "payment", "swap", "trade",
                 "bridge", "withdraw", "deposit", "stake", "unstake", "lend", "borrow", "repay",
                 "provide_liquidity", "remove_liquidity", "buy", "sell", "mint", "redeem", "claim",
                 "x402_payment"}
    bad = [(t, a, v) for t, acts in SIGNING_ACTIONS.items() for a, v in acts.items()
           if v != READ and v not in vocab]
    assert not bad, bad


def test_platform_action_is_classified_on_its_inner_action():
    assert canonical_action("platform_action", {"action": "swap", "params": {}}) == ("swap", None)
    assert canonical_action("web_search", {"query": "x"}) == ("web_search", None)


# ── THE CONTROL: the D-017 drive through the seam ────────────────────────────

def test_control_every_signing_action_now_requires_the_gate():
    morpheus = pytest.importorskip("morpheus_security.morpheus")
    requires = morpheus.MorpheusSecurity._requires_morpheus
    by_name_before = [t for t in TWIN_TOOLS if requires(t)]
    assert len(by_name_before) == 2, "the pin's measurement: only payment and stake passed, by name"
    signing = [(t, a) for t, acts in SIGNING_ACTIONS.items() for a, v in acts.items() if v != READ]
    not_required = [(t, a) for t, a in signing if not requires(canonical_action(t, {"action": a})[0])]
    assert not not_required, not_required
    assert len(signing) >= 50


# ── the refusals ─────────────────────────────────────────────────────────────

def test_a_beneficiary_other_than_the_caller_is_refused():
    for field in BENEFICIARY_FIELDS:
        msg = beneficiary_violation("defi", {"action": "supply", field: "0xTEST_B"}, "0xTEST_A")
        assert msg and "own address" in msg, (field, msg)
    assert beneficiary_violation("defi", {"action": "supply", "onBehalfOf": "0xtest_a"}, "0xTEST_A") is None


def test_a_beneficiary_with_no_bound_identity_is_refused():
    msg = beneficiary_violation("defi", {"action": "supply", "onBehalfOf": "0xTEST_B"}, "")
    assert msg and "no identity is bound" in msg


def test_a_beneficiary_on_a_read_is_not_our_business():
    assert beneficiary_violation("defi", {"action": "get_positions", "onBehalfOf": "0xTEST_B"}, "") is None


def test_platform_key_approve_is_refused_without_a_cap():
    for tool, action in ALLOWANCE_ACTIONS:
        msg = allowance_violation(tool, {"action": action, "spender": "0xTEST_S", "amount": 1}, {})
        assert msg and "disabled" in msg, (tool, msg)


def test_platform_key_approve_within_an_operator_cap_passes():
    cfg = {"security": {"platform_allowance_cap": 100}}
    assert allowance_violation("stablecoin", {"action": "approve", "amount": 50}, cfg) is None
    assert allowance_violation("stablecoin", {"action": "approve", "amount": 500}, cfg)
    assert allowance_violation("stablecoin", {"action": "approve", "amount": 0}, cfg)


# ── through the seam itself ──────────────────────────────────────────────────

class _CapturingGate:
    def __init__(self):
        self.seen = []

    async def evaluate(self, action, context):
        self.seen.append(action)
        return {"allow": True}


def _stack():
    from runtime.protocols.integration import ProtocolStack
    stack = ProtocolStack({"agents": {}, "security": {}}, "neo")
    stack._morpheus_security = _CapturingGate()
    stack._rexhepi_gate = None
    return stack


async def test_the_gate_sees_a_deployment_as_a_signed_transaction():
    stack = _stack()
    result = await stack.pre_action("smart_contract", {"action": "deploy", "source": "contract X {}"}, {"wallet": "0xTEST_A"})
    assert result["approved"] is True
    seen = stack._morpheus_security.seen[-1]
    assert seen["action_type"] == "send_transaction"
    assert seen["tool"] == "smart_contract" and seen["tool_action"] == "deploy"
    assert seen["signs_with_platform_key"] is True


async def test_the_gate_sees_a_stablecoin_transfer_as_a_transfer():
    stack = _stack()
    await stack.pre_action("stablecoin", {"action": "transfer", "to": "0xTEST_B", "amount": 1}, {"wallet": "0xTEST_A"})
    assert stack._morpheus_security.seen[-1]["action_type"] == "transfer"


async def test_the_seam_refuses_supply_on_behalf_of_somebody_else_before_the_gate():
    stack = _stack()
    result = await stack.pre_action("defi", {"action": "supply", "onBehalfOf": "0xTEST_B", "amount": 1}, {"wallet": "0xTEST_A"})
    assert result["approved"] is False and "own address" in result["denial_reason"]
    assert stack._morpheus_security.seen == [], "refused at the seam; the gate never saw it"


async def test_the_seam_refuses_a_platform_key_approve_by_default():
    stack = _stack()
    result = await stack.pre_action("stablecoin", {"action": "approve", "spender": "0xTEST_S", "amount": 1}, {"wallet": "0xTEST_A"})
    assert result["approved"] is False and "disabled" in result["denial_reason"]


async def test_a_read_passes_the_seam_untouched():
    stack = _stack()
    result = await stack.pre_action("stablecoin", {"action": "balance", "address": "0xTEST_B"}, {"wallet": "0xTEST_A"})
    assert result["approved"] is True
    assert stack._morpheus_security.seen[-1]["action_type"] == "balance"
