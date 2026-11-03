"""The tool path judges the call it runs, in the units it signs, with a gate
that comes back when it can, and leaves the caller's arguments as they were.

THE DEFECTS (pre-existing on The Matrix ``main``):

  * ``ToolDispatcher.dispatch`` wrote the identity it binds into the caller's
    own arguments dict, so what ``pre_action``, ``post_action`` and the client
    saw was not what had been executed, and a dict passed twice carried the
    first call's identity into the second;
  * a ProtocolStack whose Morpheus gate failed to construct (a transient
    database error, say) stayed failed for the life of the cached stack:
    every value-moving call was refused with "Please try again" and trying
    again could never work;
  * the platform-key ``approve`` cap compared the amount with ``float()``:
    ``NaN`` passed the comparison, and an integer too large for a float
    raised ``OverflowError`` out of the check instead of refusing;
  * ``tokenize``'s ``approve`` scaled the amount by a fixed ``10**18``, while
    the cap is in whole tokens, so on a 6-decimal token a capped approve of
    100 granted 10**14 tokens.
"""
from __future__ import annotations

import json
import types

import pytest

from runtime.security.action_map import allowance_violation

CAPPED = {"security": {"platform_allowance_cap": 100}}


async def test_dispatch_leaves_the_caller_s_arguments_as_they_were():
    """[control] The bound identity was written into the caller's dict."""
    from runtime.tools.dispatcher import ToolDispatcher
    dispatcher = ToolDispatcher({"workspace": "."})
    seen = []

    async def handler(action: str = "", caller_identity: str = "", caller_source: str = ""):
        seen.append(caller_identity)
        return json.dumps({"ok": True})

    dispatcher.register("probe_tool", handler, {"name": "probe_tool", "parameters": {}})
    args = {"action": "get_balance"}
    await dispatcher.dispatch("probe_tool", args, agent_name="neo",
                              caller_identity="0x" + "a1" * 20, caller_source="operator")
    assert seen == ["0x" + "a1" * 20], "precondition: the handler got the bound identity"
    assert args == {"action": "get_balance"}, args


async def test_a_gate_that_failed_to_construct_is_tried_again(monkeypatch):
    """[control] The failure was cached with the stack for good."""
    import runtime.security as seam
    from runtime.protocols.integration import ProtocolStack

    def broken(*_a, **_k):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(seam, "get_morpheus_security", broken)
    stack = ProtocolStack({"agents": {}, "security": {}}, "neo")
    stack._rexhepi_gate = None
    first = await stack.pre_action("stablecoin", {"action": "transfer", "to": "0x" + "b2" * 20,
                                                  "amount": 1}, {"wallet": "0x" + "a1" * 20})
    assert first["approved"] is False, "precondition: a gate that cannot construct refuses"

    class _Allow:
        async def evaluate(self, action, context):
            return {"allow": True, "route": "evaluated"}
    monkeypatch.setattr(seam, "get_morpheus_security", lambda *_a, **_k: _Allow())
    again = await stack.pre_action("stablecoin", {"action": "transfer", "to": "0x" + "b2" * 20,
                                                  "amount": 1}, {"wallet": "0x" + "a1" * 20})
    assert again["approved"] is True, again.get("denial_reason")


@pytest.mark.parametrize("amount", ["NaN", "nan", float("nan"), "inf", 10 ** 400, "1e400"])
def test_an_approve_amount_that_is_not_a_finite_number_is_refused(amount):
    """[control] NaN passed the cap; an overflowing integer raised."""
    refused = allowance_violation("stablecoin", {"action": "approve", "amount": amount}, CAPPED)
    assert refused, amount


def test_a_cap_that_is_not_a_finite_number_allows_no_approve():
    """[control] An infinite cap allowed any amount."""
    refused = allowance_violation("tokenize", {"action": "approve", "amount": 5},
                                  {"security": {"platform_allowance_cap": "inf"}})
    assert refused


def test_an_approve_within_the_cap_is_kept():
    """[guard]"""
    assert allowance_violation("stablecoin", {"action": "approve", "amount": "100"}, CAPPED) is None


async def test_tokenize_approves_in_the_token_s_own_units(monkeypatch):
    """[control] 100 of a 6-decimal token was approved as 100 * 10**18 raw."""
    from runtime.blockchain.tokenization import Tokenization

    approved = {}

    class _Fn:
        def __init__(self, value=None, args=()):
            self._value, self._args = value, args

        def call(self):
            return self._value

        def build_transaction(self, tx):
            return {**tx, "args": self._args}

    class _Functions:
        def decimals(self):
            return _Fn(6)

        def approve(self, spender, amount):
            approved["amount"] = amount
            return _Fn(args=(spender, amount))

    contract = types.SimpleNamespace(functions=_Functions())
    tok = Tokenization({"blockchain": {"rpc_url": "http://node", "paymaster_private_key": "0x" + "11" * 32,
                                       "platform_wallet": "0x" + "c3" * 20, "chain_id": 84532}})
    tok._web3 = types.SimpleNamespace(eth=types.SimpleNamespace(
        contract=lambda address, abi: contract, gas_price=1,
        get_transaction_count=lambda _a: 0,
        send_raw_transaction=lambda raw: b"\x01" * 32))
    monkeypatch.setattr(type(tok), "web3", property(lambda self: self._web3), raising=False)

    class _Signer:
        def sign_transaction(self, tx):
            return types.SimpleNamespace(raw_transaction=b"raw")

    async def signer(_action):
        return _Signer()

    async def receipt(_tx_hash, _action):
        return {"status": 1}
    monkeypatch.setattr(tok, "_platform_signer", signer)
    monkeypatch.setattr(tok, "_receipt", receipt)
    out = await tok._approve({"contract_address": "0x" + "d4" * 20, "spender": "0x" + "e5" * 20,
                              "amount": "100"})
    assert approved.get("amount") == 100 * 10 ** 6, (approved, out)
