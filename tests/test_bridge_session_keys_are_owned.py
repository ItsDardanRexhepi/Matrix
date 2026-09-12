"""The bridge flow's session and wallet legs, keyed by a session id the caller
chooses.

T3 gave conversations an owner and checked it on the chat entrances. The rest
of the bridge flow still keyed on the bare ``session_id`` string any caller
can write:

  * ``/bridge/v1/session/resume`` reported the message count of any
    conversation, owned or not;
  * ``/bridge/v1/wallet/link`` wrote a wallet link into any session id —
    including a conversation another account owns — and
    ``/bridge/v1/wallet/status`` and ``/bridge/v1/dashboard`` then showed that
    address and its balance to whoever named the id;
  * ``/bridge/v1/action`` handed the dispatcher the wallet linked to whatever
    session id the body named as the CALLER, even when the request presented
    a different account's session — so the service decided ownership for the
    account that linked, not the account that asked;
  * ``/bridge/v1/push/register`` attached a device token to a conversation
    another account owns.

A session id is a name for a conversation, not a credential. Every leg now
checks it against the account the request presents.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, "tests")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from gateway.server import GatewayServer  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

KEY = "test-operator-key"
W = "0x" + "a" * 40


def _server() -> GatewayServer:
    scratch = tempfile.mkdtemp(prefix="opnmatrx-bridge-keys-")
    config = {**SWEEP_CONFIG, "memory_dir": scratch,
              "database": {**SWEEP_CONFIG.get("database", {}), "path": f"{scratch}/b.db"},
              "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": KEY}}
    server = GatewayServer(config)
    server.react_loop.run = AsyncMock(
        return_value=SimpleNamespace(response="ok", tool_calls=[], provider="stub"))
    return server


async def _session(server: GatewayServer, subject: str) -> str:
    token = f"tok-{subject}"
    now = time.time()
    await server.wallet_sessions.add(token=token, address=subject, issued_at=now, expires_at=now + 3600)
    return token


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _owned_by_a(client, server) -> str:
    tok_a = await _session(server, "apple:A")
    r = await client.post("/bridge/v1/chat", headers=_bearer(tok_a),
                          json={"message": "my secret plan", "session_id": "conv-A"})
    assert r.status == 200, await r.text()
    return tok_a


async def test_resume_does_not_describe_another_accounts_conversation():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        tok_a = await _owned_by_a(client, server)
        tok_b = await _session(server, "apple:B")
        r = await client.post("/bridge/v1/session/resume", headers=_bearer(tok_b), json={"session_id": "conv-A"})
        assert r.status == 403, await r.text()
        assert "message_count" not in await r.text()
        r = await client.post("/bridge/v1/session/resume", headers=_bearer(tok_a), json={"session_id": "conv-A"})
        assert r.status == 200
        data = (await r.json())["data"]
        assert data["resumed"] is True and data["message_count"] == 2


async def test_a_wallet_cannot_be_linked_into_another_accounts_conversation():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        await _owned_by_a(client, server)
        siwe = await _session(server, W)
        r = await client.post("/bridge/v1/wallet/link", headers={"X-Wallet-Session": siwe},
                              json={"session_id": "conv-A"})
        assert r.status == 403, await r.text()


async def test_a_link_held_by_one_account_is_neither_shown_to_nor_overwritten_by_another():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        siwe_w = await _session(server, W)
        r = await client.post("/bridge/v1/wallet/link", headers={"X-Wallet-Session": siwe_w},
                              json={"session_id": "conv-W"})
        assert r.status == 200, await r.text()

        tok_b = await _session(server, "apple:B")
        r = await client.get("/bridge/v1/wallet/status", headers=_bearer(tok_b), params={"session_id": "conv-W"})
        assert W not in await r.text(), "another account read the linked address"
        r = await client.get("/bridge/v1/dashboard", headers=_bearer(tok_b), params={"session_id": "conv-W"})
        assert W not in await r.text(), "another account read the linked address on the dashboard"

        other = "0x" + "b" * 40
        siwe_o = await _session(server, other)
        r = await client.post("/bridge/v1/wallet/link", headers={"X-Wallet-Session": siwe_o},
                              json={"session_id": "conv-W"})
        assert r.status == 403, await r.text()

        r = await client.get("/bridge/v1/wallet/status", headers={"X-Wallet-Session": siwe_w},
                             params={"session_id": "conv-W"})
        body = await r.json()
        assert body["data"]["linked"] is True and body["data"]["address"] == W, body


async def test_a_direct_action_is_attributed_to_the_account_that_asked_not_the_one_that_linked():
    server = _server()
    calls: list[dict] = []

    class _Recorder:
        async def execute(self, action, service=None, params=None, *, caller_identity=""):
            calls.append({"action": action, "caller_identity": caller_identity})
            return json.dumps({"status": "ok"})

    async with TestClient(TestServer(server.create_app())) as client:
        server.service_dispatcher = _Recorder()
        siwe_w = await _session(server, W)
        r = await client.post("/bridge/v1/wallet/link", headers={"X-Wallet-Session": siwe_w},
                              json={"session_id": "conv-W"})
        assert r.status == 200, await r.text()
        tok_b = await _session(server, "apple:B")
        r = await client.post("/bridge/v1/action", headers=_bearer(tok_b),
                              json={"action": "noop", "params": {"x": 1}, "session_id": "conv-W"})
        assert r.status == 200, await r.text()
    assert calls, "the action never reached the dispatcher"
    assert calls[0]["caller_identity"] == "apple:B", calls


async def test_a_push_token_cannot_be_attached_to_another_accounts_conversation():
    from runtime.notifications.token_store import PushTokenStore

    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        await _owned_by_a(client, server)
        tok_b = await _session(server, "apple:B")
        r = await client.post("/bridge/v1/push/register", headers=_bearer(tok_b),
                              json={"push_token": "0xB_DEVICE", "session_id": "conv-A"})
        assert r.status == 403, await r.text()
        store = PushTokenStore(server.react_loop.memory.db)
        assert not await store.tokens_for(session_id="conv-A")


async def test_account_deletion_removes_the_push_tokens_the_account_registered():
    """The docs say DELETE /api/v1/auth/account removes the account's push
    tokens. It looked them up by the bearer TOKEN string as a session id, and
    register files a device under the conversation id — so it matched nothing
    and every device stayed registered. Tokens now carry the account that
    registered them."""
    from runtime.notifications.token_store import PushTokenStore

    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        tok_p = await _session(server, "apple:P")
        tok_q = await _session(server, "apple:Q")
        for body in ({"push_token": "DEV-P-1"}, {"push_token": "DEV-P-2", "session_id": "inst-p"}):
            r = await client.post("/bridge/v1/push/register", headers=_bearer(tok_p), json=body)
            assert r.status == 200, await r.text()
        r = await client.post("/bridge/v1/push/register", headers=_bearer(tok_q), json={"push_token": "DEV-Q"})
        assert r.status == 200
        store = PushTokenStore(server.react_loop.memory.db)
        assert set(await store.all_tokens()) == {"DEV-P-1", "DEV-P-2", "DEV-Q"}

        r = await client.delete("/api/v1/auth/account", headers=_bearer(tok_p))
        assert r.status == 200, await r.text()
        assert set(await store.all_tokens()) == {"DEV-Q"}, "the deleted account's devices are still registered"
