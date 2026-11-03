"""The public feed is streamed live: each row it stores reaches
GET /social/feed/stream, and nothing it refuses does.

README.md's feed bullet says the feed's events are "ranked and streamed live",
and web/social.html shows "Live" once its EventSource connects. The stream
handler subscribed to the broadcaster's `feed.new_event`, and nothing in the
tree published that event: a settled public swap was stored and served by
/social/feed, and a subscriber to the stream received nothing, ever, only
keep-alives. The engine now publishes each row it stores, as it stores it, on
the broadcaster the gateway attaches, under the one event name the handler
subscribes to.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile

import pytest

from runtime.db.database import Database
from runtime.social.feed_engine import SocialFeedEngine

ACTOR = "0x" + "a" * 40
#: The event GET /social/feed/stream subscribes to.
FEED_STREAM_EVENT = "feed.new_event"


def test_the_engine_publishes_under_the_event_the_stream_subscribes_to():
    from runtime.social import feed_engine

    assert feed_engine.FEED_STREAM_EVENT == FEED_STREAM_EVENT


@pytest.fixture
async def engine_and_subscriber(tmp_path):
    from gateway.event_broadcaster import EventBroadcaster

    broadcaster = EventBroadcaster()
    sub = await broadcaster.register(remote_ip="1.2.3.4", types={FEED_STREAM_EVENT})
    db = Database({"database": {"path": str(tmp_path / "feed.db")}})
    engine = SocialFeedEngine(db)
    engine.attach_broadcaster(broadcaster)
    yield engine, sub
    await broadcaster.unregister(sub)
    await db.close()


def _queued(sub) -> list:
    out = []
    while not sub.queue.empty():
        out.append(sub.queue.get_nowait())
    return out


async def test_a_stored_row_is_published_to_the_stream(engine_and_subscriber):
    engine, sub = engine_and_subscriber
    event = await engine.ingest(action="swap_tokens", actor=ACTOR,
                                detail={"service": "dex", "params": {"amount_in": 1}},
                                tx_hash="0x" + "ab" * 32)
    queued = _queued(sub)
    assert len(queued) == 1, f"a stored row reached {len(queued)} stream events"
    payload = queued[0].payload
    assert queued[0].type == FEED_STREAM_EVENT
    assert payload["id"] == event.id and payload["summary"] == event.summary
    assert payload["icon"] and payload["category"], payload
    assert "params" not in payload["detail"], payload


async def test_a_refused_item_is_not_published_to_the_stream(engine_and_subscriber):
    engine, sub = engine_and_subscriber
    await engine.ingest(action="send_message", actor=ACTOR, detail={
        "service": "social", "params": {"proof_data": {"visibility": "followers"}}})
    await engine.ingest(action="ipfs_pin", actor=ACTOR, detail={"service": "privacy"})
    await engine.ingest(action="message_encrypt", actor=ACTOR, detail={"service": "social"})
    assert _queued(sub) == []


async def test_a_publish_failure_does_not_fail_the_ingest(tmp_path):
    class _Broken:
        def publish_dict(self, *_a, **_k):
            raise RuntimeError("broadcaster down")

    db = Database({"database": {"path": str(tmp_path / "feed.db")}})
    engine = SocialFeedEngine(db)
    engine.attach_broadcaster(_Broken())
    event = await engine.ingest(action="swap_tokens", actor=ACTOR, detail={"service": "dex"})
    stored = await engine.get_feed(limit=5)
    await db.close()
    assert event.summary and [e.id for e in stored] == [event.id]


sys.path.insert(0, "tests")


async def test_the_gateway_streams_a_stored_row_to_a_client():
    """End to end: the gateway's own feed engine, its own broadcaster and
    GET /social/feed/stream, read as an EventSource reads it."""
    from aiohttp.test_utils import TestClient, TestServer

    from gateway.server import GatewayServer
    from test_route_sweep import SWEEP_CONFIG

    scratch = tempfile.mkdtemp(prefix="the-matrix-feed-live-")
    server = GatewayServer({**SWEEP_CONFIG, "memory_dir": scratch,
                            "database": {"path": f"{scratch}/f.db"}})
    async with TestClient(TestServer(server.create_app())) as client:
        assert server.social_feed_engine is not None, "premise: the gateway has its feed"
        resp = await client.get("/social/feed/stream")
        assert resp.status == 200
        for _ in range(100):
            if server.event_broadcaster._subs:
                break
            await asyncio.sleep(0.01)
        event = await server.social_feed_engine.ingest(
            action="swap_tokens", actor=ACTOR, detail={"service": "dex"})
        chunk = b""
        try:
            while b"event: feed" not in chunk:
                chunk = await asyncio.wait_for(resp.content.readuntil(b"\n\n"), 3)
        except asyncio.TimeoutError:
            pytest.fail("a row the feed stored never reached the stream")
        finally:
            resp.close()
    data = json.loads(chunk.decode().split("data: ", 1)[1])
    assert data["type"] == FEED_STREAM_EVENT and data["payload"]["id"] == event.id, data
