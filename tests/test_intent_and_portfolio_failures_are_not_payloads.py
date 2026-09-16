"""An exception is not a response body, and a failure is not a default:
/intent/resolve, /intent/execute, /portfolio/complete and /portfolio/positions.

RUN-5 and RUN-6 removed the `except Exception as e: result = {..., "message":
str(e)}` shape from their siblings — /portfolio/positions logs the reason and
answers a fixed 503; /intent/summary answers an explicit 501. The handlers here
kept it, and one more copy lived INSIDE IntentResolver.resolve, which caught
everything and returned `{"status": "error", "message": str(exc)}` itself — so
fixing only the handler's `except` would have left the leak in place.

What RUN-4's `_ok` already did, and is NOT re-claimed here: an inner
`status: error|unavailable` no longer reads as HTTP 200 (422 / 503). What it could
not do is keep the exception text out of the body, or tell a server fault from a
caller's malformed input.

ROUND 2 OF THE SAME CLASS. Redacting the handlers' `except` was not enough,
because the failures that actually happen never reach it:

  * DeFiRouter / CrossChainRouter catch their own exceptions and return
    `{"status": "error"}` or `{"status": "not_configured"}`; resolve() then read
    `.get("gas_estimate_usd", 3.0)` / `.get("dex", "uniswap")` and answered 200
    with a plan built on those defaults.
  * DataAggregator.get_user_portfolio caught every exception, and a failed
    balance read, and returned — and CACHED — an all-zero portfolio that is
    byte-identical to an empty wallet. Beneath it, Web3Manager.get_balance_eth
    turned an RPC failure into 0.0 on its own. With no RPC at all, the route
    served the same zero portfolio as a 200. A non-zero balance was valued at a
    hardcoded $3,200 ETH.
  * resolve() compared the plan's value to the $100 confirmation threshold
    using that static price table, and an unknown asset priced at 0.0 — so an
    unpriceable transfer of any size skipped confirmation.

The controls below inject failures where they really occur — inside a router's
body, inside Web3Manager's RPC read, in the price feed — not by replacing the
method the handler calls, which would skip the very try/except at fault.

Why the route sweep never saw any of it: tests/test_route_sweep.py posts one
generic body with neither `intent` nor `plan_id`, so /intent/resolve and
/intent/execute both answered 400 for a missing field and never reached the
resolver.
"""

from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes
from runtime.blockchain.web3_manager import Web3Manager

SECRET = "SECRET-upstream https://user:hunter2@rpc.internal:8545"
WALLET = "0x" + "a" * 40

DEX_CONFIG = {"dexes": {"uniswap_v3": {}}}


@pytest.fixture(autouse=True)
def _fresh_web3():
    Web3Manager.reset_shared()
    yield
    Web3Manager.reset_shared()


def _client_for(config):
    routes = ServiceRoutes(config=config)
    app = web.Application()
    routes.register_routes(app)
    return TestClient(TestServer(app))


@pytest.fixture
async def client():
    async with _client_for({}) as c:
        yield c


@pytest.fixture
async def dex_client():
    async with _client_for(DEX_CONFIG) as c:
        yield c


def _no_leak(text: str) -> None:
    for shape in ("SECRET", "hunter2", "has no attribute", "Traceback",
                  "could not convert", "IntentResolver", "object is not"):
        assert shape not in text, f"internal detail {shape!r} reached the client: {text}"


class _Exploding(dict):
    """A table whose every read fails — a failure INSIDE the code that reads it."""

    def __init__(self, exc):
        super().__init__()
        self._exc = exc

    def get(self, *a, **kw):
        raise self._exc

    def __getitem__(self, key):
        raise self._exc


# ── /intent/execute ──────────────────────────────────────────────────────

async def test_intent_execute_is_an_honest_501_not_an_attribute_error(client):
    resp = await client.post("/api/v1/intent/execute",
                             json={"plan_id": "p-1", "wallet": WALLET})
    text = await resp.text()
    assert resp.status == 501, f"{resp.status}: {text}"
    _no_leak(text)
    body = json.loads(text)
    assert body["status"] == "not_implemented"


# ── /intent/resolve: a dependency that failed is not a plan ──────────────

SWAP = {"intent": "swap 1 ETH for USDC",
        "entities": {"asset": "ETH", "amount": 1, "token_out": "USDC"}}


