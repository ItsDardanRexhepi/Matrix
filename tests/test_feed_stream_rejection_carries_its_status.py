"""GET /social/feed/stream refuses with a real HTTP status, like its sibling.

The broadcaster's contract is that a capacity rejection is 503 (global cap) or
429 (per-IP cap). /api/v1/events/stream registers BEFORE it prepares the
response and raises the status with Retry-After. /social/feed/stream prepared a
200 text/event-stream first and then registered, so its 429/503 could only be
written as a field inside an SSE error event on a successful response — a
client or proxy keying on the status saw success. A missing broadcaster was the
same shape: 200 and an error event.
"""

from __future__ import annotations

import sys
import tempfile
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "tests")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from gateway.event_broadcaster import BroadcasterCapacityError  # noqa: E402
from gateway.server import GatewayServer  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

ROUTES = ("/social/feed/stream", "/api/v1/events/stream")


def _server() -> GatewayServer:
    scratch = tempfile.mkdtemp(prefix="the-matrix-feedstream-")
    return GatewayServer({**SWEEP_CONFIG, "memory_dir": scratch, "database": {"path": f"{scratch}/f.db"}})


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("scope,status", [("per_ip", 429), ("global", 503)])
async def test_a_capacity_rejection_is_the_http_status_with_retry_after(route, scope, status):
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        server.event_broadcaster.register = AsyncMock(
            side_effect=BroadcasterCapacityError("cap reached", scope=scope))
        resp = await client.get(route)
        text = await resp.text()
        assert resp.status == status, (route, scope, resp.status, text[:200])
        assert resp.headers.get("Retry-After"), (route, dict(resp.headers))
        assert not resp.headers.get("Content-Type", "").startswith("text/event-stream"), route


async def test_no_broadcaster_is_a_503_not_a_200_stream():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        server.event_broadcaster = None
        resp = await client.get("/social/feed/stream")
        await resp.read()
        assert resp.status == 503, resp.status


# ── the slot a stream takes is given back ────────────────────────────────────
#
# Found while moving the register: the handler's `finally` called the
# broadcaster's ASYNC unregister without awaiting it, so the subscriber was
# never removed. And iter_events yields None as a keep-alive every quiet
# interval; the handler called `None.to_dict()` on it, so every feed stream died
# after 15 quiet seconds — leaking its slot on the way out. The broadcaster is
# shared with /api/v1/events/stream and counts slots per peer address, so eight
# leaked feed streams from one address (behind the shipped Caddy proxy, every
# client has the proxy's address) refused both streams to that address until a
# restart.

import asyncio  # noqa: E402

QUIET = 0.05


def _fast_keepalive(broadcaster) -> None:
    original = broadcaster.iter_events

    def iter_events(sub, keepalive_interval=QUIET):
        return original(sub, keepalive_interval=QUIET)
    broadcaster.iter_events = iter_events


async def _wait_for(predicate, timeout=3.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


async def test_a_quiet_feed_stream_stays_open_and_sends_keepalives():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        _fast_keepalive(server.event_broadcaster)
        resp = await client.get("/social/feed/stream")
        assert resp.status == 200
        chunk = await asyncio.wait_for(resp.content.readuntil(b"\n\n"), 2)
        await asyncio.sleep(QUIET * 6)
        assert len(server.event_broadcaster._subs) == 1, "the stream died while quiet"
        resp.close()
        assert chunk.startswith(b":"), chunk


async def test_a_closed_feed_stream_gives_its_slot_back():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        broadcaster = server.event_broadcaster
        _fast_keepalive(broadcaster)
        for _ in range(3):
            resp = await client.get("/social/feed/stream")
            assert resp.status == 200
            await asyncio.wait_for(resp.content.readuntil(b"\n\n"), 2)
            resp.close()
        released = await _wait_for(lambda: len(broadcaster._subs) == 0)
        assert released, f"{len(broadcaster._subs)} subscriber slots still held after every client closed"


@pytest.mark.parametrize("route", ROUTES)
async def test_a_client_gone_before_the_headers_does_not_keep_a_slot(route, monkeypatch):
    from aiohttp import web

    async def prepare_fails(self, request):
        raise ConnectionResetError("client went away")
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        monkeypatch.setattr(web.StreamResponse, "prepare", prepare_fails)
        import aiohttp
        try:
            resp = await client.get(route)
            await resp.read()
        except aiohttp.ClientError:
            pass  # the server drops the connection; the slot is what matters
        monkeypatch.undo()
        assert len(server.event_broadcaster._subs) == 0, (route, len(server.event_broadcaster._subs))
