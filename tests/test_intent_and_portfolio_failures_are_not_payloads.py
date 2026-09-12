"""An exception is not a response body: /intent/resolve, /intent/execute and
/portfolio/complete.

RUN-5 and RUN-6 removed the `except Exception as e: result = {..., "message":
str(e)}` shape from their siblings — /portfolio/positions logs the reason and
answers a fixed 503; /intent/summary answers an explicit 501. The three handlers
here kept it, and one more copy lived INSIDE IntentResolver.resolve, which caught
everything and returned `{"status": "error", "message": str(exc)}` itself — so
fixing only the handler's `except` would have left the leak in place.

What RUN-4's `_ok` already did, and is NOT re-claimed here: an inner
`status: error|unavailable` no longer reads as HTTP 200 (422 / 503). What it could
not do is keep the exception text out of the body, or tell a server fault from a
caller's malformed input — an internal failure answered 422 "your request was
unprocessable", and a caller's `amount: "abc"` answered the same 422 with
Python's own `could not convert string to float` in it.

Why the route sweep never saw it: tests/test_route_sweep.py posts one generic body
with no `plan_id`, so /intent/execute answered its 400 for a missing field and
never reached the `AttributeError` — IntentResolver has no `execute` method.
"""

from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes

SECRET = "SECRET-upstream https://user:hunter2@rpc.internal:8545"
WALLET = "0x" + "a" * 40


@pytest.fixture
async def client():
    routes = ServiceRoutes(config={})
    app = web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as c:
        yield c


def _no_leak(text: str) -> None:
    for shape in ("SECRET", "hunter2", "has no attribute", "Traceback",
                  "could not convert", "IntentResolver", "object is not"):
        assert shape not in text, f"internal detail {shape!r} reached the client: {text}"


# ── /intent/execute ──────────────────────────────────────────────────────

async def test_intent_execute_is_an_honest_501_not_an_attribute_error(client):
    resp = await client.post("/api/v1/intent/execute",
                             json={"plan_id": "p-1", "wallet": WALLET})
    text = await resp.text()
    assert resp.status == 501, f"{resp.status}: {text}"
    _no_leak(text)
    body = json.loads(text)
    assert body["status"] == "not_implemented"


# ── /intent/resolve ──────────────────────────────────────────────────────

async def test_a_failure_inside_the_resolver_is_a_redacted_5xx(client, monkeypatch):
    """The resolver's OWN except used to return str(exc) — the handler never saw
    an exception to redact."""
    from runtime.blockchain.protocol_abstraction import defi_router

    async def boom(self, *a, **kw):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(defi_router.DeFiRouter, "get_best_swap_route", boom)
    resp = await client.post("/api/v1/intent/resolve", json={
        "intent": "swap 1 ETH for USDC",
        "entities": {"asset": "ETH", "amount": 1, "token_out": "USDC"}})
    text = await resp.text()
    assert 500 <= resp.status < 600, (
        f"{resp.status}: a server-side failure answered as if the request were "
        f"at fault (or as success): {text}")
    _no_leak(text)
    assert "ref" in json.loads(text)


async def test_a_resolver_that_cannot_be_built_is_a_redacted_5xx(client, monkeypatch):
    from runtime.blockchain.protocol_abstraction import intent_resolver

    def boom(self, config):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(intent_resolver.IntentResolver, "__init__", boom)
    resp = await client.post("/api/v1/intent/resolve", json={"intent": "swap"})
    text = await resp.text()
    assert 500 <= resp.status < 600, f"{resp.status}: {text}"
    _no_leak(text)


@pytest.mark.parametrize("body", [
    {"intent": "swap 1 ETH", "entities": {"amount": "abc"}},
    {"intent": "swap 1 ETH", "entities": ["not", "a", "dict"]},
    {"intent": 42},
])
async def test_malformed_caller_input_is_a_400_without_python_in_it(client, body):
    resp = await client.post("/api/v1/intent/resolve", json=body)
    text = await resp.text()
    assert resp.status == 400, f"{resp.status}: {text}"
    _no_leak(text)


async def test_a_resolvable_intent_still_resolves(client):
    resp = await client.post("/api/v1/intent/resolve", json={
        "intent": "swap 1 ETH for USDC",
        "entities": {"asset": "ETH", "amount": 1, "token_out": "USDC"}})
    assert resp.status == 200, await resp.text()
    data = (await resp.json())["data"]
    assert data["status"] == "ok" and data["steps"]


async def test_an_unresolvable_intent_is_still_an_answer(client):
    """`unresolved` is a domain outcome the caller asked about, not a fault."""
    resp = await client.post("/api/v1/intent/resolve", json={"intent": "xyzzy"})
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["data"]["status"] == "unresolved"


# ── /portfolio/complete ──────────────────────────────────────────────────

async def test_portfolio_complete_failure_is_a_fixed_503(client, monkeypatch):
    from runtime.blockchain.protocol_abstraction import data_aggregator

    async def boom(self, wallet):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(data_aggregator.DataAggregator, "get_user_portfolio", boom)
    resp = await client.get(f"/api/v1/portfolio/complete/{WALLET}")
    text = await resp.text()
    assert resp.status == 503, f"{resp.status}: {text}"
    _no_leak(text)


async def test_portfolio_complete_still_serves_a_portfolio(client):
    resp = await client.get(f"/api/v1/portfolio/complete/{WALLET}")
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["data"]["wallet"] == WALLET
