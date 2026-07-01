"""P1-6: push token store CRUD + the /bridge/v1/push/register route."""

import pytest

from runtime.db.database import Database
from runtime.notifications.token_store import PushTokenStore


@pytest.fixture
def db(tmp_path):
    return Database({"database": {"path": str(tmp_path / "push.db")}})


@pytest.mark.asyncio
async def test_register_and_lookup_roundtrip(db):
    store = PushTokenStore(db)
    await store.register("tokA", session_id="s1", wallet="0xabc")
    await store.register("tokB", session_id="s2", wallet="0xdef")
    assert set(await store.all_tokens()) == {"tokA", "tokB"}
    assert await store.tokens_for(wallet="0xabc") == ["tokA"]
    assert await store.tokens_for(session_id="s2") == ["tokB"]


@pytest.mark.asyncio
async def test_upsert_is_idempotent(db):
    store = PushTokenStore(db)
    await store.register("tokA", wallet="0xabc")
    await store.register("tokA", wallet="0xNEW")  # same token, new wallet
    assert await store.all_tokens() == ["tokA"]      # not duplicated
    assert await store.tokens_for(wallet="0xNEW") == ["tokA"]


@pytest.mark.asyncio
async def test_remove(db):
    store = PushTokenStore(db)
    await store.register("tokA")
    await store.remove("tokA")
    assert await store.all_tokens() == []


@pytest.mark.asyncio
async def test_bridge_route_registers_token(aiohttp_client, tmp_path):
    from tests.test_gateway import _build_mock_server
    from gateway.bridge import BridgeRoutes

    config = {
        "platform": "0pnMatrx",
        "memory_dir": str(tmp_path / "memory"),
        "workspace": str(tmp_path),
        "timezone": "UTC",
        "model": {"provider": "ollama", "providers": {}},
        "agents": {"neo": {"enabled": True}},
        "gateway": {"api_key": "", "rate_limit_rpm": 60, "rate_limit_burst": 10},
        "security": {},
    }
    server = _build_mock_server(config)
    server._app_attest = None
    server._security_backend = "noop"
    # Give the mock react_loop.memory a real DB for the token store.
    server.react_loop.memory.db = Database({"database": {"path": str(tmp_path / "g.db")}})
    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.post(
        "/bridge/v1/push/register",
        json={"session_id": "default", "push_token": "device-token-xyz"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert body["data"]["registered"] is True

    store = PushTokenStore(server.react_loop.memory.db)
    assert "device-token-xyz" in await store.all_tokens()
