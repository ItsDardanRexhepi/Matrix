"""
tests/test_batch_and_events.py
==============================

Covers the two cross-cutting endpoints added to ``ServiceRoutes`` for
the MTRX iOS ``MTRXPackager``:

* ``POST /api/v1/batch`` — multi-call dispatch.
* ``GET /api/v1/events/stream`` — Server-Sent Events fan-out.

Plus unit tests on the in-process ``EventBroadcaster`` itself.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.event_broadcaster import (
    BroadcastEvent,
    BroadcasterCapacityError,
    EventBroadcaster,
)
from gateway.service_routes import (
    BATCH_MAX_ITEMS,
    ServiceRoutes,
    _BatchSubRequest,
    _format_sse,
    _parse_int_csv,
    _parse_str_csv,
)


OFFLINE_CONFIG: dict = {
    "blockchain": {
        "rpc_url": "",
        "chain_id": 84532,
        "network": "base-sepolia",
    },
    "gateway": {"host": "127.0.0.1", "port": 0, "api_key": ""},
}


# ---------------------------------------------------------------------------
# Helpers — build a live aiohttp app with ServiceRoutes wired in
# ---------------------------------------------------------------------------


class _FakeService:
    """Minimal stand-in for any blockchain service."""

    def __init__(self, response: Any = None, raises: BaseException | None = None):
        self._response = response if response is not None else {"ok": True}
        self._raises = raises
        self.calls: list[dict] = []

    async def _record(self, name: str, **kwargs) -> Any:
        self.calls.append({"method": name, "kwargs": kwargs})
        if self._raises is not None:
            raise self._raises
        return self._response

    # The ServiceRoutes handlers call a handful of different method
    # names; we dispatch them all to ``_record`` so the test doesn't
    # need to care about the exact name.

    def __getattr__(self, name):  # pragma: no cover — simple forwarder
        async def _impl(**kwargs):
            return await self._record(name, **kwargs)
        return _impl


class _FakeRegistry:
    def __init__(self, services: dict[str, _FakeService]):
        self._services = services

    def get(self, name: str) -> _FakeService:
        if name not in self._services:
            raise KeyError(name)
        return self._services[name]


@pytest.fixture
async def app_client() -> TestClient:
    """Build an aiohttp app with ServiceRoutes + a fake ServiceRegistry."""

    services = {
        "contract_conversion": _FakeService({
            "status": "converted",
            "solidity": "contract Foo {}",
        }),
        "nft_services": _FakeService({"token_id": 1, "tx": "0xabc"}),
        "defi": _FakeService({"loan_id": "loan_1"}),
        "dashboard": _FakeService({"address": "0xabc", "balance": 1.23}),
        "insurance": _FakeService(raises=RuntimeError("oracle unreachable")),
    }
    registry = _FakeRegistry(services)

    routes = ServiceRoutes(OFFLINE_CONFIG)
    routes._registry = registry  # pre-seed so _get_registry() short-circuits

    app = web.Application()
    routes.register_routes(app)

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        yield client, routes, services
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# EventBroadcaster unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcaster_fans_out_to_matching_subscribers():
    bus = EventBroadcaster()
    s1 = await bus.register()
    s2 = await bus.register(components={3})
    s3 = await bus.register(components={99})

    event = BroadcastEvent(type="nft.minted", payload={"id": 1}, component=3)
    delivered = bus.publish(event)

    # Global (s1) + component-scoped matching (s2) = 2; s3 filtered out
    assert delivered == 2
    assert s1.queue.qsize() == 1
    assert s2.queue.qsize() == 1
    assert s3.queue.qsize() == 0

    await bus.unregister(s1)
    await bus.unregister(s2)
    await bus.unregister(s3)


@pytest.mark.asyncio
async def test_broadcaster_session_filter():
    bus = EventBroadcaster()
    mine = await bus.register(session_id="sess_a")
    yours = await bus.register(session_id="sess_b")

    bus.publish(BroadcastEvent(type="chat.token", payload={}, session_id="sess_a"))

    assert mine.queue.qsize() == 1
    assert yours.queue.qsize() == 0


@pytest.mark.asyncio
async def test_broadcaster_type_filter():
    bus = EventBroadcaster()
    prices = await bus.register(types={"price.update"})
    chats = await bus.register(types={"chat.token"})

    bus.publish(BroadcastEvent(type="price.update", payload={"pair": "ETH/USD"}))
    bus.publish(BroadcastEvent(type="chat.token", payload={"delta": "hi"}))

    assert prices.queue.qsize() == 1
    assert chats.queue.qsize() == 1


@pytest.mark.asyncio
async def test_broadcaster_drops_oldest_when_subscriber_overflows():
    bus = EventBroadcaster(max_queue_per_subscriber=2)
    sub = await bus.register()

    for i in range(5):
        bus.publish(BroadcastEvent(type="x", payload={"i": i}))

    # Queue stays at 2, but we've dropped 3.
    assert sub.queue.qsize() == 2
    assert sub.dropped >= 3


@pytest.mark.asyncio
async def test_broadcaster_iter_events_emits_keepalive_on_idle():
    bus = EventBroadcaster()
    sub = await bus.register()

    async def _consume():
        it = bus.iter_events(sub, keepalive_interval=0.05)
        first = await it.__anext__()
        return first

    first = await asyncio.wait_for(_consume(), timeout=1.0)
    assert first is None  # the keep-alive tick


def test_broadcaster_snapshot():
    bus = EventBroadcaster(max_queue_per_subscriber=64)
    snap = bus.snapshot()
    assert snap["subscribers"] == 0
    assert snap["published_total"] == 0
    assert snap["max_queue_per_subscriber"] == 64
    # New fields from the replay / cap rewrite
    assert snap["max_subscribers"] == 512
    assert snap["max_subscribers_per_ip"] == 8
    assert snap["replay_buffer"] == 0
    assert snap["replay_buffer_capacity"] == 512


# ---------------------------------------------------------------------------
# Broadcaster capacity limits (global + per-IP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcaster_enforces_global_cap():
    bus = EventBroadcaster(max_subscribers=2)
    s1 = await bus.register()
    s2 = await bus.register()
    with pytest.raises(BroadcasterCapacityError) as exc_info:
        await bus.register()
    assert exc_info.value.scope == "global"
    await bus.unregister(s1)
    await bus.unregister(s2)


@pytest.mark.asyncio
async def test_broadcaster_enforces_per_ip_cap():
    bus = EventBroadcaster(max_subscribers_per_ip=2)
    s1 = await bus.register(remote_ip="10.0.0.1")
    s2 = await bus.register(remote_ip="10.0.0.1")
    # Different IP still allowed
    s_other = await bus.register(remote_ip="10.0.0.2")
    with pytest.raises(BroadcasterCapacityError) as exc_info:
        await bus.register(remote_ip="10.0.0.1")
    assert exc_info.value.scope == "per_ip"
    await bus.unregister(s1)
    await bus.unregister(s2)
    await bus.unregister(s_other)


@pytest.mark.asyncio
async def test_broadcaster_records_remote_ip_on_subscriber():
    bus = EventBroadcaster()
    sub = await bus.register(remote_ip="192.168.1.42")
    assert sub.remote_ip == "192.168.1.42"
    await bus.unregister(sub)


# ---------------------------------------------------------------------------
# Broadcaster replay buffer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcaster_replay_returns_events_after_cursor():
    bus = EventBroadcaster(replay_buffer_size=16)
    # Publish a handful of events before anyone connects
    ids = []
    for i in range(5):
        evt = BroadcastEvent(type="x", payload={"i": i})
        bus.publish(evt)
        ids.append(evt.event_id)

    # Replay everything newer than index 1 → we expect 3 events back.
    tail = bus.replay_since(ids[1])
    assert [e.payload["i"] for e in tail] == [2, 3, 4]


@pytest.mark.asyncio
async def test_broadcaster_replay_unknown_cursor_returns_full_buffer():
    bus = EventBroadcaster(replay_buffer_size=4)
    for i in range(3):
        bus.publish(BroadcastEvent(type="x", payload={"i": i}))
    tail = bus.replay_since("unknown-cursor-id")
    assert len(tail) == 3


@pytest.mark.asyncio
async def test_broadcaster_replay_filters_via_matcher():
    bus = EventBroadcaster(replay_buffer_size=16)
    bus.publish(BroadcastEvent(type="a", payload={}, component=1))
    bus.publish(BroadcastEvent(type="b", payload={}, component=2))
    bus.publish(BroadcastEvent(type="c", payload={}, component=1))

    sub = await bus.register(components={1})
    tail = bus.replay_since("missing-cursor", matcher=sub)
    assert [e.type for e in tail] == ["a", "c"]
    await bus.unregister(sub)


@pytest.mark.asyncio
async def test_broadcaster_replay_buffer_bounded():
    bus = EventBroadcaster(replay_buffer_size=3)
    for i in range(10):
        bus.publish(BroadcastEvent(type="x", payload={"i": i}))
    assert bus.replay_buffer_size() == 3


# ---------------------------------------------------------------------------
# Metrics attachment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcaster_attach_metrics_emits_counters():
    calls: list[tuple[str, int]] = []

    class _FakeMetrics:
        def incr(self, name, value=1):
            calls.append((name, value))

        def set_gauge(self, name, value):
            calls.append((name, value))

    bus = EventBroadcaster()
    bus.attach_metrics(_FakeMetrics())

    sub = await bus.register()
    bus.publish(BroadcastEvent(type="x", payload={}))
    await bus.unregister(sub)

    emitted = {c[0] for c in calls}
    assert "sse.subscribers.opened" in emitted
    assert "sse.events.published" in emitted
    assert "sse.subscribers.closed" in emitted


# ---------------------------------------------------------------------------
# SSE framing helpers
# ---------------------------------------------------------------------------


def test_format_sse_multiline_payload_splits_data_lines():
    frame = _format_sse(
        event_type="price.update",
        data={"msg": "line1\nline2"},
        event_id="abcd",
    )
    text = frame.decode("utf-8")
    assert text.startswith("event: price.update\n")
    assert "id: abcd\n" in text
    assert text.endswith("\n\n")


def test_parse_int_csv_handles_junk():
    assert _parse_int_csv(None) is None
    assert _parse_int_csv("") is None
    assert _parse_int_csv("1,2,3") == [1, 2, 3]
    assert _parse_int_csv("1,foo,3") == [1, 3]
    assert _parse_int_csv(",,") is None


def test_parse_str_csv_trims_whitespace():
    assert _parse_str_csv("a, b ,c") == ["a", "b", "c"]
    assert _parse_str_csv("") is None
    assert _parse_str_csv(None) is None


# ---------------------------------------------------------------------------
# Batch dispatch route resolution
# ---------------------------------------------------------------------------


def test_resolve_batch_route_literal_path():
    routes = ServiceRoutes(OFFLINE_CONFIG)
    routes._build_batch_route_map()
    resolved = routes._resolve_batch_route("POST", "/api/v1/contracts/convert")
    assert resolved is not None
    _, match_info, literal = resolved
    assert match_info == {}
    assert literal == "/api/v1/contracts/convert"


def test_resolve_batch_route_path_params():
    routes = ServiceRoutes(OFFLINE_CONFIG)
    routes._build_batch_route_map()
    resolved = routes._resolve_batch_route("GET", "/api/v1/dashboard/0xabc123")
    assert resolved is not None
    _, match_info, _ = resolved
    assert match_info == {"address": "0xabc123"}


def test_resolve_batch_route_method_mismatch():
    routes = ServiceRoutes(OFFLINE_CONFIG)
    routes._build_batch_route_map()
    # /api/v1/contracts/convert is POST-only; GET must return None
    assert routes._resolve_batch_route("GET", "/api/v1/contracts/convert") is None


def test_resolve_batch_route_unknown_path():
    routes = ServiceRoutes(OFFLINE_CONFIG)
    routes._build_batch_route_map()
    assert routes._resolve_batch_route("POST", "/api/v1/nope") is None


# ---------------------------------------------------------------------------
# End-to-end /api/v1/batch behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_empty_list_returns_empty_results(app_client):
    client, _, _ = app_client
    resp = await client.post("/api/v1/batch", json={"requests": []})
    assert resp.status == 200
    body = await resp.json()
    assert body["results"] == []
    assert body["total_duration_ms"] == 0


@pytest.mark.asyncio
async def test_batch_rejects_missing_requests_key(app_client):
    client, _, _ = app_client
    resp = await client.post("/api/v1/batch", json={})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_batch_rejects_too_many_items(app_client):
    client, _, _ = app_client
    items = [
        {"id": str(i), "method": "POST",
         "path": "/api/v1/contracts/convert",
         "body": {"source_code": "x", "source_lang": "solidity"}}
        for i in range(BATCH_MAX_ITEMS + 1)
    ]
    resp = await client.post("/api/v1/batch", json={"requests": items})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_batch_parallel_happy_path(app_client):
    client, _, services = app_client
    resp = await client.post("/api/v1/batch", json={
        "requests": [
            {
                "id": "a",
                "method": "POST",
                "path": "/api/v1/contracts/convert",
                "body": {"source_code": "pragma solidity;", "source_lang": "solidity"},
            },
            {
                "id": "b",
                "method": "POST",
                "path": "/api/v1/nft/mint",
                "body": {"collection_id": "c1", "creator": "0xabc", "metadata": {}},
            },
        ],
    })
    assert resp.status == 200
    body = await resp.json()
    assert len(body["results"]) == 2
    ids = {r["id"]: r for r in body["results"]}
    assert ids["a"]["status"] == 200
    assert ids["b"]["status"] == 200
    assert ids["a"]["error"] is None
    assert ids["a"]["body"]["status"] == "ok"
    assert ids["a"]["body"]["data"]["solidity"] == "contract Foo {}"
    assert services["contract_conversion"].calls
    assert services["nft_services"].calls


@pytest.mark.asyncio
async def test_batch_sequential_aborts_on_failure(app_client):
    client, _, services = app_client
    resp = await client.post("/api/v1/batch", json={
        "sequential": True,
        "abort_on_failure": True,
        "requests": [
            {
                "id": "first",
                "method": "POST",
                "path": "/api/v1/contracts/convert",
                "body": {"source_code": "x", "source_lang": "solidity"},
            },
            {
                "id": "boom",
                "method": "POST",
                "path": "/api/v1/insurance/policy/create",
                "body": {
                    "holder": "0x1",
                    "policy_type": "parametric",
                    "coverage_amount": 1.0,
                    "premium": 0.1,
                },
            },
            {
                "id": "never",
                "method": "POST",
                "path": "/api/v1/nft/mint",
                "body": {"collection_id": "c1", "creator": "0x1", "metadata": {}},
            },
        ],
    })
    assert resp.status == 200
    body = await resp.json()
    results = {r["id"]: r for r in body["results"]}
    assert results["first"]["status"] == 200
    assert results["boom"]["status"] == 500
    assert results["never"]["status"] == 0
    assert results["never"]["error"] == "aborted"
    assert services["nft_services"].calls == []  # never reached


@pytest.mark.asyncio
async def test_batch_unknown_path_returns_404_entry(app_client):
    client, _, _ = app_client
    resp = await client.post("/api/v1/batch", json={
        "requests": [
            {"id": "nope", "method": "POST", "path": "/api/v1/does/not/exist", "body": {}},
        ],
    })
    body = await resp.json()
    assert body["results"][0]["status"] == 404
    assert "No route" in body["results"][0]["error"]


@pytest.mark.asyncio
async def test_batch_path_param_route(app_client):
    client, _, services = app_client
    services["dashboard"] = _FakeService({"balance": 4.2})
    resp = await client.post("/api/v1/batch", json={
        "requests": [
            {"id": "dash", "method": "GET",
             "path": "/api/v1/dashboard/0xabc", "body": None},
        ],
    })
    body = await resp.json()
    entry = body["results"][0]
    assert entry["status"] == 200
    assert entry["body"]["data"]["balance"] == 4.2


@pytest.mark.asyncio
async def test_batch_missing_path_returns_400(app_client):
    client, _, _ = app_client
    resp = await client.post("/api/v1/batch", json={
        "requests": [{"id": "x", "method": "POST"}],
    })
    body = await resp.json()
    assert body["results"][0]["status"] == 400
    assert "path" in body["results"][0]["error"].lower()


@pytest.mark.asyncio
async def test_batch_missing_required_field_surfaces_400(app_client):
    client, _, _ = app_client
    resp = await client.post("/api/v1/batch", json={
        "requests": [
            {"id": "bad", "method": "POST",
             "path": "/api/v1/contracts/convert",
             "body": {}},  # missing source_code + source_lang
        ],
    })
    body = await resp.json()
    assert body["results"][0]["status"] == 400
    assert "required" in body["results"][0]["error"].lower()


@pytest.mark.asyncio
async def test_batch_emits_completion_broadcast(app_client):
    client, routes, _ = app_client
    sub = await routes.broadcaster.register(types={"batch.completed"})
    resp = await client.post("/api/v1/batch", json={
        "requests": [
            {"id": "a", "method": "POST",
             "path": "/api/v1/contracts/convert",
             "body": {"source_code": "x", "source_lang": "solidity"}},
        ],
    })
    assert resp.status == 200
    await asyncio.sleep(0)  # let publish run
    assert sub.queue.qsize() == 1
    evt = await sub.queue.get()
    assert evt.type == "batch.completed"
    assert evt.payload["success_count"] == 1
    await routes.broadcaster.unregister(sub)


# ---------------------------------------------------------------------------
# SSE endpoint — end-to-end smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_stream_emits_hello_then_event(app_client):
    client, routes, _ = app_client

    async with client.get("/api/v1/events/stream") as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/event-stream")

        # read the hello frame
        hello = await asyncio.wait_for(resp.content.readuntil(b"\n\n"), timeout=2)
        assert b"event: stream.opened" in hello

        # publish an event and read it back
        routes.broadcaster.publish_dict(
            "price.update",
            {"pair": "ETH/USD", "price": 3456.78},
        )
        frame = await asyncio.wait_for(resp.content.readuntil(b"\n\n"), timeout=2)
        assert b"event: price.update" in frame
        assert b"ETH/USD" in frame


@pytest.mark.asyncio
async def test_event_stream_replays_on_last_event_id(app_client):
    client, routes, _ = app_client
    # Seed the replay buffer with one event BEFORE anyone connects.
    evt = BroadcastEvent(type="price.update", payload={"pair": "ETH/USD", "price": 1})
    routes.broadcaster.publish(evt)
    # The client reconnects with a cursor the broadcaster doesn't
    # recognise — it should still get the full buffer back on resume.
    async with client.get(
        "/api/v1/events/stream",
        headers={"Last-Event-ID": "nonexistent"},
    ) as resp:
        assert resp.status == 200
        replayed = await asyncio.wait_for(resp.content.readuntil(b"\n\n"), timeout=2)
        assert b"event: price.update" in replayed


@pytest.mark.asyncio
async def test_event_stream_rejects_when_capacity_full(app_client):
    client, routes, _ = app_client
    # Shrink the cap on the already-running broadcaster.
    routes.broadcaster._max_subscribers = 0
    resp = await client.get("/api/v1/events/stream")
    assert resp.status == 503
    # Restore the cap so the rest of the suite still works.
    routes.broadcaster._max_subscribers = 512


@pytest.mark.asyncio
async def test_event_stream_component_filter(app_client):
    client, routes, _ = app_client

    async with client.get("/api/v1/events/stream?components=3") as resp:
        assert resp.status == 200
        _hello = await asyncio.wait_for(resp.content.readuntil(b"\n\n"), timeout=2)

        # component=99 should NOT appear
        routes.broadcaster.publish_dict(
            "nft.minted", {"id": 1}, component=99,
        )
        # component=3 SHOULD appear
        routes.broadcaster.publish_dict(
            "nft.minted", {"id": 2}, component=3,
        )

        frame = await asyncio.wait_for(resp.content.readuntil(b"\n\n"), timeout=2)
        assert b'"id":2' in frame or b'"id": 2' in frame


# ---------------------------------------------------------------------------
# _BatchSubRequest — sanity checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_sub_request_json_returns_stored_body():
    sub = _BatchSubRequest(
        body={"a": 1}, match_info={}, method="POST", path="/x",
    )
    body = await sub.json()
    assert body == {"a": 1}


@pytest.mark.asyncio
async def test_batch_sub_request_json_defaults_empty():
    sub = _BatchSubRequest(
        body=None, match_info={}, method="POST", path="/x",
    )
    assert await sub.json() == {}
