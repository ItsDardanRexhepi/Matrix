"""A fractionalisation is recorded only for the token's on-chain owner, read
and compared — never for a caller the record cannot name, never past an
owner nobody could read, and never with the read holding up the gateway.

THE DEFECTS (pre-existing on The Matrix ``main``), with the chain configured:

  * an empty ``owner`` skipped the ownership comparison and the record was
    made for nobody;
  * an ``ownerOf`` that could not be read (no such token, an address that is
    not an ERC-721, a failed RPC) returned "", which also skipped it, and the
    record's own disclosure said the owner "WAS read and checked";
  * on a dispatched action the ``owner`` was the request's params: naming the
    token's real owner passed the check whoever asked, because the method did
    not take the identity the dispatcher binds;
  * ``ownerOf`` was a synchronous JSON-RPC call on the event loop, so a slow
    node stalled every other request on the gateway.
"""
from __future__ import annotations

import asyncio
import inspect
import time

import pytest

from runtime.blockchain.services.nft_services.service import NFTService

REAL = "0x" + "a1" * 20
OTHER = "0x" + "b2" * 20


def _live(monkeypatch, owner_of=None, contract=None):
    svc = NFTService({})
    monkeypatch.setattr(type(svc._web3), "available", property(lambda self: True), raising=False)
    monkeypatch.setattr(svc._web3, "is_placeholder", lambda _v: False, raising=False)
    if owner_of is not None:
        monkeypatch.setattr(svc, "_owner_of", owner_of)
    if contract is not None:
        monkeypatch.setattr(svc._web3, "load_contract", lambda *_a, **_k: contract, raising=False)
    return svc


async def _real_owner(_collection, _token_id):
    return REAL


class _Contract:
    """An ERC-721 whose ownerOf answers *answer*, raises it, or sleeps first."""

    def __init__(self, answer=REAL, delay=0.0):
        self._answer, self._delay = answer, delay
        outer = self

        class _Call:
            def __init__(self, token_id):
                self.token_id = token_id

            def call(self):
                if outer._delay:
                    time.sleep(outer._delay)
                if isinstance(outer._answer, Exception):
                    raise outer._answer
                return outer._answer

        class _Functions:
            def ownerOf(self, token_id):   # noqa: N802 — the ABI's name
                return _Call(token_id)

        self.functions = _Functions()


async def _fractionalize(svc, **kw):
    args = dict(collection="0xC", token_id=7, fractions=10, price_per_fraction=1.0)
    args.update(kw)
    return await svc.fractionalize(**args)


async def test_no_owner_is_refused(monkeypatch):
    """[control] An empty owner skipped the comparison."""
    out = await _fractionalize(_live(monkeypatch, owner_of=_real_owner), owner="")
    assert out.get("error") == "owner_required", out


@pytest.mark.parametrize("failure", [ValueError("execution reverted"), ConnectionError("rpc down")])
async def test_an_owner_nobody_could_read_is_refused(monkeypatch, failure):
    """[control] An unreadable ownerOf read as "" and skipped the comparison."""
    out = await _fractionalize(_live(monkeypatch, contract=_Contract(failure)), owner=REAL)
    assert out.get("error") == "owner_unverifiable", out


async def test_the_dispatcher_s_caller_outranks_the_params_owner(monkeypatch):
    """[control] Naming the real owner in params passed for any caller."""
    assert "caller_identity" in inspect.signature(NFTService.fractionalize).parameters
    svc = _live(monkeypatch, owner_of=_real_owner)
    out = await _fractionalize(svc, owner=REAL, caller_identity=OTHER, caller_source="authenticated")
    assert out.get("error") == "not_token_owner", out
    ok = await _fractionalize(svc, owner="", caller_identity=REAL.upper().replace("0X", "0x"),
                              caller_source="authenticated")
    assert ok.get("status") != "error", ok


async def test_the_owner_read_does_not_hold_the_event_loop(monkeypatch):
    """[control] A 0.3 s ownerOf stopped every other task for 0.3 s."""
    svc = _live(monkeypatch, contract=_Contract(REAL, delay=0.3))
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.ensure_future(ticker())
    try:
        out = await _fractionalize(svc, owner=REAL)
    finally:
        task.cancel()
    assert out.get("status") != "error", out
    assert ticks >= 10, f"the loop ticked {ticks} times during a 0.3 s read"


async def test_the_owner_s_record_says_what_was_checked(monkeypatch):
    """[guard] The real owner is recorded, and the disclosure is true of it."""
    out = await _fractionalize(_live(monkeypatch, contract=_Contract(REAL)), owner=REAL)
    assert out.get("status") != "error", out
    assert "WAS read and checked" not in repr(out)
    assert "read" in out.get("disclosure", "").lower()
