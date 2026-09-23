"""A platform-signed transfer moves only the caller's own asset.

THE SIBLING (a review of the attestation-subject binding, recorded for §CD).
``ACTION_BENEFICIARY_FIELDS`` lists the field a signing twin action reads as the
account it acts FOR. Two such fields were outside it, and neither is an address
something is delivered to:

  nft.transfer          transferFrom(from_address, to), signed by the platform
                        key (runtime/blockchain/nfts.py)
  gaming.transfer_item  safeTransferFrom(player_address, to, ...), the same
                        (runtime/blockchain/gaming.py)

Wherever the platform key holds an approval, the request chose whose asset
moved. The seam now binds each FROM field to the caller's identity; absent, the
tool moves the platform's own, as before.

NOT BOUND, and pinned here as a decision: the account an ADMIN action is about.
``securities.freeze``'s ``investor_address`` and ``governance.grant_role``'s
``account`` are somebody else by the nature of the action; binding them to the
caller would leave only freezing yourself or granting yourself the role. They
are Neo's tools, and a chat caller without the operator key never holds them —
driven below through the tool dispatcher.

CONTROL. At fix/oldq-census 083ed72 the tests marked [control] fail; the tests
marked [guard] pass before and after.
"""

from __future__ import annotations

import sys

import pytest

from runtime.security.action_map import beneficiary_violation

ZERO = "0x" + "0" * 40
A = "0x" + "a1" * 20      # the caller's bound identity
B = "0x" + "b2" * 20      # somebody else

FROM_CASES = [
    ("nft", {"action": "transfer", "from_address": B, "to": A,
             "contract_address": ZERO, "token_id": 1}, "from_address"),
    ("gaming", {"action": "transfer_item", "player_address": B, "to": A,
                "contract_address": ZERO, "item_id": 1}, "player_address"),
]


@pytest.mark.parametrize("tool,args,field", FROM_CASES)
def test_moving_somebody_elses_asset_is_refused(tool, args, field):
    """[control]"""
    msg = beneficiary_violation(tool, args, A)
    assert msg and "own address" in msg and field in msg, (tool, msg)


@pytest.mark.parametrize("tool,args,field", FROM_CASES)
def test_with_no_bound_identity_naming_any_owner_is_refused(tool, args, field):
    """[control]"""
    msg = beneficiary_violation(tool, args, "")
    assert msg and "no identity is bound" in msg, (tool, msg)


@pytest.mark.parametrize("tool,args,field", FROM_CASES)
def test_the_callers_own_asset_the_platforms_own_and_any_payee_still_pass(tool, args, field):
    """[guard] Your own asset, the platform's own (field absent), and delivery
    to somebody else — `to` is the payee, which is what a transfer is for."""
    assert beneficiary_violation(tool, {**args, field: A}, A) is None
    assert beneficiary_violation(tool, {k: v for k, v in args.items() if k != field}, A) is None
    assert beneficiary_violation(tool, {**args, field: A, "to": B}, A) is None


async def test_the_seam_refuses_it_before_the_gate():
    """[control] Through the real pre_action, as the tool loop calls it."""
    sys.path.insert(0, "tests")
    from test_twins_seam import _stack
    stack = _stack()
    result = await stack.pre_action("nft", FROM_CASES[0][1], {"wallet": A})
    assert result["approved"] is False and "own address" in result["denial_reason"]
    assert stack._morpheus_security.seen == [], "refused at the seam; the gate never saw it"


@pytest.mark.parametrize("tool,args", [
    ("securities", {"action": "freeze", "investor_address": B, "contract_address": ZERO}),
    ("governance", {"action": "grant_role", "account": B, "role": "0x" + "00" * 32,
                    "contract_address": ZERO}),
])
def test_an_admin_actions_subject_is_not_bound(tool, args):
    """[guard] The decision above, pinned: these name somebody else by nature."""
    assert beneficiary_violation(tool, args, A) is None


@pytest.mark.parametrize("caller_kind", ["session", "anonymous"])
@pytest.mark.parametrize("tool,args", [
    ("securities", {"action": "freeze", "investor_address": B, "contract_address": ZERO}),
    ("governance", {"action": "grant_role", "account": B, "role": "0x" + "00" * 32,
                    "contract_address": ZERO}),
])
async def test_a_caller_without_the_operator_key_never_holds_the_admin_tools(
        monkeypatch, caller_kind, tool, args):
    """[guard] What leaves the admin subjects unbound safe to leave: whatever
    agent name arrives with it, a chat caller without the operator key is served
    by Trinity, who holds neither tool, so nothing runs."""
    from runtime.tools.dispatcher import ToolDispatcher

    ran = []

    async def handler(**kwargs):
        ran.append(kwargs)
        return "ran"

    dispatcher = ToolDispatcher({"workspace": "."})
    monkeypatch.setitem(dispatcher._tools, tool, handler)
    out = await dispatcher.dispatch(tool, dict(args), agent_name="neo", caller_kind=caller_kind)
    assert ran == [] and out.ok is False and "[DENIED]" in out.model_text, out.model_text
