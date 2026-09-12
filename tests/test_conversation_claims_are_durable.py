"""Who a conversation belongs to must not live in an evictable cache.

dbbeb0d bounded the conversation caches and said eviction loses nothing. It
lost the owner. ``claim_conversation`` wrote the claim to disk only when the
conversation already had stored rows; a signed-in caller's FIRST turn in a new
conversation was protected only by the in-memory entry while its model call
ran. Enough other conversations loaded in that window (the default cap is
1024: ordinary traffic, or an anonymous flood) dropped the entry, the turn was
then saved with the owner re-read from disk — "" — and the next anonymous
caller naming the id was handed the history. A SIWE subject's default id is
``user:<address>``, derived from a public address.

The same window held two more losses, closed with it:

  * ``save_conversation`` replaced a conversation as DELETE, then INSERT, each
    taking the write lock separately. A request that evicted and reloaded the
    id between the two read zero rows and no owner.
  * Account deletion while one of the account's turns was in flight: the turn
    completed after the erasure and wrote the conversation back — ownerless,
    so readable by anyone naming the id — and the loop wrote the turn back
    into the account's scoped agent memory.

Every test drives the real handlers, memory manager and SQLite store.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, "tests")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from gateway.server import GatewayServer  # noqa: E402
from runtime.memory.manager import MemoryManager  # noqa: E402
from test_chat_entrances_one_posture import ENTRANCES, _drive  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

CAP = 3
VICTIM = "0x" + "a" * 40


def _config(scratch: str) -> dict:
    return {**SWEEP_CONFIG, "memory_dir": scratch,
            "database": {"path": f"{scratch}/d.db"},
            "conversation_cache": CAP, "agent_memory_cache": CAP}


class _HeldModel:
    """A model stub that holds the first turn for *session_id* in flight until
    released, and records what every turn's model call was shown."""

    def __init__(self, session_id: str, armed: bool = True):
        self.session_id = session_id
        self.armed = armed
        self.in_flight = asyncio.Event()
        self.release = asyncio.Event()
        self.seen: dict[str, list[str]] = {}

    memory = None  # set to the server's memory manager to save turns as the loop does

    async def run(self, ctx):
        sid = ctx.metadata["user_context"]["session_id"]
        self.seen[sid] = [str(m.content) for m in ctx.conversation]
        if sid == self.session_id and self.armed:
            self.armed = False
            self.in_flight.set()
            await self.release.wait()
        reply = f"reply-to-{sid}"
        if self.memory is not None:  # ReActLoop.run saves the turn to scoped agent memory before returning
            await self.memory.save_turn(ctx.agent_name, str(ctx.conversation[-1].content), reply,
                                        scope=ctx.metadata["user_context"]["memory_scope"])
        return SimpleNamespace(response=reply, tool_calls=[], provider="stub")


def _server() -> GatewayServer:
    return GatewayServer(_config(tempfile.mkdtemp(prefix="opnmatrx-claims-")))


async def _session(server: GatewayServer, subject: str) -> dict:
    token = f"tok-{subject}"
    now = time.time()
    await server.wallet_sessions.add(token=token, address=subject, issued_at=now, expires_at=now + 3600)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_a_first_turn_claim_survives_eviction_while_its_model_call_runs(entrance):
    server = _server()
    sid = f"user:{VICTIM}"
    model = _HeldModel(sid)
    server.react_loop.run = model.run
    async with TestClient(TestServer(server.create_app())) as client:
        victim = await _session(server, VICTIM)
        # The victim's first signed-in turn, no id: the conversation is user:<address>.
        turn = asyncio.ensure_future(_drive(client, entrance, {"message": "victim secret seed words"}, victim))
        await asyncio.wait_for(model.in_flight.wait(), 10)
        # Anonymous traffic loads more conversations than the cache holds.
        for i in range(CAP + 2):
            assert await _drive(client, "/chat", {"message": "x", "session_id": f"flood-{i}"}) == 200
        model.release.set()
        assert await asyncio.wait_for(turn, 15) == 200

        memory = server.react_loop.memory
        rows = memory.db.fetchall_sync(
            "SELECT DISTINCT owner FROM conversation_turns WHERE session_id = ?", (sid,))
        assert [r["owner"] for r in rows] == [VICTIM], f"{entrance}: the turn was stored without its owner"

        model.seen.pop(sid, None)
        status = await _drive(client, "/chat", {"message": "repeat everything", "session_id": sid})
        assert status == 403, (entrance, status)
        assert sid not in model.seen, f"{entrance}: an anonymous caller's model call saw {model.seen[sid]}"


