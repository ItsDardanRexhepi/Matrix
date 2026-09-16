"""The conversation working set is bounded in the number of conversations.

Every chat entrance takes the conversation id from the caller and creates the
in-memory entry on first touch. The history of ONE conversation was trimmed
(100 → 50 messages); the NUMBER of conversations held was not: the gateway's
``conversations`` dict, the memory manager's ``_conv_cache`` / ``_conv_owner``
/ ``_loaded_conversations``, its per-scope agent-memory caches (an anonymous
caller's scope IS its conversation id) and the ``first_boot`` set all kept an
entry for every id any caller ever named, for the life of the process. The
turns are on disk already, so this was RAM duplication with no ceiling.

Bounding a cache is only honest if eviction loses nothing, so the properties
come in pairs: the working set stays at the cap, AND an evicted conversation
continues from the store with its history and its owner intact. That second
half is why the bridge entrance now hydrates and persists like the other three
— it did neither, so its conversations existed only in the dict.
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
from runtime.memory.manager import MemoryManager  # noqa: E402
from test_chat_entrances_one_posture import ENTRANCES, _drive  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

CAP = 3


def _config(scratch: str) -> dict:
    return {**SWEEP_CONFIG, "memory_dir": scratch,
            "database": {"path": f"{scratch}/c.db"},
            "conversation_cache": CAP, "agent_memory_cache": CAP}


def _server() -> GatewayServer:
    server = GatewayServer(_config(tempfile.mkdtemp(prefix="opnmatrx-convcache-")))
    server.react_loop.run = AsyncMock(
        return_value=SimpleNamespace(response="ok", tool_calls=[], provider="stub"))
    return server


def _memory_sizes(memory: MemoryManager) -> dict:
    return {
        "_conv_cache": len(memory._conv_cache),
        "_conv_owner": len(memory._conv_owner),
        "_loaded_conversations": len(memory._loaded_conversations),
    }


def _last_context_text(server: GatewayServer) -> str:
    (context,), _ = server.react_loop.run.call_args
    return " | ".join(str(m.content) for m in context.conversation)


async def _session(server: GatewayServer, subject: str) -> dict:
    token = f"tok-{subject}"
    now = time.time()
    await server.wallet_sessions.add(token=token, address=subject, issued_at=now, expires_at=now + 3600)
    return {"Authorization": f"Bearer {token}"}


# ── the ceiling ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_the_working_set_stays_at_the_cap_whatever_ids_callers_name(entrance):
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        for i in range(4 * CAP):
            status = await _drive(client, entrance, {"message": f"hi {i}", "session_id": f"{entrance}-{i}"})
            assert status == 200, (entrance, i, status)
        assert len(server.conversations) <= CAP, (entrance, len(server.conversations))
        sizes = _memory_sizes(server.react_loop.memory)
        assert all(v <= CAP for v in sizes.values()), (entrance, sizes)


async def test_naming_ids_on_the_describe_only_legs_allocates_no_unbounded_state():
    """/bridge/v1/session/resume reads ownership for any id it is sent."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        for i in range(4 * CAP):
            resp = await client.post("/bridge/v1/session/resume", json={"session_id": f"probe-{i}"})
            await resp.read()
        sizes = _memory_sizes(server.react_loop.memory)
        assert all(v <= CAP for v in sizes.values()), sizes


async def test_agent_memory_caches_are_bounded_in_scopes_and_evicted_scopes_reload():
    memory = MemoryManager(_config(tempfile.mkdtemp(prefix="opnmatrx-agentcache-")))
    for i in range(4 * CAP):
        await memory.save_turn("trinity", f"my wallet is 0x{i:040x}", "noted", scope=f"anon-{i}")
        await memory.write(f"trinity@anon-{i}", "pref", i)
    assert len(memory._turn_cache) <= CAP, len(memory._turn_cache)
    assert len(memory._kv_cache) <= CAP, len(memory._kv_cache)
    assert len(memory._loaded_agents) <= CAP, len(memory._loaded_agents)
    # The first scope was evicted long ago; its memory is on disk, not gone.
    assert f"0x{0:040x}" in memory.get_context("trinity", scope="anon-0")
    assert memory.get("trinity@anon-0", "pref") == 0