async def test_a_failure_inside_the_router_body_is_a_503_not_a_default_plan(
        dex_client, monkeypatch):
    """The router's own try/except turns this into {"status": "error"}; resolve
    used to fill in $3.00 and "uniswap" and answer 200 ok."""
    from runtime.blockchain.protocol_abstraction import defi_router

    monkeypatch.setattr(defi_router, "_DEX_DEFAULTS",
                        _Exploding(ConnectionRefusedError(SECRET)))
    resp = await dex_client.post("/api/v1/intent/resolve", json=SWAP)
    text = await resp.text()
    assert resp.status == 503, f"{resp.status}: a failed route answered as a plan: {text}"
    _no_leak(text)
    body = json.loads(text)
    assert body["status"] == "unavailable"
    assert isinstance(body["error"], str) and body["error"]
    assert "plan_id" not in text and "estimated_cost_usd" not in text


@pytest.mark.parametrize("intent,entities", [
    ("swap 1 ETH for USDC", {"asset": "ETH", "amount": 1, "token_out": "USDC"}),
    ("deposit 5 USDC", {"asset": "USDC", "amount": 5}),
    ("borrow 5 USDC", {"asset": "USDC", "amount": 5, "collateral": "ETH"}),
    ("bridge 1 ETH", {"asset": "ETH", "amount": 1, "from_chain": "base",
                      "to_chain": "ethereum"}),
])
async def test_nothing_configured_is_a_503_not_an_invented_plan(client, intent, entities):
    """config {}: no DEX, no lending protocol, no bridge. There is nothing to plan
    with, and the answer used to be a 200 plan anyway."""
    resp = await client.post("/api/v1/intent/resolve",
                             json={"intent": intent, "entities": entities})
    text = await resp.text()
    assert resp.status == 503, f"{intent}: {resp.status}: {text}"
    body = json.loads(text)
    assert body["status"] == "unavailable" and body["reason"] == "not_configured", body
    assert "plan_id" not in body


async def test_an_unsupported_bridge_chain_is_the_callers_400():
    """CrossChainRouter reports this as status error too — but it is the
    caller's input, so it must not read as our outage either."""
    async with _client_for({"bridges": {"hop": {}}}) as c:
        resp = await c.post("/api/v1/intent/resolve", json={
            "intent": "bridge 1 ETH",
            "entities": {"asset": "ETH", "amount": 1, "from_chain": "mars",
                         "to_chain": "base"}})
        text = await resp.text()
        assert resp.status == 400, f"{resp.status}: {text}"
        _no_leak(text)
        resp = await c.post("/api/v1/intent/resolve", json={
            "intent": "bridge 1 ETH",
            "entities": {"asset": "ETH", "amount": 1, "from_chain": "base",
                         "to_chain": "base"}})
        assert resp.status == 400, await resp.text()


async def test_an_exception_inside_resolve_is_a_redacted_5xx(dex_client, monkeypatch):
    """An exception raised in resolve()'s own body (not a replaced method)
    reaches client_error and is redacted."""
    from runtime.blockchain.protocol_abstraction import intent_resolver

    monkeypatch.setattr(intent_resolver, "_TIME_ESTIMATES", _Exploding(RuntimeError(SECRET)))
    resp = await dex_client.post("/api/v1/intent/resolve", json=SWAP)
    text = await resp.text()
    assert 500 <= resp.status < 600, f"{resp.status}: {text}"
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


# ── the confirmation gate does not read a price nobody has ───────────────

@pytest.mark.parametrize("asset,amount", [
    ("UNKNOWNCOIN", 1_000_000),   # no price at all: used to be 0.0 -> no confirmation
    ("ETH", 0.02),                # static table says $64; nobody knows the real value
])
async def test_a_plan_whose_value_is_unknown_requires_confirmation(dex_client, asset, amount):
    resp = await dex_client.post("/api/v1/intent/resolve", json={
        "intent": f"swap {amount} {asset} for USDC",
        "entities": {"asset": asset, "amount": amount, "token_out": "USDC"}})
    assert resp.status == 200, await resp.text()
    data = (await resp.json())["data"]
    assert data["requires_confirmation"] is True, data
    assert data["value_usd"] is None, data


