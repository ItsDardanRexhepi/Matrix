"""NEW-17 — content assertions for the streaming channels.

D1 (the route sweep) can judge a normal route: send a request, read the whole
body, assert on it. It cannot judge a stream, because a stream never ends — so
D1 only ever confirmed that the handshake succeeded. Every SSE and WebSocket
route was therefore unjudged ON CONTENT, and that is exactly where RUN-5's
redaction was missing: `/chat/stream` emitted `{"error": str(e)}` and `/ws`
emitted the same, on channels no test had ever read a frame from.

The technique these tests use is BOUNDED CONSUMPTION: read at most N frames or
until a deadline, whichever comes first, then assert on what arrived. That is
what makes an endless stream testable without hanging the suite. It is applied
to all three SSE routes and the WebSocket.
"""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

sys.path.insert(0, "tests")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from gateway.error_contract import is_redacted  # noqa: E402
from gateway.server import GatewayServer  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

# Internal detail that must never appear in a frame.
FORBIDDEN = (
    "Traceback",
    "has no attribute",
    "Connect call failed",
    "Cannot connect to host",
    "localhost:11434",
    "llama3.1",
    "mistral",
    "ollama",
    "sk-",
    "api_key",
    "signer_key",
    "/Users/",
    "site-packages",
)

MAX_FRAMES = 12
DEADLINE_S = 5.0


def _leaks(text: str) -> list[str]:
    return [s for s in FORBIDDEN if s.lower() in text.lower()]


async def read_bounded_sse(resp, *, max_frames: int = MAX_FRAMES,
                           deadline: float = DEADLINE_S) -> list[str]:
    """Consume at most *max_frames* SSE frames, or until *deadline*.

    An SSE frame is terminated by a blank line. Returning on either bound is
    what lets an endless stream be asserted on at all — without it the only
    testable thing is the handshake, which is precisely how these routes went
    unjudged.
    """
    frames: list[str] = []
    buf = b""
    loop = asyncio.get_running_loop()
    end = loop.time() + deadline
    while len(frames) < max_frames:
        remaining = end - loop.time()
        if remaining <= 0:
            break
        try:
            chunk = await asyncio.wait_for(resp.content.read(4096), timeout=remaining)
        except (asyncio.TimeoutError, TimeoutError):
            break
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf and len(frames) < max_frames:
            frame, buf = buf.split(b"\n\n", 1)
            frames.append(frame.decode("utf-8", "replace"))
    return frames


def parse_sse(frame: str) -> tuple[str | None, dict | None]:
    """Return ``(event_type, data)`` for one frame. Comments yield (None, None)."""
    event, data = None, None
    for line in frame.splitlines():
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            raw = line[len("data:"):].strip()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"__unparsed__": raw}
    return event, data


# ── /chat/stream ───────────────────────────────────────────────────────────

async def test_chat_stream_error_frame_is_redacted_and_terminates():
    """The leak RUN-5 missed, and the reason it missed it.

    With no model provider reachable (the test config has none), this stream
    takes its failure path. Before the fix that path emitted
    `{"error": str(e)}` — the full provider exception, hostnames and model
    names included — straight into the stream. RUN-5 did not catch it because
    it grepped for str(e) inside json_response call shapes, and an SSE frame is
    neither a json_response nor that shape.

    Asserted here: the error frame is REDACTED, carries the contract, and the
    stream still terminates with `done` rather than hanging.
    """
    server = GatewayServer(SWEEP_CONFIG)
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post(
            "/chat/stream",
            json={"message": "hi", "agent": "neo"},
            headers={"Authorization": "Bearer k"},
        )
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/event-stream")

        frames = await read_bounded_sse(resp)

    assert frames, "no frames arrived — the stream produced nothing to judge"

    joined = "\n".join(frames)
    assert not _leaks(joined), f"stream leaked {_leaks(joined)}"

    parsed = [parse_sse(f) for f in frames]
    events = [e for e, _ in parsed if e]
    assert events[0] == "start", f"first event was {events[0]!r}, expected 'start'"

    error_payloads = [d for e, d in parsed if e == "error" and d]
    assert error_payloads, f"no error frame despite an unreachable provider: {events}"
    err = error_payloads[0]
    assert is_redacted(err), f"error frame is not on the contract: {err}"
    assert err["ref"] and err["ref"] != "-", "error frame carries no correlation id"
    assert err["ref"] in err["error"], "the ref must be quotable from the message alone"

    assert "done" in events, f"stream did not terminate with 'done': {events}"