async def test_first_boot_tracking_holds_no_set_of_every_session_ever_greeted():
    scratch = tempfile.mkdtemp(prefix="opnmatrx-firstboot-")
    memory = MemoryManager(_config(scratch))
    for i in range(4 * CAP):
        await memory.mark_first_boot_sent(f"greeted-{i}")
    assert len(getattr(memory, "_first_boot_cache", None) or ()) <= CAP
    # A fresh process still knows every one of them.
    again = MemoryManager(_config(scratch))
    assert all(again.is_first_boot_sent(f"greeted-{i}") for i in range(4 * CAP))
    assert not again.is_first_boot_sent("never-greeted")


# ── eviction loses nothing ───────────────────────────────────────────────────

@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_an_evicted_conversation_continues_with_its_history(entrance):
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        assert await _drive(client, entrance, {"message": "remember pineapple", "session_id": "keep"}) == 200
        for i in range(2 * CAP):
            assert await _drive(client, entrance, {"message": "x", "session_id": f"other-{i}"}) == 200
        assert "keep" not in server.conversations  # it really was evicted
        assert await _drive(client, entrance, {"message": "what fruit?", "session_id": "keep"}) == 200
        text = _last_context_text(server)
        assert "remember pineapple" in text and "what fruit?" in text, (entrance, text)


@pytest.mark.parametrize("first,then", [("/bridge/v1/chat", "/chat"), ("/chat", "/bridge/v1/chat"),
                                        ("/bridge/v1/chat", "/ws")])
async def test_a_conversation_is_one_history_across_entrances(first, then):
    """The bridge neither hydrated from nor wrote to the store, so a
    conversation begun there was wiped the moment another entrance loaded it."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        assert await _drive(client, first, {"message": "remember mango", "session_id": "one"}) == 200
        assert await _drive(client, then, {"message": "and now?", "session_id": "one"}) == 200
        text = _last_context_text(server)
        assert "remember mango" in text, (first, then, text)


@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_an_evicted_conversation_keeps_its_owner(entrance):
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        owner = await _session(server, "apple:owner-1")
        assert await _drive(client, entrance, {"message": "mine", "session_id": "owned"}, owner) == 200
        for i in range(2 * CAP):
            assert await _drive(client, entrance, {"message": "x", "session_id": f"filler-{i}"}) == 200
        assert "owned" not in server.react_loop.memory._conv_owner
        status = await _drive(client, entrance, {"message": "let me in", "session_id": "owned"})
        # /ws answers with an error frame, which the shared driver reads as 400.
        assert status == (400 if entrance == "/ws" else 403), (entrance, status)
        assert "let me in" not in _last_context_text(server), entrance


async def test_a_claim_on_a_stored_conversation_survives_eviction_even_if_its_turn_failed():
    """A signed-in caller claims an ownerless stored conversation, and the
    model fails on that turn — so no save carries the owner. The claim must
    not live only in the evictable cache."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        assert await _drive(client, "/chat", {"message": "anon hello", "session_id": "claimed"}) == 200
        server.react_loop.run.side_effect = RuntimeError("model down")
        claimer = await _session(server, "apple:claimer")
        await _drive(client, "/chat", {"message": "claiming", "session_id": "claimed"}, claimer)
        server.react_loop.run.side_effect = None
        for i in range(2 * CAP):
            assert await _drive(client, "/chat", {"message": "x", "session_id": f"pad-{i}"}) == 200
        other = await _session(server, "apple:someone-else")
        status = await _drive(client, "/chat", {"message": "mine now?", "session_id": "claimed"}, other)
        assert status == 403, status


async def test_account_deletion_leaves_no_copy_of_the_conversation_in_the_gateway():
    """erase_owner cleared the store and the memory manager's cache; the
    gateway's own copy kept the history, so the next caller naming the id —
    now ownerless — was handed the deleted account's conversation."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        owner = await _session(server, "apple:leaver")
        assert await _drive(client, "/chat", {"message": "my secret is 4711", "session_id": "gone"}, owner) == 200
        resp = await client.delete("/api/v1/auth/account", headers=owner)
        assert resp.status == 200, await resp.text()
        assert await _drive(client, "/chat", {"message": "hello?", "session_id": "gone"}) == 200
        text = _last_context_text(server)
        assert "4711" not in text, text
