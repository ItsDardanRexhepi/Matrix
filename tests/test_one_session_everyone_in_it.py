"""T3 — one session, everyone in it (register entry::DV-CONV-INJECT-2,
entry::B3-JARVIS-PATTERN-LEAK, §D3.6, C2/C2b).

What the register measured before this change, at the pin:

  * Every chat request that omitted ``session_id`` landed in ONE persisted
    conversation, ``"default"`` — publicly writable and replayed to a
    tool-enabled agent. The iOS app's REST fallback and push registration
    sent exactly that literal.
  * ``react_loop`` saved every user's turn into the AGENT's memory, keyed by
    agent name alone, and rendered that memory — [User Facts] with wallet
    addresses and goals, plus the last five turns — into every caller's
    system prompt.
  * Jarvis kept "User said: …" patterns and the active plan per agent, so one
    caller's words became the next caller's "observed conversation patterns".
  * Nothing recorded who a conversation belonged to, so anyone naming a
    session id continued it, and erasure could not find a user's rows.

THE CONTROL (M2 plan T3): two sessions, ``0xTEST_A`` in A's message, the
messages handed to the model for B captured at ``router.complete`` — present
before, absent after. Driven through the public surface the way C2 was.
"""

from __future__ import annotations

import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "tests")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from gateway.server import GatewayServer  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

A_SECRET = "my wallet is 0xTEST_A and my goal is to buy a house in Lisbon"


def _server(api_key: str = "") -> GatewayServer:
    scratch = tempfile.mkdtemp(prefix="the-matrix-t3-")
    config = {**SWEEP_CONFIG, "memory_dir": scratch,
              "database": {**SWEEP_CONFIG.get("database", {}), "path": f"{scratch}/t3.db"},
              "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": api_key}}
    server = GatewayServer(config)
    # The model, stubbed at the router: every message list it receives is captured.
    server.react_loop.router.complete = AsyncMock(
        return_value=SimpleNamespace(content="ok", tool_calls=[], provider="stub"))
    return server


def _rendered_for_last_call(server: GatewayServer) -> str:
    kwargs = server.react_loop.router.complete.call_args.kwargs
    return "\n".join(str(getattr(m, "content", m)) for m in kwargs["messages"])


async def _session(server: GatewayServer, subject: str, ttl: float = 3600) -> str:
    token = f"tok-{subject}"
    now = time.time()
    await server.wallet_sessions.add(token=token, address=subject, issued_at=now, expires_at=now + ttl)
    return token


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class _FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}
        self.query = {}


# ── THE CONTROL ──────────────────────────────────────────────────────────────

async def test_control_one_callers_text_is_absent_from_another_callers_prompt():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        r = await client.post("/chat", json={"message": A_SECRET, "session_id": "conv-A"})
        assert r.status == 200, await r.text()
        r = await client.post("/chat", json={"message": "hello", "session_id": "conv-B"})
        assert r.status == 200, await r.text()
        rendered = _rendered_for_last_call(server)
        assert "0xTEST_A" not in rendered, "A's message reached B's model call"
        assert "Lisbon" not in rendered


async def test_the_same_caller_still_gets_their_own_memory():
    """Scoping must not amount to amnesia: A's second turn sees A's first."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        await client.post("/chat", json={"message": A_SECRET, "session_id": "conv-A"})
        r = await client.post("/chat", json={"message": "what is my goal?", "session_id": "conv-A"})
        assert r.status == 200
        assert "0xTEST_A" in _rendered_for_last_call(server)


async def test_control_holds_across_two_signed_in_accounts_on_the_app_path():
    """The iOS REST fallback: two Apple accounts, no session_id sent at all."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        tok_x = await _session(server, "apple:X")
        tok_y = await _session(server, "apple:Y")
        r = await client.post("/bridge/v1/chat", headers=_bearer(tok_x), json={"message": A_SECRET})
        assert r.status == 200, await r.text()
        body = await r.json()
        assert body["data"]["session_id"] == "user:apple:X", body
        r = await client.post("/bridge/v1/chat", headers=_bearer(tok_y), json={"message": "hello"})
        assert r.status == 200, await r.text()
        assert "0xTEST_A" not in _rendered_for_last_call(server)
        r = await client.post("/bridge/v1/chat", headers=_bearer(tok_x), json={"message": "and my goal?"})
        assert r.status == 200
        assert "0xTEST_A" in _rendered_for_last_call(server)


# ── "default" is not a session ───────────────────────────────────────────────

def test_production_refuses_the_shared_default_session(monkeypatch):
    server = _server()
    monkeypatch.setattr("gateway.server.is_production_mode", lambda: True)
    assert server._resolve_session_id(_FakeRequest(), None)[1]
    assert server._resolve_session_id(_FakeRequest(), "default")[1]
    assert server._resolve_session_id(_FakeRequest(), "  ")[1]
    assert server._resolve_session_id(_FakeRequest(), "conv-1") == ("conv-1", None)


def test_development_keeps_default_for_local_runs(monkeypatch):
    server = _server()
    monkeypatch.setattr("gateway.server.is_production_mode", lambda: False)
    assert server._resolve_session_id(_FakeRequest(), None) == ("default", None)


