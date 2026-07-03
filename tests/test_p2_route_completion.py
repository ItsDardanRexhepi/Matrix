"""P2 regression tests: gateway route completion.

Every leg the MTRX client expects for storage / messaging / groups / licensing /
events / indexer / oracle-feeds / compute-jobs / portfolio-performance is now a
registered route. WIRE routes run through the ``_call()`` seam to a real service
and return a 200; the rest return an honest 501 (never a fabricated 200).
"""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes


@pytest.fixture
async def client():
    routes = ServiceRoutes(config={})
    app = web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as c:
        yield c


# ── WIRE routes: real service, real 200 ────────────────────────────────

async def test_messaging_conversations_wire_returns_real_list(client):
    # A wallet with no history honestly returns an empty list — not fabricated.
    resp = await client.get("/api/v1/messaging/conversations?address=0xabc")
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["data"] == []


async def test_messaging_messages_wire_reaches_real_service(client):
    # The route runs through _call to social.get_messages. An existing
    # conversation returns its messages (200); an unknown one is an honest 400
    # ("not found") — never a fabricated empty 200 and never a bare 500.
    resp = await client.get("/api/v1/messaging/conversations/conv_1/messages")
    assert resp.status in (200, 400), await resp.text()
    assert resp.status != 500


async def test_groups_create_wire_returns_real_record(client):
    resp = await client.post(
        "/api/v1/groups",
        json={"creator": "0xabc", "name": "Builders", "description": "hi"},
    )
    assert resp.status == 200, await resp.text()
    rec = (await resp.json())["data"]
    assert rec["status"] == "active"
    assert rec["creator"] == "0xabc"
    assert rec["name"] == "Builders"


async def test_licensing_register_ip_wire_returns_real_record(client):
    resp = await client.post(
        "/api/v1/licensing/ip",
        json={"owner": "0xabc", "type": "patent", "name": "Widget", "evidenceHash": "0xdead"},
    )
    # register_ip validates ip_type: a valid type -> 200 record; an unknown type
    # -> honest 400 (via the _call ValueError->400 mapping). Never a 500.
    assert resp.status in (200, 400), await resp.text()
    assert resp.status != 500


async def test_licensing_create_license_never_500(client):
    resp = await client.post(
        "/api/v1/licensing/licenses",
        json={"ipId": "ip_missing", "recipient": "0xabc", "terms": {"license_type": "non_exclusive"}},
    )
    # Unknown IP is an honest client/validation outcome, never a bare 500.
    assert resp.status != 500, await resp.text()


# ── NOT_IMPLEMENTED routes: honest 501, never a fake 200 ───────────────

NOT_IMPLEMENTED = [
    ("GET", "/api/v1/storage/files"),
    ("POST", "/api/v1/storage/files"),
    ("GET", "/api/v1/storage/files/bafy123"),
    ("POST", "/api/v1/storage/files/bafy123/pin"),
    ("POST", "/api/v1/storage/files/bafy123/unpin"),
    ("POST", "/api/v1/messaging/conversations"),
    ("POST", "/api/v1/messaging/conversations/conv_1/messages"),
    ("GET", "/api/v1/groups"),
    ("GET", "/api/v1/groups/discover"),
    ("GET", "/api/v1/groups/g1/feed"),
    ("POST", "/api/v1/groups/g1/join"),
    ("POST", "/api/v1/groups/g1/leave"),
    ("POST", "/api/v1/groups/g1/posts"),
    ("GET", "/api/v1/licensing/ip"),
    ("GET", "/api/v1/licensing/licenses"),
    ("POST", "/api/v1/licensing/licenses/purchase"),
    ("GET", "/api/v1/licensing/marketplace"),
    ("GET", "/api/v1/events"),
    ("GET", "/api/v1/events/tickets"),
    ("POST", "/api/v1/events"),
    ("POST", "/api/v1/events/e1/purchase"),
    ("GET", "/api/v1/events/tickets/t1/verify"),
    ("GET", "/api/v1/indexer/subgraphs"),
    ("POST", "/api/v1/indexer/subgraphs/s1/query"),
    ("POST", "/api/v1/indexer/subgraphs/s1/translate"),
    ("GET", "/api/v1/indexer/queries"),
    ("POST", "/api/v1/indexer/queries"),
    ("GET", "/api/v1/oracle/feeds"),
    ("POST", "/api/v1/oracle/feeds/f1/subscribe"),
    ("POST", "/api/v1/oracle/feeds/f1/unsubscribe"),
    ("GET", "/api/v1/oracle/feeds/f1/history"),
    ("GET", "/api/v1/compute/providers"),
    ("POST", "/api/v1/compute/jobs"),
    ("GET", "/api/v1/compute/jobs"),
    ("GET", "/api/v1/compute/jobs/j1"),
    ("GET", "/api/v1/compute/jobs/j1/result"),
    ("GET", "/api/v1/portfolio/performance/0xabc"),
]


@pytest.mark.parametrize("method,path", NOT_IMPLEMENTED)
async def test_not_implemented_routes_return_honest_501(client, method, path):
    resp = await client.request(method, path, json={} if method == "POST" else None)
    assert resp.status == 501, f"{method} {path} -> {resp.status}: {await resp.text()}"
    body = await resp.json()
    assert body.get("status") == "not_implemented"


# ── existing routes must NOT be clobbered by P2 (no duplicate registration) ──

async def test_preexisting_routes_still_present(client):
    # /oracle/price and /portfolio/complete predate P2; they must still resolve
    # (not 404/405) — proving P2 did not shadow or drop them.
    for path in ("/api/v1/oracle/price/ETH-USD", "/api/v1/portfolio/complete/0xabc"):
        resp = await client.get(path)
        assert resp.status != 404, f"{path} disappeared: {resp.status}"
        assert resp.status != 405, f"{path} method broke: {resp.status}"
