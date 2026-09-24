"""The portfolio's live ETH/USD read: one read per cache window, off the event
loop, and never for a wallet that is not an address.

540b991 made /portfolio/complete and /portfolio/positions value a non-zero
balance at a live quote, which was right, but it built a fresh
`PriceFeed(self._config)` inside every request. PriceFeed's 30 s cache lives on
the instance, so no request ever hit it. The /price route and the paymaster
route already shared one instance (ServiceRoutes._price_feed).

Worse, PriceFeed._default_chainlink was an `async def` that made synchronous
web3 HTTP calls, so every read held the gateway's event loop for its RPC round
trips. Before 540b991 the portfolio used a static table and made no call at
all, so the branch added a stall to every portfolio request.

Also, a wallet path segment that is not an address is the caller's input. web3
rejected it inside get_balance_eth's try, and the route answered 503
"unavailable right now".

These controls use the REAL PriceFeed._default_chainlink against a local
JSON-RPC server that answers slowly and counts calls. The only fake is the
balance read (a stand-in w3 under the real Web3Manager.get_balance_eth), and
the Coinbase fallback, which is made to fail so no test touches the network.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

pytest.importorskip("web3")

from gateway.service_routes import ServiceRoutes
from runtime.blockchain.web3_manager import Web3Manager

WALLET = "0x" + "a" * 40
FEED = "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70"
RPC_DELAY = 0.25
PORTFOLIO_ROUTES = ("/api/v1/portfolio/complete/", "/api/v1/portfolio/positions/")


class _SlowChainlinkRPC:
    """A JSON-RPC endpoint that answers a Chainlink aggregator slowly."""

    def __init__(self):
        from web3 import Web3

        decimals_sel = Web3.keccak(text="decimals()")[:4].hex().replace("0x", "")
        state = self
        self.calls = 0
        self._lock = threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                reqs = body if isinstance(body, list) else [body]
                out = []
                for q in reqs:
                    with state._lock:
                        state.calls += 1
                    time.sleep(RPC_DELAY)
                    if q["method"] == "eth_chainId":
                        result = "0x14a34"
                    elif q["method"] == "eth_call":
                        data = q["params"][0].get("data") or q["params"][0].get("input")
                        if data[2:10] == decimals_sel:
                            result = "0x" + (8).to_bytes(32, "big").hex()
                        else:
                            words = [1, 2000 * 10**8, 0, int(time.time()), 1]
                            result = "0x" + b"".join(w.to_bytes(32, "big") for w in words).hex()
                    else:
                        result = None
                    out.append({"jsonrpc": "2.0", "id": q["id"], "result": result})
                raw = json.dumps(out if isinstance(body, list) else out[0]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()


class _FakeEth:
    def __init__(self, get_balance):
        self.get_balance = get_balance


class _FakeW3:
    def __init__(self, get_balance):
        self.eth = _FakeEth(get_balance)

    @staticmethod
    def to_checksum_address(address):
        from web3 import Web3
        return Web3.to_checksum_address(address)

    @staticmethod
    def from_wei(wei, unit):
        return wei / 10**18


@pytest.fixture
def rpc():
    server = _SlowChainlinkRPC()
    yield server
    server.close()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    from runtime.blockchain import price_feed

    async def _coinbase_down(self):
        raise ConnectionError("no network in this test")

    monkeypatch.setattr(price_feed.PriceFeed, "_default_coinbase", _coinbase_down)
    Web3Manager.reset_shared()
    yield
    Web3Manager.reset_shared()


def _online(config, get_balance, rpc=None):
    mgr = Web3Manager.get_shared(config)
    mgr.available = True
    mgr.w3 = _FakeW3(get_balance)
    if rpc is not None:
        rpc.calls = 0   # building the manager may probe the RPC; count reads only
    return mgr


def _app(config):
    routes = ServiceRoutes(config=config)
    app = web.Application()
    routes.register_routes(app)

    async def unrelated(_request):
        return web.json_response({"ok": True})

    app.router.add_get("/unrelated", unrelated)
    return TestClient(TestServer(app))


def _config(rpc):
    return {"blockchain": {"rpc_url": rpc.url, "price_feeds": {"eth_usd": FEED}}}


async def test_repeated_portfolio_requests_read_the_price_once(rpc):
    config = _config(rpc)
    balance_reads = []
    _online(config, lambda a: balance_reads.append(a) or 10**18, rpc)
    async with _app(config) as client:
        resp = await client.get("/api/v1/portfolio/complete/" + WALLET)
        assert resp.status == 200, await resp.text()
        data = (await resp.json())["data"]
        assert data["tokens"][0]["price_source"] == "chainlink", data
        assert data["total_value_usd"] == 2000.0, data
        one_read = rpc.calls
        assert one_read > 0

        for route in PORTFOLIO_ROUTES * 2:
            resp = await client.get(route + WALLET)
            assert resp.status == 200, await resp.text()
        assert rpc.calls == one_read, (
            f"5 portfolio requests made {rpc.calls} price RPC calls; one read "
            f"is {one_read}. Every request built its own uncached PriceFeed.")
        assert len(balance_reads) == 5   # balances are still read per request


async def test_a_slow_price_read_does_not_stall_other_requests(rpc):
    """Client and server share one event loop here, so the stall is measured
    as the loop sees it: a ticker that wakes every 10 ms records the longest gap
    between its wake-ups while four portfolio requests and one unrelated
    request run. A synchronous RPC read inside the loop shows up as a gap at
    least one RPC_DELAY long."""
    config = _config(rpc)
    _online(config, lambda _a: 10**18, rpc)
    async with _app(config) as client:
        done = asyncio.Event()
        gaps = []

        async def ticker():
            last = time.perf_counter()
            while not done.is_set():
                await asyncio.sleep(0.01)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now

        async def portfolio():
            r = await client.get("/api/v1/portfolio/complete/" + WALLET)
            return r.status

        async def unrelated():
            await asyncio.sleep(0.05)
            r = await client.get("/unrelated")
            return r.status

        tick = asyncio.ensure_future(ticker())
        *statuses, other = await asyncio.gather(
            *(portfolio() for _ in range(4)), unrelated())
        done.set()
        await tick
        assert statuses == [200, 200, 200, 200] and other == 200
        worst = max(gaps)
        assert worst < RPC_DELAY / 2, (
            f"the event loop stalled {worst:.2f}s during the price read: the "
            f"read is running on the loop, and every other request waits")
        calls_for_four = rpc.calls

    # Four concurrent requests share one read, too: a fresh gateway serving a
    # single request makes the same number of RPC calls.
    Web3Manager.reset_shared()
    _online(config, lambda _a: 10**18, rpc)
    async with _app(config) as client:
        resp = await client.get("/api/v1/portfolio/complete/" + WALLET)
        assert resp.status == 200
    assert calls_for_four == rpc.calls, (
        f"4 concurrent requests made {calls_for_four} RPC calls; one request "
        f"makes {rpc.calls}")


async def test_a_price_read_that_hangs_is_bounded(monkeypatch, rpc):
    """A read that does not answer ends as price_unavailable (503) within the
    source timeout, not a request that holds the loop for the RPC's delay."""
    from runtime.blockchain import price_feed

    global RPC_DELAY
    # raising=False: on a tree with no such bound the read simply runs long,
    # and the elapsed-time assertion below is what fails.
    monkeypatch.setattr(price_feed, "_SOURCE_TIMEOUT_SECONDS", 0.3, raising=False)
    config = _config(rpc)
    _online(config, lambda _a: 10**18, rpc)
    old, RPC_DELAY = RPC_DELAY, 3.0
    try:
        async with _app(config) as client:
            started = time.perf_counter()
            resp = await client.get("/api/v1/portfolio/complete/" + WALLET)
            elapsed = time.perf_counter() - started
            text = await resp.text()
    finally:
        RPC_DELAY = old
    assert elapsed < 2.0, f"the unanswered read held the request {elapsed:.1f}s ({resp.status})"
    assert resp.status == 503, text


@pytest.mark.parametrize("route", PORTFOLIO_ROUTES)
@pytest.mark.parametrize("wallet", ["not-an-address", "0x1234", "0x" + "g" * 40])
async def test_a_wallet_that_is_not_an_address_is_the_callers_400(rpc, route, wallet):
    config = _config(rpc)
    reads = []
    _online(config, lambda a: reads.append(a) or 10**18, rpc)
    async with _app(config) as client:
        resp = await client.get(route + wallet)
        text = await resp.text()
    assert resp.status == 400, f"{resp.status}: {text}"
    body = json.loads(text)
    assert isinstance(body.get("error"), str) and body["error"]
    assert "Unknown format" not in text and "Traceback" not in text
    assert reads == [] and rpc.calls == 0, "a malformed wallet reached an RPC read"


@pytest.mark.parametrize("route", PORTFOLIO_ROUTES)
async def test_a_malformed_wallet_is_a_400_even_with_no_data_source(route):
    async with _app({}) as client:
        resp = await client.get(route + "not-an-address")
        assert resp.status == 400, await resp.text()
        resp = await client.get(route + WALLET)
        assert resp.status == 503, await resp.text()