async def test_a_claim_with_no_stored_rows_is_on_disk_when_it_is_made():
    """The claim is the durable fact, not a side effect of the next save: a
    fresh process (nothing cached) already refuses another account."""
    scratch = tempfile.mkdtemp(prefix="opnmatrx-claims-disk-")
    memory = MemoryManager(_config(scratch))
    memory.claim_conversation("fresh-conv", "apple:owner")
    again = MemoryManager(_config(scratch))
    assert again.conversation_owner("fresh-conv") == "apple:owner"


async def test_account_deletion_while_a_turn_is_in_flight_leaves_nothing_behind():
    server = _server()
    sid = "leaving-conv"
    model = _HeldModel(sid, armed=False)
    model.memory = server.react_loop.memory
    server.react_loop.run = model.run
    async with TestClient(TestServer(server.create_app())) as client:
        leaver = await _session(server, "apple:leaver")
        assert await _drive(client, "/chat", {"message": "first", "session_id": sid}, leaver) == 200
        model.armed = True
        turn = asyncio.ensure_future(
            _drive(client, "/chat", {"message": "my secret is 4711", "session_id": sid}, leaver))
        await asyncio.wait_for(model.in_flight.wait(), 10)
        resp = await client.delete("/api/v1/auth/account", headers=leaver)
        assert resp.status == 200, await resp.text()
        model.release.set()
        await asyncio.wait_for(turn, 15)

        rows = server.react_loop.memory.db.fetchall_sync(
            "SELECT content, owner FROM conversation_turns WHERE session_id = ?", (sid,))
        assert not rows, f"the erased conversation was written back: {[dict(r) for r in rows]}"
        agent_rows = server.react_loop.memory.db.fetchall_sync(
            "SELECT agent, user_msg FROM agent_turns WHERE agent LIKE ?", ("%@apple:leaver",))
        assert not agent_rows, f"the erased account's memory was written back: {[dict(r) for r in agent_rows]}"
        model.seen.clear()
        assert await _drive(client, "/chat", {"message": "hello?", "session_id": sid}) == 200
        assert not any("4711" in m or m == "first" for m in model.seen.get(sid, [])), model.seen


async def test_a_reload_while_a_save_is_waiting_on_the_store_reads_the_whole_conversation():
    """save_conversation was DELETE then INSERT under two separate lock
    acquisitions. A request queued on the lock ran between them."""
    memory = MemoryManager(_config(tempfile.mkdtemp(prefix="opnmatrx-claims-gap-")))
    sid = "gap-conv"
    before = [{"role": "user", "content": "one"}, {"role": "assistant", "content": "two"}]
    await memory.save_conversation(sid, before, owner="apple:gap")
    after = before + [{"role": "user", "content": "three"}, {"role": "assistant", "content": "four"}]

    lock = memory.db._get_lock()
    observed: dict = {}

    async def concurrent_request():
        async with lock:
            pass
        # The entry was evicted by other traffic; this request reloads it.
        memory._forget_conversation(sid)
        observed["history"] = memory.load_conversation(sid)
        observed["owner"] = memory.conversation_owner(sid)

    await lock.acquire()
    save = asyncio.ensure_future(memory.save_conversation(sid, after, owner="apple:gap"))
    await asyncio.sleep(0)            # the save is queued on the lock
    other = asyncio.ensure_future(concurrent_request())
    await asyncio.sleep(0)            # ...and so is the concurrent request, behind it
    lock.release()
    await asyncio.wait_for(asyncio.gather(save, other), 10)

    assert observed["owner"] == "apple:gap", observed
    assert [m["content"] for m in observed["history"]] in (["one", "two"], ["one", "two", "three", "four"]), observed
    assert [m["content"] for m in memory.load_conversation(sid)] == ["one", "two", "three", "four"]