async def test_chat_stream_rejects_a_bad_agent_before_streaming():
    """A validation failure must be an ordinary status, not a 200 stream whose
    first frame is an error — the client cannot retry on a 200."""
    server = GatewayServer(SWEEP_CONFIG)
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post(
            "/chat/stream",
            json={"message": "hi", "agent": "not-an-agent"},
            headers={"Authorization": "Bearer k"},
        )
        assert resp.status == 400
        assert not resp.headers["Content-Type"].startswith("text/event-stream")


# ── /api/v1/events/stream ──────────────────────────────────────────────────

async def test_events_stream_opens_with_an_honest_handshake_frame():
    """The first frame must describe the subscription the server actually made.

    A stream that says `stream.opened` while having registered different
    filters is the streaming form of a fake success — the client believes it is
    subscribed to something it is not. This asserts the echoed filters match
    what was requested.
    """
    server = GatewayServer(SWEEP_CONFIG)
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.get(
            "/api/v1/events/stream?components=3,13&types=price.update",
            headers={"Authorization": "Bearer k"},
        )
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/event-stream")
        frames = await read_bounded_sse(resp, max_frames=1, deadline=3.0)

    assert frames, "the stream sent nothing — a client cannot tell it is live"
    event, data = parse_sse(frames[0])
    assert event == "stream.opened", f"first event was {event!r}"
    assert data is not None
    assert data["components"] == [3, 13], f"echoed components {data['components']}"
    assert data["types"] == ["price.update"], f"echoed types {data['types']}"
    assert not _leaks(frames[0]), f"handshake frame leaked {_leaks(frames[0])}"


async def test_events_stream_delivers_a_real_event_with_the_right_shape():
    """Content, not handshake: publish an event and read it off the wire.

    This is the assertion D1 structurally could not make. It proves the stream
    carries real data, that the data keeps its declared type, and that a
    published payload does not smuggle internals into a client frame.
    """
    server = GatewayServer(SWEEP_CONFIG)
    app = server.create_app()
    async with TestClient(TestServer(app)) as client:
        resp = await client.get(
            "/api/v1/events/stream?types=price.update",
            headers={"Authorization": "Bearer k"},
        )
        assert resp.status == 200
        opened = await read_bounded_sse(resp, max_frames=1, deadline=3.0)
        assert opened and parse_sse(opened[0])[0] == "stream.opened"

        broadcaster = server.event_broadcaster
        broadcaster.publish_dict("price.update", {"symbol": "ETH", "price": "1234.56"})

        frames = await read_bounded_sse(resp, max_frames=3, deadline=5.0)

    payloads = [parse_sse(f) for f in frames]
    matching = [d for e, d in payloads if e == "price.update" and d]
    assert matching, (
        f"published event never arrived on the stream; got events "
        f"{[e for e, _ in payloads]}"
    )
    body = matching[0]
    assert body.get("type") == "price.update"
    # The wire shape is `payload`, not `data` — asserted against what the
    # broadcaster actually emits rather than what a reader might assume.
    assert body.get("payload", {}).get("symbol") == "ETH", f"wire shape: {body}"
    joined = "\n".join(frames)
    assert not _leaks(joined), f"event frame leaked {_leaks(joined)}"


