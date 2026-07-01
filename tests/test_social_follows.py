"""P2-10: social follow-graph store + routes."""

import pytest

from runtime.db.database import Database
from runtime.social.follows import FollowStore


@pytest.fixture
def db(tmp_path):
    return Database({"database": {"path": str(tmp_path / "follows.db")}})


@pytest.mark.asyncio
async def test_follow_unfollow_roundtrip(db):
    store = FollowStore(db)
    await store.follow("0xa", "0xb")
    await store.follow("0xc", "0xb")
    assert set(await store.followers("0xb")) == {"0xa", "0xc"}
    assert await store.following("0xa") == ["0xb"]
    await store.unfollow("0xa", "0xb")
    assert await store.followers("0xb") == ["0xc"]


@pytest.mark.asyncio
async def test_self_follow_ignored(db):
    store = FollowStore(db)
    await store.follow("0xa", "0xa")
    assert await store.followers("0xa") == []


@pytest.mark.asyncio
async def test_routes(aiohttp_client, tmp_path):
    from tests.test_gateway import _build_mock_server
    config = {
        "platform": "0pnMatrx", "memory_dir": str(tmp_path / "m"),
        "workspace": str(tmp_path), "timezone": "UTC",
        "model": {"provider": "ollama", "providers": {}},
        "agents": {"neo": {"enabled": True}},
        "gateway": {"api_key": "", "rate_limit_rpm": 60, "rate_limit_burst": 10},
        "security": {},
    }
    server = _build_mock_server(config)
    server._app_attest = None
    server._security_backend = "noop"
    server.react_loop.memory.db = Database({"database": {"path": str(tmp_path / "g.db")}})
    client = await aiohttp_client(server.create_app())

    r = await client.post("/social/follow", json={"address": "0xbob"},
                          headers={"X-Wallet-Address": "0xalice"})
    assert r.status == 200 and (await r.json())["success"] is True

    r = await client.get("/social/0xbob/followers")
    body = await r.json()
    assert body["followers"] == ["0xalice"] and body["count"] == 1
