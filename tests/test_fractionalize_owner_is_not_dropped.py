"""§CD sibling pass over NEW-89: an authorization input the route required and dropped.

`POST /api/v1/nft/fractionalize` demanded `owner` from the caller and then never
forwarded it — `nft_services.fractionalize` had no owner parameter and performed
no ownership check, so the route advertised an authorization input that governed
nothing. That is the same DROPPED-INTENT shape NEW-89 refused in four sibling
routes, left standing in a handler NEW-89 itself edited.
"""

from __future__ import annotations

import inspect

import pytest

from runtime.blockchain.services.nft_services.service import NFTService


def _service() -> NFTService:
    return NFTService({})


def test_the_service_accepts_an_owner():
    sig = inspect.signature(NFTService.fractionalize)
    assert "owner" in sig.parameters, "the route's authorization input must reach the service"


def test_the_route_forwards_the_owner():
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "gateway" / "service_routes.py"
    text = src.read_text(encoding="utf-8")
    handler = text.split("async def _handle_nft_fractionalize", 1)[1].split("async def ", 1)[0]
    assert "owner=" in handler, "the handler must forward the owner it requires"
    assert "current_request_security" in handler, "the authenticated wallet must win over the body"


async def test_an_unconfigured_chain_reports_the_owner_it_was_given():
    """The refusal still names who asked — a fractionalisation is never attributed to nobody."""
    result = await _service().fractionalize(
        collection="0xTEST_COLLECTION", token_id=1, fractions=10,
        price_per_fraction=1.0, owner="0xTEST_A")
    assert result.get("status") != "ok"
    assert "0xTEST_A" in repr(result), "the owner reaches the record even when the chain is absent"


async def test_a_caller_who_is_not_the_token_owner_is_refused(monkeypatch):
    """With a readable chain, the on-chain owner decides."""
    svc = _service()
    monkeypatch.setattr(type(svc._web3), "available", property(lambda self: True), raising=False)
    monkeypatch.setattr(svc._web3, "is_placeholder", lambda _v: False, raising=False)

    async def owner_of(_collection, _token_id):
        return "0xTEST_REAL_OWNER"

    monkeypatch.setattr(svc, "_owner_of", owner_of)
    refused = await svc.fractionalize(collection="0xC", token_id=1, fractions=10,
                                      price_per_fraction=1.0, owner="0xTEST_IMPOSTOR")
    assert refused.get("error") == "not_token_owner"

    allowed = await svc.fractionalize(collection="0xC", token_id=1, fractions=10,
                                      price_per_fraction=1.0, owner="0xtest_real_owner")
    assert allowed.get("status") == "fractionalized"
    assert allowed.get("owner") == "0xtest_real_owner"
