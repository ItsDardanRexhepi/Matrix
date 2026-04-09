"""Tests for gateway.server.GatewayServer HTTP endpoints.

Uses aiohttp.test_utils for in-process testing without real network I/O.
All model calls are mocked to avoid external API dependencies.
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer

from runtime.react_loop import ReActResult
from runtime.models.model_interface import ModelResponse


@pytest.fixture
def gateway_config(tmp_path):
    """Config for GatewayServer with auth enabled."""
    return {
        "platform": "0pnMatrx",
        "memory_dir": str(tmp_path / "memory"),
        "workspace": str(tmp_path),
        "timezone": "UTC",
        "max_steps": 5,
        "model": {
            "provider": "ollama",
            "providers": {},
        },
        "agents": {
            "neo": {"enabled": True},
            "trinity": {"enabled": True},
            "morpheus": {"enabled": True},
        },
        "gateway": {
            "api_key": "test-secret-key",
            "rate_limit_rpm": 60,
            "rate_limit_burst": 10,
        },
        "security": {},
    }


@pytest.fixture
def gateway_config_no_auth(gateway_config):
    """Config with auth disabled (empty api_key)."""
    cfg = dict(gateway_config)
    cfg["gateway"] = dict(cfg["gateway"])
    cfg["gateway"]["api_key"] = ""
    return cfg


def _build_mock_server(config):
    """Create a GatewayServer with mocked model calls."""
    with patch("gateway.server.GatewayServer.__init__", lambda self, cfg: None):
        from gateway.server import GatewayServer, RateLimiter
        server = GatewayServer.__new__(GatewayServer)

    server.config = config
    server.conversations = {}
    server.request_count = 0
    server._first_boot_sent = set()
    server._conv_loaded = set()
    # WalletSessionStore / NonceStore stand-ins: dict-like reads, async writes/init.
    server.wallet_sessions = MagicMock()
    server.wallet_sessions.initialize = AsyncMock()
    server.wallet_sessions.cleanup = AsyncMock()
    server.wallet_sessions.add = AsyncMock()
    server.wallet_sessions.remove = AsyncMock()
    server.wallet_sessions.get = MagicMock(return_value=None)
    server.wallet_sessions.__contains__ = MagicMock(return_value=False)
    server.wallet_nonces = MagicMock()
    server.wallet_nonces.initialize = AsyncMock()
    server.wallet_nonces.cleanup = AsyncMock()
    server.wallet_nonces.add = AsyncMock()
    server.wallet_nonces.consume = AsyncMock(return_value=False)
    server.wallet_nonces.__contains__ = MagicMock(return_value=False)
    server._wallet_session_ttl = 86400
    server._auth_cleanup_task = None
    # Backups disabled in tests — no on-disk side effects
    server._backup_enabled = False
    server._backup_dir = ""
    server._backup_retention = 7
    server._backup_interval = 86400.0
    server.backup_manager = None
    server._backup_task = None
    from runtime.monitoring.metrics import MetricsCollector
    server.metrics = MetricsCollector()

    gw = config.get("gateway", {})
    server.api_key = gw.get("api_key", "")
    server.auth_enabled = bool(server.api_key)
    server._public_paths = {"/health", "/auth/nonce", "/auth/verify"}

    auth_rpm = gw.get("rate_limit_rpm_authenticated", gw.get("rate_limit_rpm", 60))
    auth_burst = gw.get("rate_limit_burst_authenticated", gw.get("rate_limit_burst", 10))
    anon_rpm = gw.get("rate_limit_rpm_anonymous", gw.get("rate_limit_rpm", 60))
    anon_burst = gw.get("rate_limit_burst_anonymous", gw.get("rate_limit_burst", 10))
    server.rate_limiter_auth = RateLimiter(requests_per_minute=auth_rpm, burst=auth_burst)
    server.rate_limiter_anon = RateLimiter(requests_per_minute=anon_rpm, burst=anon_burst)

    # Mock the react_loop
    mock_loop = MagicMock()
    mock_loop.get_agent_prompt = MagicMock(return_value="You are an agent.")
    mock_loop.run = AsyncMock(return_value=ReActResult(
        response="Hello from Trinity",
        tool_calls=[],
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

    # Mock temporal context
    mock_temporal = MagicMock()
    mock_temporal.get_context_string = MagicMock(return_value="Current time: 2026-01-01")
    server.temporal = mock_temporal

    return server


@pytest.fixture
async def client_with_auth(aiohttp_client, gateway_config):
    server = _build_mock_server(gateway_config)
    app = server.create_app()
    return await aiohttp_client(app)


@pytest.fixture
async def client_no_auth(aiohttp_client, gateway_config_no_auth):
    server = _build_mock_server(gateway_config_no_auth)
    app = server.create_app()
    return await aiohttp_client(app)


class TestHealthEndpoint:
    """GET /health returns 200 and status info."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client_with_auth):
        # /health is a public path, no auth needed
        resp = await client_with_auth.get("/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_no_auth_required(self, client_with_auth):
        # No Authorization header, should still work
        resp = await client_with_auth.get("/health")
        assert resp.status == 200


class TestChatEndpoint:
    """POST /chat with various inputs."""

    @pytest.mark.asyncio
    async def test_valid_chat_request(self, client_no_auth):
        resp = await client_no_auth.post("/chat", json={
            "message": "Hello Trinity",
            "agent": "trinity",
            "session_id": "test-session",
        })
        assert resp.status == 200
        data = await resp.json()
        assert "response" in data
        assert data["agent"] == "trinity"
        assert data["session_id"] == "test-session"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self, client_no_auth):
        resp = await client_no_auth.post(
            "/chat",
            data=b"not json{{{",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_empty_message_returns_400(self, client_no_auth):
        resp = await client_no_auth.post("/chat", json={
            "message": "",
            "agent": "trinity",
        })
        assert resp.status == 400
        data = await resp.json()
        assert "message" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_whitespace_only_message_returns_400(self, client_no_auth):
        resp = await client_no_auth.post("/chat", json={
            "message": "   ",
            "agent": "trinity",
        })
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_invalid_agent_returns_400(self, client_no_auth):
        resp = await client_no_auth.post("/chat", json={
            "message": "hello",
            "agent": "jarvis",
        })
        assert resp.status == 400
        data = await resp.json()
        assert "invalid agent" in data["error"]

    @pytest.mark.asyncio
    async def test_default_agent_is_trinity(self, client_no_auth):
        resp = await client_no_auth.post("/chat", json={
            "message": "hello",
        })
        assert resp.status == 200
        data = await resp.json()
        assert data["agent"] == "trinity"

    @pytest.mark.asyncio
    async def test_first_boot_message_included(self, client_no_auth):
        resp = await client_no_auth.post("/chat", json={
            "message": "hi",
            "agent": "trinity",
            "session_id": "fresh-session",
        })
        data = await resp.json()
        assert "Trinity" in data["response"]


class TestAuthMiddleware:
    """Auth middleware blocks unauthenticated requests on protected endpoints."""

    @pytest.mark.asyncio
    async def test_blocks_without_key(self, client_with_auth):
        resp = await client_with_auth.post("/chat", json={
            "message": "hello",
            "agent": "trinity",
        })
        assert resp.status == 401
        data = await resp.json()
        assert data["error"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_blocks_with_wrong_key(self, client_with_auth):
        resp = await client_with_auth.post(
            "/chat",
            json={"message": "hello", "agent": "trinity"},
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_passes_with_valid_bearer_key(self, client_with_auth):
        resp = await client_with_auth.post(
            "/chat",
            json={"message": "hello", "agent": "trinity"},
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_passes_with_query_param_key(self, client_with_auth):
        resp = await client_with_auth.post(
            "/chat?api_key=test-secret-key",
            json={"message": "hello", "agent": "trinity"},
        )
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_health_bypasses_auth(self, client_with_auth):
        resp = await client_with_auth.get("/health")
        assert resp.status == 200


class TestRateLimiting:
    """Rate limiter returns 429 when tokens are exhausted."""

    @pytest.mark.asyncio
    async def test_rate_limit_returns_429(self, aiohttp_client, gateway_config_no_auth):
        # Set burst to 2 so we can trigger the limit quickly
        cfg = dict(gateway_config_no_auth)
        cfg["gateway"] = dict(cfg["gateway"])
        cfg["gateway"]["rate_limit_rpm"] = 1
        cfg["gateway"]["rate_limit_burst"] = 2

        server = _build_mock_server(cfg)
        app = server.create_app()
        client = await aiohttp_client(app)

        payload = {"message": "test", "agent": "trinity"}
        # First two should succeed (burst=2)
        r1 = await client.post("/chat", json=payload)
        r2 = await client.post("/chat", json=payload)
        # Third should be rate limited
        r3 = await client.post("/chat", json=payload)

        assert r1.status == 200
        assert r2.status == 200
        assert r3.status == 429
        data = await r3.json()
        assert data["error"] == "rate_limited"


class TestMemoryEndpoints:
    """POST /memory/read and /memory/write."""

    @pytest.mark.asyncio
    async def test_memory_read(self, client_no_auth):
        resp = await client_no_auth.post("/memory/read", json={"agent": "neo"})
        assert resp.status == 200
        data = await resp.json()
        assert data["agent"] == "neo"
        assert "memory" in data

    @pytest.mark.asyncio
    async def test_memory_write(self, client_no_auth):
        resp = await client_no_auth.post("/memory/write", json={
            "agent": "neo",
            "key": "test_key",
            "value": "test_value",
        })
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_memory_write_missing_key_returns_400(self, client_no_auth):
        resp = await client_no_auth.post("/memory/write", json={
            "agent": "neo",
            "value": "test_value",
        })
        assert resp.status == 400
