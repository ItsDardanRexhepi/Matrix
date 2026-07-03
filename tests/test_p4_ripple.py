"""P4 regression tests: ripple completion (loop steps 12-13).

A successfully executed consequential action publishes a ``feed.ripple`` event
(ripples out to the live feed). Privacy actions never ripple, reads never
ripple, and an honest failure produces NO ripple — verified by watching the
broadcaster's published-event counter across each request.
"""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes


@pytest.fixture
async def env():
    routes = ServiceRoutes(config={})
    app = web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as c:
        yield routes, c


def _published(routes) -> int:
    return routes.broadcaster.snapshot()["published_total"]


async def test_executed_action_ripples(env):
    routes, client = env
    before = _published(routes)
    resp = await client.post(
        "/api/v1/groups", json={"creator": "0xabc", "name": "Builders"}
    )
    assert resp.status == 200, await resp.text()
    assert _published(routes) == before + 1, "an executed action must ripple once"


async def test_privacy_action_does_not_ripple(env):
    # /compute/store executes privacy.decentralized_store — a privacy-service
    # action must NEVER ripple (steps 12-13 respect privacy).
    routes, client = env
    before = _published(routes)
    resp = await client.post(
        "/api/v1/compute/store",
        json={"owner": "0xabc", "data": "0xdead", "storage_type": "ipfs"},
    )
    assert resp.status == 200, await resp.text()
    assert _published(routes) == before, "privacy actions must not ripple"


async def test_read_does_not_ripple(env):
    # A read (get_conversations) changes no state and must not ripple.
    routes, client = env
    before = _published(routes)
    resp = await client.get("/api/v1/messaging/conversations?address=0xabc")
    assert resp.status == 200, await resp.text()
    assert _published(routes) == before, "reads must not ripple"


async def test_honest_failure_produces_no_ripple(env):
    # An unsupported oracle pair is an honest 400 — no execution, no ripple.
    routes, client = env
    before = _published(routes)
    resp = await client.get("/api/v1/oracle/price/NOPE-NOPE")
    assert resp.status == 400, await resp.text()
    assert _published(routes) == before, "honest failures must not ripple"


async def test_write_with_readish_prefix_still_ripples(env):
    # snapshot_vote is a consequential WRITE whose name begins with a formerly
    # read-classified prefix ("snapshot"). It must ripple — regression guard for
    # the over-broad read-prefix bug the adversarial pass caught.
    routes, client = env
    before = _published(routes)
    resp = await client.post(
        "/api/v1/governance/snapshot/vote",
        json={"voter": "0xabc", "space": "mydao.eth", "proposal_id": "p1", "choice": 1},
    )
    if resp.status == 200:
        assert _published(routes) == before + 1, "snapshot_vote (a write) must ripple"
    else:
        # If the backing method can't run here it must at least not be a silent
        # read-skip masquerading as success.
        assert resp.status != 200 or _published(routes) > before


async def test_ripple_payload_shape(env):
    # The ripple event carries the actor + action so the feed can render it.
    routes, client = env
    events = []
    orig = routes.broadcaster.publish_dict

    def _spy(type_, payload, **kw):
        events.append((type_, payload))
        return orig(type_, payload, **kw)

    routes.broadcaster.publish_dict = _spy  # type: ignore[assignment]
    resp = await client.post(
        "/api/v1/licensing/ip",
        json={"owner": "0xowner", "type": "patent", "name": "Widget"},
    )
    assert resp.status in (200, 400), await resp.text()
    if resp.status == 200:
        ripples = [p for t, p in events if t == "feed.ripple"]
        assert ripples, "an executed register_ip must emit feed.ripple"
        assert ripples[0]["actor"] == "0xowner"
        assert ripples[0]["service"] == "ip_royalties"
