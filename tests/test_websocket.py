"""Tests for the WebSocket endpoint (gateway.server.handle_websocket).

Mirrors the in-process aiohttp testing approach used in test_gateway.py:
the GatewayServer is constructed with mocked memory/react_loop so the
endpoint runs end-to-end without external services. We use the test
client's ``ws_connect`` to talk to ``/ws`` over a real WebSocket.
"""

from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from runtime.react_loop import ReActResult


@pytest.fixture
def ws_config(tmp_path):
    """Config for GatewayServer with auth disabled (WS path is open)."""
    return {
        "platform": "0pnMatrx",
        "memory_dir": str(tmp_path / "memory"),
        "workspace": str(tmp_path),
        "timezone": "UTC",
        "max_steps": 5,
        "model": {"provider": "ollama", "providers": {}},
        "agents": {
            "neo": {"enabled": True},
            "trinity": {"enabled": True},
            "morpheus": {"enabled": True},
        },
        "gateway": {
            "api_key": "",
            "rate_limit_rpm": 600,
            "rate_limit_burst": 100,
        },
        "security": {},
    }


def _build_mock_server(config):
    """Same shape as test_gateway._build_mock_server, scoped down for WS."""
    with patch("gateway.server.GatewayServer.__init__", lambda self, cfg: None):
        from gateway.server import GatewayServer, RateLimiter
        server = GatewayServer.__new__(GatewayServer)

    server.config = config
    server.conversations = {}
    server.request_count = 0
    server._first_boot_sent = set()
    server._conv_loaded = set()

    server.wallet_sessions = MagicMock()
    server.wallet_sessions.initialize = AsyncMock()
    server.wallet_sessions.cleanup = AsyncMock()
    server.wallet_sessions.get = MagicMock(return_value=None)
    server.wallet_sessions.__contains__ = MagicMock(return_value=False)
    server.wallet_nonces = MagicMock()
    server.wallet_nonces.initialize = AsyncMock()
    server.wallet_nonces.cleanup = AsyncMock()
    server.wallet_nonces.consume = AsyncMock(return_value=False)
    server.wallet_nonces.__contains__ = MagicMock(return_value=False)
    server._wallet_session_ttl = 86400
    server._auth_cleanup_task = None

    server._backup_enabled = False
    server._backup_dir = ""
    server._backup_retention = 7
    server._backup_interval = 86400.0
    server.backup_manager = None
    server._backup_task = None

    from runtime.monitoring.metrics import MetricsCollector
    from runtime.monitoring.otel import OTelMetricsBridge
    server.metrics = MetricsCollector()
    server.otel_bridge = OTelMetricsBridge(server.metrics, {})

    gw = config.get("gateway", {})
    server.api_key = gw.get("api_key", "")
    server.auth_enabled = bool(server.api_key)
    server._public_paths = {"/health", "/auth/nonce", "/auth/verify"}

    server.rate_limiter_auth = RateLimiter(
        requests_per_minute=gw.get("rate_limit_rpm", 600),
        burst=gw.get("rate_limit_burst", 100),
    )
    server.rate_limiter_wallet = RateLimiter(
        requests_per_minute=gw.get("rate_limit_rpm", 600),
        burst=gw.get("rate_limit_burst", 100),
    )
    server.rate_limiter_anon = RateLimiter(
        requests_per_minute=gw.get("rate_limit_rpm", 600),
        burst=gw.get("rate_limit_burst", 100),
    )

    # Timeout and WebSocket config (new in 0.5.0)
    server.request_timeout = float(gw.get("request_timeout_seconds", 120))
    ws_cfg = gw.get("websocket", {}) if isinstance(gw.get("websocket"), dict) else {}
    # Keep the WS frame limit well above the 100k message cap in tests.
    server.ws_max_message_size = int(ws_cfg.get("max_message_size", 4 * (1 << 20)))
    server.ws_heartbeat_seconds = float(ws_cfg.get("heartbeat_seconds", 30))

    mock_loop = MagicMock()
    mock_loop.get_agent_prompt = MagicMock(return_value="You are an agent.")
    mock_loop.run = AsyncMock(return_value=ReActResult(
        response="Hello from Trinity over websocket",
        tool_calls=[{"tool": "noop", "args": {}}],
        iterations=1,
        provider="mock",
    ))
    mock_loop.router = MagicMock()
    mock_loop.router.health_check = AsyncMock(return_value={"mock": True})
    mock_loop.memory = MagicMock()
    mock_loop.memory.initialize = AsyncMock()
    mock_loop.memory.close = AsyncMock()
    mock_loop.memory.read = MagicMock(return_value={"kv": {}, "turns": []})
    mock_loop.memory.write = AsyncMock()
    mock_loop.memory.load_conversation = MagicMock(return_value=[])
    mock_loop.memory.save_conversation = AsyncMock()
    mock_loop.memory.is_first_boot_sent = MagicMock(return_value=True)
    mock_loop.memory.mark_first_boot_sent = AsyncMock()
    from pathlib import Path as _P
    mock_loop.memory.memory_dir = _P("memory")
    server.react_loop = mock_loop

    mock_temporal = MagicMock()
    mock_temporal.get_context_string = MagicMock(return_value="Current time: 2026-01-01")
    server.temporal = mock_temporal

    return server


