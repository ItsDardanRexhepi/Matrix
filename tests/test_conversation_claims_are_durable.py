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
        if self.memory is not None:  # as ReActLoop._remember_turn saves it, before run returns
            await self.memory.save_turn(ctx.agent_name, str(ctx.conversation[-1].content), reply,
                                        scope=ctx.metadata["user_context"]["memory_scope"],
                                        claim=ctx.metadata.get("turn_claim"))
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


# ── a turn is tied to the claim it was admitted under, not to an owner string ──
#
# The save compared only the owner string. Account deletion erases the claim;
# the same subject signing in again (a SIWE address and an Apple sub are
# stable) re-creates a claim with the same owner string. So a turn still
# running from before the deletion either (a) found "the same owner" on the
# re-claimed conversation and was written back into it and into the new
# account's memory, or (b) found the conversation unclaimed, was refused, and
# the refusal re-erased ALL of the subject's scoped memory — the new account's.
# Driven through the real ReAct loop; the model is held at the router.

class _HeldRouter:
    def __init__(self, marker: str):
        self.marker = marker
        self.armed = True
        self.in_flight = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, messages, tools=None, **kwargs):
        last_user = next((str(m.content) for m in reversed(messages) if m.role == "user"), "")
        if self.armed and self.marker in last_user:
            self.armed = False
            self.in_flight.set()
            await self.release.wait()
        return SimpleNamespace(content="ok", tool_calls=[], provider="stub")


async def _delete_and_sign_in_again(client, server, headers, subject: str) -> dict:
    resp = await client.delete("/api/v1/auth/account", headers=headers)
    assert resp.status == 200, await resp.text()
    now = time.time()
    await server.wallet_sessions.add(token=f"again-{subject}", address=subject, issued_at=now, expires_at=now + 3600)
    return {"Authorization": f"Bearer again-{subject}"}


def _rows_with(memory, text: str) -> tuple[list, list]:
    conv = memory.db.fetchall_sync("SELECT session_id, content FROM conversation_turns WHERE content LIKE ?",
                                   (f"%{text}%",))
    agent = memory.db.fetchall_sync("SELECT agent, user_msg FROM agent_turns WHERE user_msg LIKE ?",
                                    (f"%{text}%",))
    return [dict(r) for r in conv], [dict(r) for r in agent]


@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_a_turn_from_before_deletion_is_not_written_into_the_same_subjects_new_claim(entrance):
    server = _server()
    router = _HeldRouter("4711")
    server.react_loop.router.complete = router.complete
    memory = server.react_loop.memory
    sid = "leaving-conv"
    async with TestClient(TestServer(server.create_app())) as client:
        leaver = await _session(server, "apple:leaver")
        assert await _drive(client, "/chat", {"message": "first", "session_id": sid}, leaver) == 200
        turn = asyncio.ensure_future(_drive(client, entrance, {"message": "my secret is 4711", "session_id": sid}, leaver))
        await asyncio.wait_for(router.in_flight.wait(), 10)

        again = await _delete_and_sign_in_again(client, server, leaver, "apple:leaver")
        assert await _drive(client, "/chat", {"message": "hello again", "session_id": sid}, again) == 200
        router.release.set()
        await asyncio.wait_for(turn, 15)

        conv, agent = _rows_with(memory, "4711")
        assert not conv, f"{entrance}: the deleted account's turn was written into the new claim: {conv}"
        assert not agent, f"{entrance}: the deleted account's turn was written into the new account's memory: {agent}"
        kept_conv, kept_agent = _rows_with(memory, "hello again")
        assert kept_conv and kept_agent, (entrance, kept_conv, kept_agent)


@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_a_refused_turn_from_before_deletion_leaves_the_new_accounts_memory_alone(entrance):
    server = _server()
    router = _HeldRouter("4711")
    server.react_loop.router.complete = router.complete
    memory = server.react_loop.memory
    sid = "leaving-conv"
    async with TestClient(TestServer(server.create_app())) as client:
        leaver = await _session(server, "apple:leaver")
        assert await _drive(client, "/chat", {"message": "first", "session_id": sid}, leaver) == 200
        turn = asyncio.ensure_future(_drive(client, entrance, {"message": "my secret is 4711", "session_id": sid}, leaver))
        await asyncio.wait_for(router.in_flight.wait(), 10)

        again = await _delete_and_sign_in_again(client, server, leaver, "apple:leaver")
        assert await _drive(client, "/chat", {"message": "new account fact", "session_id": "other-conv"}, again) == 200
        router.release.set()
        await asyncio.wait_for(turn, 15)

        conv, agent = _rows_with(memory, "4711")
        assert not conv and not agent, (entrance, conv, agent)
        kept_conv, kept_agent = _rows_with(memory, "new account fact")
        assert kept_conv, f"{entrance}: the new account's conversation was erased"
        assert kept_agent, f"{entrance}: the refused old turn erased the new account's scoped memory"


async def test_a_turn_whose_account_is_deleted_before_its_loop_starts_leaves_no_protocol_state():
    """Between admission and the loop's start a handler awaits (/chat marks the
    first-boot greeting; /chat/stream writes its headers). A deletion landing
    there used to leave the loop to create a fresh protocol stack for the
    deleted subject and record the turn's "User said: …" in it — shown to the
    same subject's next prompt after signing in again — or, when the deletion
    landed before the handler built the turn's context (the session gone, so
    the turn ran in the conversation's scope), to the next caller naming the
    erased conversation's id."""
    server = _server()
    calls: list[str] = []

    async def complete(messages, tools=None, **kwargs):
        calls.append("\n".join(str(m.content) for m in messages))
        return SimpleNamespace(content="ok", tool_calls=[], provider="stub")

    server.react_loop.router.complete = complete
    memory = server.react_loop.memory
    held = asyncio.Event()
    release = asyncio.Event()
    real_mark = memory.mark_first_boot_sent

    async def mark_first_boot_sent(session_id):
        if session_id == "gap-conv":
            held.set()
            await release.wait()
        return await real_mark(session_id)

    memory.mark_first_boot_sent = mark_first_boot_sent
    async with TestClient(TestServer(server.create_app())) as client:
        leaver = await _session(server, "apple:gap")
        turn = asyncio.ensure_future(_drive(client, "/chat", {"message": "GAP-SECRET-77 is my pin",
                                                              "session_id": "gap-conv"}, leaver))
        await asyncio.wait_for(held.wait(), 10)
        again = await _delete_and_sign_in_again(client, server, leaver, "apple:gap")
        release.set()
        await asyncio.wait_for(turn, 15)
        assert not any("GAP-SECRET-77" in c for c in calls), "the turn ran after its claim was erased"

        calls.clear()
        assert await _drive(client, "/chat", {"message": "hello", "session_id": "gap-other"}, again) == 200
        # The erased conversation is unclaimed again: anyone naming its id continues it.
        assert await _drive(client, "/chat", {"message": "hello", "session_id": "gap-conv"}) == 200
        assert len(calls) == 2 and not any("GAP-SECRET-77" in c for c in calls), (
            "a deleted account's turn left protocol state a later caller was shown")
        conv, agent = _rows_with(memory, "GAP-SECRET-77")
        assert not conv and not agent, (conv, agent)
