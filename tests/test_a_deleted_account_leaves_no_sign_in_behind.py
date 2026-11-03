"""Deleting an account deletes the sign-in it was: its Apple user record, the
wallet linked to it and every session of the account, not only the one the
request presented.

THE DEFECTS (pre-existing on The Matrix ``main``). ``DELETE
/api/v1/auth/account`` erased the account's conversations, memory and devices
and removed the presented session, and left two things behind:

  * the ``apple_users`` row — first sign-in, last sign-in and the linked
    wallet. Signing in again with the same Apple ID answered ``isNewUser:
    false`` with the old ``walletAddress``, and every session-derived identity
    (the security context, the follow graph, the routes that act as the
    caller) resolved the new session to the deleted account's wallet;
  * every OTHER live session of the account. A second device stayed signed in,
    its token still passed the auth wall and still resolved to the linked
    wallet, until it expired.

And a first sign-in was recorded before its session existed, so a sign-in
whose session could not be stored was answered 500 and the retry was told it
was not new.
"""
from __future__ import annotations

import time

import pytest

SUB = "deleted-user"
WALLET = "0x" + "d4" * 20


def _server(tmp_path):
    from gateway.server import GatewayServer
    return GatewayServer({"memory_dir": str(tmp_path / "m"),
                          "database": {"path": str(tmp_path / "s.db")},
                          "gateway": {"api_key": "k"},
                          "auth": {"apple": {"bundle_id": "com.example.app"}}})


@pytest.fixture
def apple(monkeypatch):
    async def verify(token, **kwargs):
        return {"sub": SUB}
    monkeypatch.setattr("gateway.apple_auth.verify_apple_identity_token", verify)


async def _sign_in(client):
    resp = await client.post("/api/v1/auth/apple", json={"identityToken": "t"})
    assert resp.status == 200, await resp.text()
    return await resp.json()


async def test_a_deleted_account_signs_in_again_as_new_with_no_wallet(apple, tmp_path):
    """[control] The apple_users row outlived the deletion."""
    from aiohttp.test_utils import TestClient, TestServer
    server = _server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        first = await _sign_in(client)
        assert first["isNewUser"] is True
        await server.apple_users.link_wallet(SUB, WALLET)
        resp = await client.delete("/api/v1/auth/account",
                                   headers={"Authorization": f"Bearer {first['token']}"})
        assert resp.status == 200, await resp.text()
        assert server.apple_users.get(SUB) is None
        rows = await server.react_loop.memory.db.fetchall(
            "SELECT sub FROM apple_users WHERE sub = ?", (SUB,))
        assert list(rows) == []
        again = await _sign_in(client)
    assert again["isNewUser"] is True
    assert again["walletAddress"] == ""


async def test_no_session_of_a_deleted_account_stays_signed_in(apple, tmp_path):
    """[control] A second device's token still passed the wall."""
    from aiohttp.test_utils import TestClient, TestServer
    server = _server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        one = await _sign_in(client)
        two = await _sign_in(client)
        resp = await client.get("/api/v1/capabilities", headers={"Authorization": f"Bearer {two['token']}"})
        assert resp.status == 200, "precondition: the second device is signed in"
        resp = await client.delete("/api/v1/auth/account",
                                   headers={"Authorization": f"Bearer {one['token']}"})
        assert resp.status == 200, await resp.text()
        resp = await client.get("/api/v1/capabilities", headers={"Authorization": f"Bearer {two['token']}"})
        assert resp.status == 401, resp.status
    assert server.wallet_sessions.get(two["token"]) is None


async def test_another_account_s_sessions_are_untouched(apple, tmp_path):
    """[guard] Only the deleted account's sessions go."""
    from aiohttp.test_utils import TestClient, TestServer
    server = _server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        mine = await _sign_in(client)
        now = time.time()
        await server.wallet_sessions.add(token="0xOTHER_ACCOUNT", address="apple:someone-else",
                                         issued_at=now, expires_at=now + 3600)
        await server.apple_users.touch("someone-else")
        resp = await client.delete("/api/v1/auth/account",
                                   headers={"Authorization": f"Bearer {mine['token']}"})
        assert resp.status == 200
    assert server.wallet_sessions.get("0xOTHER_ACCOUNT") is not None
    assert server.apple_users.get("someone-else") is not None


async def test_a_sign_in_whose_session_failed_is_still_new_on_retry(apple, tmp_path, monkeypatch):
    """[control] The first sign-in was recorded before its session was stored."""
    from aiohttp.test_utils import TestClient, TestServer
    server = _server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        real_add = server.wallet_sessions.add
        calls = {"n": 0}

        async def failing_once(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("database is locked")
            return await real_add(**kwargs)

        monkeypatch.setattr(server.wallet_sessions, "add", failing_once)
        resp = await client.post("/api/v1/auth/apple", json={"identityToken": "t"})
        assert resp.status == 500
        retry = await _sign_in(client)
    assert retry["isNewUser"] is True