@pytest.fixture
async def ws_client(aiohttp_client, ws_config):
    server = _build_mock_server(ws_config)
    app = server.create_app()
    client = await aiohttp_client(app)
    # Stash the server on the client so individual tests can poke at it.
    client.server_under_test = server
    return client


async def _drain_until_done(ws):
    """Read frames from the WebSocket until a ``done`` or ``error`` arrives."""
    tokens: list[str] = []
    final = None
    async for msg in ws:
        if msg.type.name not in {"TEXT"}:
            break
        payload = json.loads(msg.data)
        if payload.get("type") == "token":
            tokens.append(payload["text"])
        elif payload.get("type") in {"done", "error"}:
            final = payload
            break
    return tokens, final


class TestWebSocketHappyPath:
    """A valid chat frame produces tokens followed by a done frame."""

    @pytest.mark.asyncio
    async def test_chat_frame_streams_tokens_and_done(self, ws_client):
        async with ws_client.ws_connect("/ws") as ws:
            await ws.send_json({
                "type": "chat",
                "message": "Hello over ws",
                "agent": "trinity",
                "session_id": "ws-session-1",
            })
            tokens, final = await _drain_until_done(ws)
            await ws.close()

        assert tokens, "expected at least one token frame"
        assembled = "".join(tokens)
        assert "Trinity" in assembled
        assert final is not None
        assert final["type"] == "done"
        assert final["session_id"] == "ws-session-1"
        assert final["agent"] == "trinity"
        assert final["provider"] == "mock"
        assert final["tool_calls"] == [{"tool": "noop", "args": {}}]

    @pytest.mark.asyncio
    async def test_conversation_persisted_across_frames(self, ws_client):
        server = ws_client.server_under_test
        async with ws_client.ws_connect("/ws") as ws:
            await ws.send_json({
                "type": "chat",
                "message": "first message",
                "agent": "trinity",
                "session_id": "ws-multi",
            })
            await _drain_until_done(ws)
            await ws.send_json({
                "type": "chat",
                "message": "second message",
                "agent": "trinity",
                "session_id": "ws-multi",
            })
            await _drain_until_done(ws)
            await ws.close()

        # User + assistant turn for each frame: 4 messages.
        history = server.conversations["ws-multi"]
        assert len(history) == 4
        assert history[0].role == "user"
        assert history[0].content == "first message"
        assert history[1].role == "assistant"
        assert history[2].role == "user"
        assert history[2].content == "second message"
        assert history[3].role == "assistant"


class TestWebSocketValidation:
    """Bad frames produce ``error`` responses without tearing down the socket."""

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self, ws_client):
        async with ws_client.ws_connect("/ws") as ws:
            await ws.send_str("not json{{{")
            msg = await ws.receive(timeout=2)
            payload = json.loads(msg.data)
            await ws.close()
        assert payload["type"] == "error"
        assert "json" in payload["error"].lower()

    @pytest.mark.asyncio
    async def test_unsupported_message_type_returns_error(self, ws_client):
        async with ws_client.ws_connect("/ws") as ws:
            await ws.send_json({"type": "ping"})
            msg = await ws.receive(timeout=2)
            payload = json.loads(msg.data)
            await ws.close()
        assert payload["type"] == "error"
        assert "unsupported" in payload["error"].lower()

    @pytest.mark.asyncio
    async def test_empty_message_returns_error(self, ws_client):
        async with ws_client.ws_connect("/ws") as ws:
            await ws.send_json({"type": "chat", "message": "   ", "agent": "trinity"})
            msg = await ws.receive(timeout=2)
            payload = json.loads(msg.data)
            await ws.close()
        assert payload["type"] == "error"
        assert "required" in payload["error"].lower()

    @pytest.mark.asyncio
    async def test_message_too_long_returns_error(self, ws_client):
        oversized = "x" * 100_001
        async with ws_client.ws_connect("/ws") as ws:
            await ws.send_json({"type": "chat", "message": oversized, "agent": "trinity"})
            msg = await ws.receive(timeout=2)
            payload = json.loads(msg.data)
            await ws.close()
        assert payload["type"] == "error"
        assert "too long" in payload["error"].lower()

    @pytest.mark.asyncio
    async def test_invalid_agent_returns_error(self, ws_client):
        async with ws_client.ws_connect("/ws") as ws:
            await ws.send_json({"type": "chat", "message": "hi", "agent": "jarvis"})
            msg = await ws.receive(timeout=2)
            payload = json.loads(msg.data)
            await ws.close()
        assert payload["type"] == "error"
        assert "agent" in payload["error"].lower()


class TestWebSocketErrorHandling:
    """If the ReAct loop raises, the socket reports the error gracefully."""

    @pytest.mark.asyncio
    async def test_runtime_error_from_loop_returned_as_error_frame(self, ws_client):
        server = ws_client.server_under_test
        server.react_loop.run = AsyncMock(side_effect=RuntimeError("model unavailable"))

        async with ws_client.ws_connect("/ws") as ws:
            await ws.send_json({
                "type": "chat",
                "message": "trigger failure",
                "agent": "trinity",
                "session_id": "ws-fail",
            })
            msg = await ws.receive(timeout=2)
            payload = json.loads(msg.data)
            await ws.close()

        assert payload["type"] == "error"
        assert "model unavailable" in payload["error"]
