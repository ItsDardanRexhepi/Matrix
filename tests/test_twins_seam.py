"""T4 — the twins' seam (register entry::TWINS-CRITICAL, entry::B3-TWIN-APPROVE,
entry::B3-TWIN-SUPPLY-ONBEHALF, standing rule §DL.4).

Measured at the pin (D-017 drive, register entry::TWINS-CRITICAL): the seam
handed the security gate ``action_type = tool_name``, a label that names the
tool that was called and not what the call does, so most twin tools reached the
gate under a label it passed through, ``smart_contract`` deploying
caller-supplied Solidity with the platform key included. ``onBehalfOf`` and
``spender`` were whatever the caller wrote.

Now the seam maps every declared (tool, action) to what it DOES. These tests
pin the table's completeness against the registry's own schemas, the refusals,
and — when the private package is installed — the control, asked of the gate
itself through the seam: every signing label is one the gate evaluates rather
than passes through. What the gate evaluates is the private package's own and
is not restated here; without the package those checks are skipped, not run
against a copy.
"""

from __future__ import annotations

import ast
import re
import secrets
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


def test_platform_action_is_classified_on_its_inner_action():
    assert canonical_action("platform_action", {"action": "swap", "params": {}}) == ("swap", None)
    assert canonical_action("web_search", {"query": "x"}) == ("web_search", None)


# ── against the installed gate, asked through the seam ───────────────────────
#
# These checks ask the gate itself, built through the seam with no host the way
# a script builds it, and skip where the private package is not installed: they
# never run against a copy of anything the gate holds. A decision says in
# ``route`` whether the gate evaluated the call at all; ``pass_through`` is a
# call it did not (runtime/security/SECURITY_INTERFACE.md).

PASSED_THROUGH = "pass_through"


def _installed_gate(tmp_path):
    pytest.importorskip("morpheus_security")
    import runtime.security as seam

    if seam.MorpheusSecurity.__module__.split(".")[0] == "runtime":
        pytest.skip("the seam is not bound to the private package")
    seam.reset_morpheus_security()
    gate = seam.get_morpheus_security({"memory_dir": str(tmp_path),
                                       "database": {"path": str(tmp_path / "gate.db")}})
    return seam, gate


async def _route(gate, action_type: str, caller: str, **fields) -> str | None:
    decision = await gate.evaluate({"action_type": action_type, **fields}, {"wallet_address": caller})
    return decision.get("route")


async def _gate_lets_a_read_through(gate, caller: str) -> bool:
    """A gate that refuses everything for this caller (or for everyone) would
    make the measurements below say nothing: every route would read as taken."""
    decision = await gate.evaluate(
        {"action_type": "balance", "tool": "stablecoin", "tool_action": "balance"},
        {"wallet_address": caller})
    return decision.get("allow") is True and not decision.get("would_block")


async def test_every_signing_label_is_one_the_installed_gate_evaluates(tmp_path):
    """Every label the seam produces for a platform-key-signed twin action is
    one the installed gate evaluates rather than passes through. What the gate
    evaluates is the private package's own, asked of the gate where it is
    installed; this repository keeps no copy of it."""
    seam, gate = _installed_gate(tmp_path)
    caller = "0x" + secrets.token_hex(20)
    try:
        await gate.initialize()
        assert await _gate_lets_a_read_through(gate, caller), "the gate refuses a read for a fresh caller"
        passed_through = []
        for tool, acts in SIGNING_ACTIONS.items():
            for verb, mapped in acts.items():
                if mapped == READ:
                    continue
                label, signs = canonical_action(tool, {"action": verb})
                route = await _route(gate, label, caller, tool=tool, tool_action=verb,
                                     signs_with_platform_key=signs)
                if route == PASSED_THROUGH:
                    passed_through.append((tool, verb, label))
        assert not passed_through, passed_through
    finally:
        seam.reset_morpheus_security()


# ── THE CONTROL: the D-017 drive through the seam ────────────────────────────

async def test_control_every_signing_action_now_requires_the_gate(tmp_path):
    """Labelled by the tool's name, twin tools were passed through (the pin's
    measurement); labelled by what the call does, every signing action is
    evaluated."""
    seam, gate = _installed_gate(tmp_path)
    caller = "0x" + secrets.token_hex(20)
    try:
        await gate.initialize()
        assert await _gate_lets_a_read_through(gate, caller), "the gate refuses a read for a fresh caller"
        by_name_passed_through = 0
        for tool in sorted(TWIN_TOOLS):
            if await _route(gate, tool, caller, tool=tool) == PASSED_THROUGH:
                by_name_passed_through += 1
        assert by_name_passed_through, (
            "the pin's measurement no longer reproduces: labelled by tool name, no "
            "twin tool is passed through")
        signing = [(t, a) for t, acts in SIGNING_ACTIONS.items() for a, v in acts.items() if v != READ]
        passed_through = []
        for tool, verb in signing:
            label, signs = canonical_action(tool, {"action": verb})
            if await _route(gate, label, caller, tool=tool, tool_action=verb,
                            signs_with_platform_key=signs) == PASSED_THROUGH:
                passed_through.append((tool, verb))
        assert not passed_through, passed_through
        # 49 declared signing actions at this commit. The floor read 50 until
        # D-045 took ``deploy`` out of smart_contract's declared actions, and
        # failed with the core installed from then on, on the base tree too.
        assert len(signing) >= 49, len(signing)
    finally:
        seam.reset_morpheus_security()


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