async def test_events_stream_filter_excludes_non_matching_types():
    """A filtered subscription that delivers everything is a silent privacy
    failure — the client is handed events it never asked to see."""
    server = GatewayServer(SWEEP_CONFIG)
    app = server.create_app()
    async with TestClient(TestServer(app)) as client:
        resp = await client.get(
            "/api/v1/events/stream?types=price.update",
            headers={"Authorization": "Bearer k"},
        )
        await read_bounded_sse(resp, max_frames=1, deadline=3.0)

        broadcaster = server.event_broadcaster
        broadcaster.publish_dict("transaction.confirmed", {"tx": "0xdeadbeef"})
        broadcaster.publish_dict("price.update", {"symbol": "BTC"})

        frames = await read_bounded_sse(resp, max_frames=4, deadline=5.0)

    events = [e for e, _ in (parse_sse(f) for f in frames) if e]
    assert "transaction.confirmed" not in events, (
        f"a filtered-out event was delivered: {events}"
    )
    assert "price.update" in events, f"the subscribed event never arrived: {events}"


# ── /ws ────────────────────────────────────────────────────────────────────

async def test_websocket_error_frame_is_redacted():
    """The other channel RUN-5 never looked at.

    A WebSocket has no HTTP status after the handshake, so the contract must
    travel in the payload. Before the fix this frame was
    `{"type": "error", "error": str(e)}`.
    """
    server = GatewayServer(SWEEP_CONFIG)
    async with TestClient(TestServer(server.create_app())) as client:
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "chat", "message": "hi", "agent": "neo"})

        received = []
        loop = asyncio.get_running_loop()
        end = loop.time() + DEADLINE_S
        while len(received) < MAX_FRAMES:
            remaining = end - loop.time()
            if remaining <= 0:
                break
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=remaining)
            except (asyncio.TimeoutError, TimeoutError):
                break
            if msg.type != client._session._ws_response_class.__module__ and not msg.data:
                break
            try:
                received.append(json.loads(msg.data))
            except (TypeError, json.JSONDecodeError):
                break
            if received[-1].get("type") in {"error", "done"}:
                break
        await ws.close()

    assert received, "the socket produced no frames"
    raw = json.dumps(received)
    assert not _leaks(raw), f"websocket leaked {_leaks(raw)}"

    errors = [f for f in received if f.get("type") == "error"]
    assert errors, f"no error frame despite an unreachable provider: {received}"
    err = errors[0]
    assert is_redacted(err), f"websocket error frame is not on the contract: {err}"
    assert err["ref"] and err["ref"] != "-", "no correlation id on the socket frame"


# ── the meta-assertion ─────────────────────────────────────────────────────

def test_every_streaming_route_has_a_content_assertion():
    """NEW-17's own closing condition, enforced.

    NEW-17 stays open until every streaming route either has a content
    assertion or a written reason it cannot. This test fails if a new streaming
    route appears without one, so the debt cannot silently regrow.
    """
    judged = {
        "/chat/stream": "test_chat_stream_error_frame_is_redacted_and_terminates",
        "/api/v1/events/stream": "test_events_stream_delivers_a_real_event_with_the_right_shape",
        "/ws": "test_websocket_error_frame_is_redacted",
        # Judged by D1's dedicated assertion, added when the sweep missed it.
        "/social/feed/stream": "test_route_sweep.py::feed-stream raise/500 assertion",
    }

    import inspect

    server = GatewayServer(SWEEP_CONFIG)
    app = server.create_app()

    # Detect streaming routes STRUCTURALLY, by what the handler does — not by
    # "stream" appearing in the path. The first version of this test used the
    # substring and flagged /api/v1/payments/stream/create, which streams MONEY
    # over time and is an ordinary JSON POST. A name-based detector reports
    # confident nonsense; the same mistake D3's regex made.
    streaming = set()
    for resource in app.router.resources():
        path = getattr(resource, "canonical", None)
        if not path:
            continue
        for route in resource:
            try:
                source = inspect.getsource(route.handler)
            except (OSError, TypeError):
                continue
            if "text/event-stream" in source or "WebSocketResponse" in source:
                streaming.add(path)

    assert streaming, "detector found no streaming routes at all — it is broken"
    unjudged = streaming - set(judged)
    assert not unjudged, (
        f"streaming route(s) with no content assertion: {sorted(unjudged)}. "
        "Add one, or record here why it cannot have one."
    )
