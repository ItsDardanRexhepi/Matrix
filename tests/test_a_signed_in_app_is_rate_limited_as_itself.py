"""A signed-in app is rate-limited as the account it is, not as its address.

THE DEFECT (pre-existing on The Matrix ``main``). The rate limiter recognised a
session only through the ``X-Wallet-Session`` header. The iOS app presents its
Apple session as ``Authorization: Bearer``, so every request of every
signed-in app user fell into the anonymous per-address bucket: users behind one
carrier NAT shared 20 requests a minute between them and were answered 429
while each held a valid session. The limiter now reads the session the way the
auth wall does — ``X-Wallet-Session`` first, then the Bearer — and keys a live
session's requests on its account; the operator key and the anonymous bucket
are as they were.
"""
from __future__ import annotations

import time


def _server(tmp_path):
    from gateway.server import GatewayServer
    return GatewayServer({"memory_dir": str(tmp_path / "m"),
                          "database": {"path": str(tmp_path / "s.db")},
                          "gateway": {"api_key": "k"}})


async def _keys(tmp_path, headers_list):
    from aiohttp.test_utils import TestClient, TestServer
    server = _server(tmp_path)
    seen = []
    for limiter in (server.rate_limiter_wallet, server.rate_limiter_auth, server.rate_limiter_anon):
        real = limiter.allow

        def allow(key, _real=real, _limiter=limiter):
            seen.append((_limiter, key))
            return _real(key)
        limiter.allow = allow
    async with TestClient(TestServer(server.create_app())) as client:
        now = time.time()
        await server.wallet_sessions.add(token="0xAPP_ONE", address="apple:one",
                                         issued_at=now, expires_at=now + 3600)
        await server.wallet_sessions.add(token="0xAPP_TWO", address="apple:two",
                                         issued_at=now, expires_at=now + 3600)
        await server.wallet_sessions.add(token="0xGONE", address="apple:gone",
                                         issued_at=now - 7200, expires_at=now - 3600)
        for headers in headers_list:
            # The wall answers a request with no live credential before the
            # limiter sees it, except on a public path.
            path = "/api/v1/capabilities" if headers.get("Authorization", "").endswith(
                ("APP_ONE", "APP_TWO", " k")) or headers.get("X-Wallet-Session") else "/health"
            await client.get(path, headers=headers)
    name = {id(server.rate_limiter_wallet): "wallet", id(server.rate_limiter_auth): "key",
            id(server.rate_limiter_anon): "anonymous"}
    return [(name[id(limiter)], key) for limiter, key in seen]


async def test_a_bearer_session_is_limited_as_its_account(tmp_path):
    """[control] Two signed-in users on one address: two buckets, not one."""
    keys = await _keys(tmp_path, [{"Authorization": "Bearer 0xAPP_ONE"},
                                  {"Authorization": "Bearer 0xAPP_TWO"}])
    assert keys == [("wallet", "wallet:apple:one"), ("wallet", "wallet:apple:two")], keys


async def test_the_other_credentials_keep_their_buckets(tmp_path):
    """[guard] The session header, the operator key, an expired session and
    no credential land where they did."""
    keys = await _keys(tmp_path, [{"X-Wallet-Session": "0xAPP_ONE"},
                                  {"Authorization": "Bearer k"},
                                  {"Authorization": "Bearer 0xGONE"},
                                  {}])
    assert keys[0] == ("wallet", "wallet:apple:one")
    assert keys[1][0] == "key" and keys[1][1].startswith("key:")
    assert keys[2][0] == "anonymous" and keys[2][1].startswith("ip:")
    assert keys[3][0] == "anonymous" and keys[3][1].startswith("ip:")