async def test_a_zero_amount_needs_no_price(dex_client):
    resp = await dex_client.post("/api/v1/intent/resolve", json={
        "intent": "swap ETH for USDC",
        "entities": {"asset": "ETH", "amount": 0, "token_out": "USDC"}})
    assert resp.status == 200, await resp.text()
    data = (await resp.json())["data"]
    assert data["requires_confirmation"] is False and data["value_usd"] == 0.0


# ── /intent/resolve: what still answers ──────────────────────────────────

@pytest.mark.parametrize("body", [
    {"intent": "swap 1 ETH", "entities": {"amount": "abc"}},
    {"intent": "swap 1 ETH", "entities": ["not", "a", "dict"]},
    {"intent": 42},
    {"intent": "swap ETH", "entities": {"amount": -5}},
])
async def test_malformed_caller_input_is_a_400_without_python_in_it(client, body):
    resp = await client.post("/api/v1/intent/resolve", json=body)
    text = await resp.text()
    assert resp.status == 400, f"{resp.status}: {text}"
    _no_leak(text)


async def test_a_configured_swap_resolves(dex_client):
    resp = await dex_client.post("/api/v1/intent/resolve", json=SWAP)
    assert resp.status == 200, await resp.text()
    data = (await resp.json())["data"]
    assert data["status"] == "ok" and data["steps"]
    assert data["protocols"] == ["Uniswap V3"], data


async def test_an_unresolvable_intent_is_still_an_answer(client):
    """`unresolved` is a domain outcome the caller asked about, not a fault."""
    resp = await client.post("/api/v1/intent/resolve", json={"intent": "xyzzy"})
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["data"]["status"] == "unresolved"


# ── /portfolio/complete and /portfolio/positions ─────────────────────────

PORTFOLIO_ROUTES = ("/api/v1/portfolio/complete/", "/api/v1/portfolio/positions/")


class _FakeEth:
    def __init__(self, get_balance):
        self.get_balance = get_balance


class _FakeW3:
    """Stands in for web3.Web3 so the REAL Web3Manager.get_balance_eth runs."""

    def __init__(self, get_balance):
        self.eth = _FakeEth(get_balance)

    @staticmethod
    def to_checksum_address(address):
        return address

    @staticmethod
    def from_wei(wei, unit):
        assert unit == "ether"
        return wei / 10**18


def _online_web3(get_balance):
    mgr = Web3Manager.get_shared({})
    mgr.available = True
    mgr.w3 = _FakeW3(get_balance)
    return mgr


def _price(monkeypatch, price=None, exc=None):
    from runtime.blockchain import price_feed

    async def eth_usd(self, *, now=None):
        if exc is not None:
            raise exc
        return {"price": price, "source": "test"}

    monkeypatch.setattr(price_feed.PriceFeed, "eth_usd", eth_usd)


@pytest.mark.parametrize("route", PORTFOLIO_ROUTES)
async def test_an_rpc_failure_is_a_503_not_an_empty_wallet(client, route, monkeypatch):
    def get_balance(_address):
        raise ConnectionRefusedError(SECRET)

    _online_web3(get_balance)
    _price(monkeypatch, 2000.0)
    # One request is enough here. Each request builds its own DataAggregator,
    # so a second request could not see a cached failure even if one were
    # cached; that is tested on a single aggregator below.
    resp = await client.get(route + WALLET)
    text = await resp.text()
    assert resp.status == 503, f"{resp.status}: {text}"
    _no_leak(text)
    assert "total_value_usd" not in text


@pytest.mark.parametrize("failure", ["balance_read_failed", "price_unavailable"])
async def test_one_aggregator_does_not_cache_a_failed_portfolio(monkeypatch, failure):
    """The non-caching claim, on the object that owns the cache: the same
    DataAggregator asked twice raises twice and stores no portfolio."""
    from runtime.blockchain.price_feed import PriceUnavailable
    from runtime.blockchain.protocol_abstraction.data_aggregator import DataAggregator

    reads = []

    def get_balance(address):
        reads.append(address)
        if failure == "balance_read_failed":
            raise ConnectionRefusedError(SECRET)
        return 10**18

    _online_web3(get_balance)
    _price(monkeypatch, exc=PriceUnavailable(SECRET))
    agg = DataAggregator({})
    for attempt in (1, 2):
        try:
            result = await agg.get_user_portfolio(WALLET)
        except Exception as exc:   # by name, so an older tree fails on behaviour
            assert type(exc).__name__ == "PortfolioUnavailable", repr(exc)
            assert exc.reason == failure, (attempt, exc.reason)
        else:
            pytest.fail(f"attempt {attempt} returned a portfolio for a failed "
                        f"{failure}: {result}")
    assert len(reads) == 2, "the second call did not read again"
    assert not [k for k in agg._cache if k.startswith("portfolio:")], agg._cache


