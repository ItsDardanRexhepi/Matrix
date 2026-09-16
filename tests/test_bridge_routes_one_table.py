"""The bridge's two entrances are one table.

/bridge/v1/* is reachable directly on the HTTP router and, for an operator,
through POST /api/v1/batch. The two lists were written separately:
BridgeRoutes.register_routes had its add_* calls and
ServiceRoutes._build_batch_route_map had its own copy. e1232ca removed
/bridge/v1/push/register from the batch copy when its handler was deleted; P1-6
brought the handler back on the router and nobody re-added it to the copy, so
the same call succeeded direct and answered 404 "No route" through batch.

Both entrances now read BridgeRoutes.route_specs(). The test derives the live
bridge routes from the router, so it does not depend on either list.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time

sys.path.insert(0, "tests")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from gateway.server import GatewayServer  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402


def _server() -> GatewayServer:
    scratch = tempfile.mkdtemp(prefix="the-matrix-bridge-table-")
    return GatewayServer({**SWEEP_CONFIG, "memory_dir": scratch, "database": {"path": f"{scratch}/b.db"}})


def _live_bridge_routes(app) -> set[tuple[str, str]]:
    out = set()
    for route in app.router.routes():
        info = route.resource.get_info() if route.resource else {}
        path = info.get("path") or info.get("formatter") or ""
        if path.startswith("/bridge/v1/") and route.method != "HEAD":
            out.add((route.method, path))
    return out


def _concrete(path: str) -> str:
    return path.replace("{component_id}", "contract_conversion")


async def test_every_bridge_route_answers_the_same_through_batch_as_direct():
    """Same request, both entrances, same status — derived from the router."""
    server = _server()
    app = server.create_app()
    live = sorted(_live_bridge_routes(app))
    assert ("POST", "/bridge/v1/push/register") in live and len(live) >= 12, live
    async with TestClient(TestServer(app)) as client:
        direct = {}
        for method, path in live:
            url = _concrete(path) + ("?session_id=table-conv" if method == "GET" else "")
            kwargs = {} if method == "GET" else {"json": {"session_id": "table-conv"}}
            resp = await client.request(method, url, **kwargs)
            await resp.read()
            direct[(method, path)] = resp.status
        requests = [
            {"id": f"{m} {p}", "method": m,
             "path": _concrete(p) + ("?session_id=table-conv" if m == "GET" else ""),
             "body": None if m == "GET" else {"session_id": "table-conv"}}
            for m, p in live
        ]
        resp = await client.post("/api/v1/batch", json={"requests": requests, "sequential": True})
        assert resp.status == 200, await resp.text()
        batched = {tuple(r["id"].split(" ", 1)): r for r in (await resp.json())["results"]}
    disagree = {f"{m} {p}": (direct[(m, p)], batched[(m, p)]["status"], batched[(m, p)].get("error"))
                for m, p in live if direct[(m, p)] != batched[(m, p)]["status"]}
    assert not disagree, f"direct vs batch (status, batch status, batch error): {disagree}"


async def test_a_batch_item_that_crashes_does_not_ship_the_exception_text():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        async def boom(request):
            raise RuntimeError("secret-host:5432 refused")
        routes = [r for r in _sr(server)._batch_routes if r[4] == "/bridge/v1/config"]
        assert routes, "the batch map has no /bridge/v1/config"
        idx = _sr(server)._batch_routes.index(routes[0])
        m, pat, names, _h, lit = routes[0]
        _sr(server)._batch_routes[idx] = (m, pat, names, boom, lit)
        resp = await client.post("/api/v1/batch", json={"requests": [
            {"id": "x", "method": "GET", "path": "/bridge/v1/config"}]})
        (item,) = (await resp.json())["results"]
        assert item["status"] == 500, item
        assert "secret-host" not in json.dumps(item), item


def _sr(server):
    """The ServiceRoutes instance create_app built for *server* (it keeps no
    attribute for it; its broadcaster is the server's event_broadcaster)."""
    import gc
    from gateway.service_routes import ServiceRoutes
    for o in gc.get_objects():
        if isinstance(o, ServiceRoutes) and o.broadcaster is server.event_broadcaster:
            return o
    raise AssertionError("ServiceRoutes instance not found")


async def test_push_register_through_batch_files_the_device_as_the_direct_call_does():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        body = {"session_id": "batch-device-conv", "push_token": "a" * 64}
        resp = await client.post("/api/v1/batch", json={"requests": [
            {"id": "push", "method": "POST", "path": "/bridge/v1/push/register", "body": body}]})
        assert resp.status == 200, await resp.text()
        (item,) = (await resp.json())["results"]
        assert item["status"] == 200, item
        assert item["body"].get("data", {}).get("registered") is True, item
        from runtime.notifications.token_store import PushTokenStore
        tokens = await PushTokenStore(server.react_loop.memory.db).tokens_for(session_id="batch-device-conv")
        assert "a" * 64 in tokens, tokens


async def test_a_batch_get_item_carries_its_query_to_the_handler():
    """wallet/status reads ?session_id: a link made for the conversation is
    visible through batch exactly as it is direct."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        direct = await client.get("/bridge/v1/wallet/status?session_id=q-conv")
        direct_body = await direct.json()
        resp = await client.post("/api/v1/batch", json={"requests": [
            {"id": "q", "method": "GET", "path": "/bridge/v1/wallet/status?session_id=q-conv"}]})
        (item,) = (await resp.json())["results"]
        assert item["status"] == direct.status, (item, direct.status)
        assert item["body"]["data"] == direct_body["data"], (item, direct_body)


async def test_a_batch_item_whose_handler_reads_the_request_mapping_answers_as_direct():
    """aiohttp's Request is a mapping; handlers in the batch map read it
    (``request.get("request_id")`` in the oracle's price-unavailable branch).
    The sub-request was not, so the documented 503 became a 500 through batch."""
    from runtime.blockchain.price_feed import PriceUnavailable

    class _NoSource:
        async def eth_usd(self):
            raise PriceUnavailable("no source reachable")

    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        _sr(server)._price_feed_inst = _NoSource()
        direct = await client.get("/api/v1/oracle/price/eth-usd")
        await direct.read()
        resp = await client.post("/api/v1/batch", json={"requests": [
            {"id": "p", "method": "GET", "path": "/api/v1/oracle/price/eth-usd"}]})
        (item,) = (await resp.json())["results"]
    assert direct.status == 503, direct.status
    assert item["status"] == direct.status, item