async def test_a_signed_in_caller_without_a_session_id_gets_their_own_conversation(monkeypatch):
    server = _server()
    monkeypatch.setattr("gateway.server.is_production_mode", lambda: True)
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _session(server, "apple:S")
        r = await client.post("/bridge/v1/chat", headers=_bearer(token), json={"message": "hi", "session_id": "default"})
        assert r.status == 200, await r.text()
        assert (await r.json())["data"]["session_id"] == "user:apple:S"
        r = await client.post("/bridge/v1/chat", json={"message": "hi"})
        assert r.status == 400
        assert "session" in (await r.json())["error"].lower() or "session" in (await r.text()).lower()


async def test_push_registration_never_lands_on_the_shared_session():
    from runtime.notifications.token_store import PushTokenStore
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _session(server, "apple:P")
        r = await client.post("/bridge/v1/push/register", headers=_bearer(token),
                              json={"push_token": "0xTEST_APNS", "session_id": "default"})
        assert r.status == 200, await r.text()
        store = PushTokenStore(server.react_loop.memory.db)
        assert await store.tokens_for(session_id="user:apple:P")
        assert not await store.tokens_for(session_id="default")


# ── ownership (C2b) ──────────────────────────────────────────────────────────

async def test_a_conversation_belongs_to_the_account_that_started_it():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        tok_x = await _session(server, "apple:X")
        tok_y = await _session(server, "apple:Y")
        r = await client.post("/chat", headers=_bearer(tok_x), json={"message": A_SECRET, "session_id": "shared-1"})
        assert r.status == 200, await r.text()
        r = await client.post("/chat", headers=_bearer(tok_y), json={"message": "hi", "session_id": "shared-1"})
        assert r.status == 403
        r = await client.post("/chat", json={"message": "hi", "session_id": "shared-1"})
        assert r.status == 403, "anonymous continuation of an owned conversation"
        r = await client.post("/chat", headers=_bearer(tok_x), json={"message": "still me", "session_id": "shared-1"})
        assert r.status == 200
        rows = await server.react_loop.memory.db.fetchall(
            "SELECT DISTINCT owner FROM conversation_turns WHERE session_id = ?", ("shared-1",))
        assert [r["owner"] for r in rows] == ["apple:X"], "the owner is persisted with the rows"


async def test_an_ownerless_conversation_is_claimed_by_the_first_signed_in_caller():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        r = await client.post("/chat", json={"message": "hi", "session_id": "anon-1"})
        assert r.status == 200
        r = await client.post("/chat", json={"message": "hi again", "session_id": "anon-1"})
        assert r.status == 200, "anonymous callers keep their unclaimed conversation"
        tok_x = await _session(server, "apple:X")
        r = await client.post("/chat", headers=_bearer(tok_x), json={"message": "mine now", "session_id": "anon-1"})
        assert r.status == 200
        r = await client.post("/chat", json={"message": "hi", "session_id": "anon-1"})
        assert r.status == 403


async def test_account_deletion_erases_the_accounts_conversations_and_memory():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        tok_x = await _session(server, "apple:X")
        await client.post("/chat", headers=_bearer(tok_x), json={"message": A_SECRET, "session_id": "mine-1"})
        memory = server.react_loop.memory
        assert "0xTEST_A" in memory.get_context("trinity", scope="apple:X")
        r = await client.delete("/api/v1/auth/account", headers=_bearer(tok_x))
        assert r.status == 200, await r.text()
        # The app presents its session as the Bearer; the handler read only
        # X-Wallet-Session and deleted nothing while answering 200 (found here).
        assert server.wallet_sessions.get(tok_x) is None, "the session itself must be gone"
        rows = await memory.db.fetchall("SELECT COUNT(*) AS n FROM conversation_turns WHERE owner = ?", ("apple:X",))
        assert rows[0]["n"] == 0
        assert memory.get_context("trinity", scope="apple:X") == ""


# ── the pieces ───────────────────────────────────────────────────────────────

async def test_agent_memory_is_scoped_and_the_shared_memory_stays_out_of_scoped_prompts():
    server = _server()
    async with TestClient(TestServer(server.create_app())):
        memory = server.react_loop.memory
        await memory.save_turn("trinity", "hello from s1", "hi", scope="s1")
        await memory.save_turn("trinity", "operator note", "noted")          # unscoped, shared
        assert "hello from s1" in memory.get_context("trinity", scope="s1")
        assert memory.get_context("trinity", scope="s2") == ""
        assert "hello from s1" not in memory.get_context("trinity")
        assert "operator note" not in memory.get_context("trinity", scope="s1")


def test_protocol_stacks_are_per_scope_with_a_cap():
    server = _server()
    loop = server.react_loop
    a = loop._get_protocol_stack("trinity", "u1")
    assert loop._get_protocol_stack("trinity", "u1") is a
    assert loop._get_protocol_stack("trinity", "u2") is not a
    loop._protocol_stack_cap = 2
    loop._get_protocol_stack("trinity", "u3")
    assert ("trinity", "u1") not in loop._protocol_stacks, "least-recently-used stack evicted"


def test_memory_scope_is_the_account_when_signed_in_else_the_conversation():
    server = _server()
    assert server._memory_scope(_FakeRequest(), "conv-9") == "conv:conv-9"
    # An anonymous id spelled like an account subject still names a conversation.
    assert server._memory_scope(_FakeRequest(), "apple:X") == "conv:apple:X"