@pytest.mark.parametrize("route", PORTFOLIO_ROUTES)
async def test_no_data_source_is_a_503_not_an_empty_wallet(client, route):
    """config {}: no RPC. Nothing was read, so nothing may be reported as $0."""
    resp = await client.get(route + WALLET)
    text = await resp.text()
    assert resp.status == 503, f"{resp.status}: {text}"
    assert "total_value_usd" not in text


@pytest.mark.parametrize("route", PORTFOLIO_ROUTES)
async def test_an_unpriceable_balance_is_a_503_not_a_static_price(client, route,
                                                                  monkeypatch):
    from runtime.blockchain.price_feed import PriceUnavailable

    _online_web3(lambda _a: 5 * 10**17)
    _price(monkeypatch, exc=PriceUnavailable(SECRET))
    resp = await client.get(route + WALLET)
    text = await resp.text()
    assert resp.status == 503, f"{resp.status}: {text}"
    _no_leak(text)


async def test_a_read_balance_is_valued_at_the_live_price(client, monkeypatch):
    _online_web3(lambda _a: 5 * 10**17)          # 0.5 ETH
    _price(monkeypatch, 2000.0)
    resp = await client.get("/api/v1/portfolio/complete/" + WALLET)
    assert resp.status == 200, await resp.text()
    data = (await resp.json())["data"]
    assert data["wallet"] == WALLET
    assert data["total_value_usd"] == 1000.0, data   # not 0.5 * a hardcoded 3200
    assert data["tokens"][0]["balance"] == 0.5


async def test_a_genuinely_empty_wallet_is_still_a_200(client, monkeypatch):
    """The RPC answered 0. That IS a portfolio, and needs no price."""
    _online_web3(lambda _a: 0)
    _price(monkeypatch, exc=AssertionError("an empty wallet needs no price"))
    resp = await client.get("/api/v1/portfolio/positions/" + WALLET)
    assert resp.status == 200, await resp.text()
    data = (await resp.json())["data"]
    assert data["total_value_usd"] == 0.0 and data["positions"]["tokens"] == []


async def test_portfolio_complete_exception_body_is_a_fixed_sentence(client, monkeypatch):
    """Whatever raises, the client gets the fixed sentence, never the text."""
    from runtime.blockchain.protocol_abstraction import data_aggregator

    def boom(self, *_args, **_kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(data_aggregator.DataAggregator, "__init__", boom)
    resp = await client.get(f"/api/v1/portfolio/complete/{WALLET}")
    text = await resp.text()
    assert resp.status == 503, f"{resp.status}: {text}"
    _no_leak(text)


# ── the root: a balance nobody read is not 0.0 ───────────────────────────

def test_get_balance_eth_raises_instead_of_returning_zero():
    from runtime.blockchain.web3_manager import BalanceUnavailable

    def get_balance(_address):
        raise ConnectionRefusedError(SECRET)

    mgr = _online_web3(get_balance)
    with pytest.raises(BalanceUnavailable) as info:
        mgr.get_balance_eth(WALLET)
    assert "SECRET" not in str(info.value)

    offline = Web3Manager({})
    with pytest.raises(BalanceUnavailable):
        offline.get_balance_eth(WALLET)

    assert _online_web3(lambda _a: 10**18).get_balance_eth(WALLET) == 1.0


def test_the_bridge_wallet_status_balance_is_none_when_the_read_failed():
    """gateway/bridge.py documents _lookup_balance_eth as "None if
    unavailable"; with get_balance_eth swallowing the failure it returned 0.0."""
    from gateway.bridge import BridgeRoutes

    def get_balance(_address):
        raise ConnectionRefusedError(SECRET)

    bridge = BridgeRoutes.__new__(BridgeRoutes)
    bridge._web3_manager = _online_web3(get_balance)
    assert bridge._lookup_balance_eth(WALLET) is None
