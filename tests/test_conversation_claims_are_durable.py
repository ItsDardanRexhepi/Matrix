"""Who a conversation belongs to must not live in an evictable cache.

7ffe8de bounded the conversation caches and said eviction loses nothing. It
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
    return GatewayServer(_config(tempfile.mkdtemp(prefix="the-matrix-claims-")))


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
    scratch = tempfile.mkdtemp(prefix="the-matrix-claims-disk-")
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
    memory = MemoryManager(_config(tempfile.mkdtemp(prefix="the-matrix-claims-gap-")))
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
        self.shown: list[str] = []   # every model call's messages, joined

    async def complete(self, messages, tools=None, **kwargs):
        self.shown.append("\n".join(str(m.content) for m in messages))
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


# ── the unclaimed state has an identity too ──────────────────────────────────
#
# A turn admitted to an unclaimed conversation carried ("", ""), and erasing a
# claim deleted its row, which made the state ("", "") again. So an anonymous
# turn in flight while an account claimed the conversation and was then
# deleted matched its "claim" and was written back: into the conversation and
# into conv:<id> memory, with a reply generated from the pre-claim history the
# deletion had just removed, shown to the next caller naming the id.

@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_an_anonymous_turn_in_flight_through_a_claim_and_its_accounts_deletion_is_not_written_back(entrance):
    server = _server()
    router = _HeldRouter("ANON-HELD")
    server.react_loop.router.complete = router.complete
    memory = server.react_loop.memory
    sid = "shared-conv"
    async with TestClient(TestServer(server.create_app())) as client:
        assert await _drive(client, "/chat", {"message": "pre-sign-in: my pin is 5150", "session_id": sid}) == 200
        turn = asyncio.ensure_future(
            _drive(client, entrance, {"message": "ANON-HELD what is my pin?", "session_id": sid}))
        await asyncio.wait_for(router.in_flight.wait(), 10)

        account = await _session(server, "apple:abaacct")
        assert await _drive(client, "/chat", {"message": "ACCT-SECRET-31", "session_id": sid}, account) == 200
        assert memory.conversation_owner(sid) == "apple:abaacct"
        resp = await client.delete("/api/v1/auth/account", headers=account)
        assert resp.status == 200, await resp.text()
        assert _rows_with(memory, "5150") == ([], []), "the deletion did not erase the pre-claim turn"

        router.release.set()
        await asyncio.wait_for(turn, 15)

        for text in ("ANON-HELD", "5150", "ACCT-SECRET-31"):
            conv, agent = _rows_with(memory, text)
            assert not conv, f"{entrance}: {text!r} was written back into the erased conversation: {conv}"
            assert not agent, f"{entrance}: {text!r} was written back into conv:{sid} memory: {agent}"

        router.shown.clear()
        assert await _drive(client, "/chat", {"message": "anyone there?", "session_id": sid}) == 200
        assert len(router.shown) == 1, router.shown
        for text in ("ANON-HELD", "5150", "ACCT-SECRET-31"):
            assert text not in router.shown[0], f"{entrance}: the next caller naming the id was shown {text!r}"


@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_an_anonymous_turn_in_flight_while_another_conversations_account_is_deleted_is_stored(entrance):
    """Giving the unclaimed state an identity must not refuse turns whose
    conversation no deletion touched."""
    server = _server()
    router = _HeldRouter("ANON-KEEP")
    server.react_loop.router.complete = router.complete
    memory = server.react_loop.memory
    async with TestClient(TestServer(server.create_app())) as client:
        turn = asyncio.ensure_future(
            _drive(client, entrance, {"message": "ANON-KEEP stays", "session_id": "bystander-conv"}))
        await asyncio.wait_for(router.in_flight.wait(), 10)
        account = await _session(server, "apple:elsewhere")
        assert await _drive(client, "/chat", {"message": "mine", "session_id": "elsewhere-conv"}, account) == 200
        resp = await client.delete("/api/v1/auth/account", headers=account)
        assert resp.status == 200, await resp.text()
        router.release.set()
        assert await asyncio.wait_for(turn, 15) == 200

        conv, agent = _rows_with(memory, "ANON-KEEP")
        assert conv and agent, f"{entrance}: a turn no deletion touched was refused: {conv} {agent}"


async def test_an_unclaimed_claim_stops_standing_once_the_conversation_is_claimed_and_erased():
    memory = MemoryManager(_config(tempfile.mkdtemp(prefix="the-matrix-claims-unclaimed-")))
    before = memory.conversation_claim("c1")
    untouched = memory.conversation_claim("c2")
    assert memory.claim_stands(before) and before.owner == ""
    memory.claim_conversation("c1", "apple:x")
    assert not memory.claim_stands(before)
    assert await memory.erase_owner("apple:x") == ["c1"]
    assert memory.conversation_claim("c1").owner == ""
    assert not memory.claim_stands(before), "erasure restored the unclaimed state a pre-claim turn was admitted under"
    assert not await memory.save_conversation("c1", [{"role": "user", "content": "back"}], expect_claim=before)
    assert not await memory.save_turn("trinity", "back", "r", scope="conv:c1", claim=before)
    # A conversation the erasure did not touch is still unclaimed under the same claim.
    assert memory.claim_stands(untouched)
    assert await memory.save_conversation("c2", [{"role": "user", "content": "kept"}], expect_claim=untouched)
    # A turn admitted after the erasure is admitted under the new unclaimed state.
    after = memory.conversation_claim("c1")
    assert memory.claim_stands(after)
    assert await memory.save_turn("trinity", "fresh", "r", scope="conv:c1", claim=after)
    # ...and survives a fresh process reading the same store.
    again = MemoryManager(_config(memory.memory_dir.as_posix()))
    assert again.claim_stands(after) and not again.claim_stands(before)


async def test_the_erasure_log_is_pruned_and_a_turn_older_than_the_pruned_log_is_refused():
    """The log of erased ids is kept only for its retention window. A turn
    admitted unclaimed before an erasure whose entry was pruned cannot be
    cleared by the log any more, and is refused rather than assumed safe."""
    memory = MemoryManager({**_config(tempfile.mkdtemp(prefix="the-matrix-claims-prune-")),
                            "conversation_erasure_log_seconds": 60})
    before = memory.conversation_claim("c1")
    memory.claim_conversation("c9", "apple:gone")
    assert await memory.erase_owner("apple:gone") == ["c9"]
    assert memory.claim_stands(before), "an erasure of another conversation refused the turn"
    assert memory.db.fetchall_sync("SELECT session_id FROM conversation_erasures")  # kept within the window

    dropped = await memory.db.run_in_transaction(lambda conn: memory._prune_erasure_log_in(conn, time.time() + 120))
    assert dropped == 1
    assert not memory.db.fetchall_sync("SELECT session_id FROM conversation_erasures"), "the erased id outlived the window"
    assert not memory.claim_stands(before), "a turn older than the pruned log was assumed to stand"
    assert not await memory.save_conversation("c1", [{"role": "user", "content": "x"}], expect_claim=before)
    after = memory.conversation_claim("c1")
    assert memory.claim_stands(after)


async def test_the_periodic_sweep_prunes_the_erasure_log():
    from test_every_rate_limiter_is_swept import _one_sweep

    scratch = tempfile.mkdtemp(prefix="the-matrix-claims-sweep-")
    server = GatewayServer({**_config(scratch), "conversation_erasure_log_seconds": 0})
    memory = server.react_loop.memory
    memory.claim_conversation("swept-conv", "apple:swept")
    await memory.erase_owner("apple:swept")
    assert memory.db.fetchall_sync("SELECT session_id FROM conversation_erasures")
    await asyncio.sleep(0.01)
    await _one_sweep(server)
    assert not memory.db.fetchall_sync("SELECT session_id FROM conversation_erasures")


@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_a_turn_from_before_deletion_is_not_written_into_a_claim_made_by_a_surviving_second_session(entrance):
    """Deletion removes the session that asked for it, not the subject's other
    sessions: the same subject on a second device continues with no
    re-authentication. Its claim is still a new claim."""
    server = _server()
    router = _HeldRouter("4711")
    server.react_loop.router.complete = router.complete
    memory = server.react_loop.memory
    sid = "leaving-conv"
    async with TestClient(TestServer(server.create_app())) as client:
        leaver = await _session(server, "apple:leaver")
        now = time.time()
        await server.wallet_sessions.add(token="device2", address="apple:leaver", issued_at=now, expires_at=now + 3600)
        device2 = {"Authorization": "Bearer device2"}
        assert await _drive(client, "/chat", {"message": "first", "session_id": sid}, leaver) == 200
        turn = asyncio.ensure_future(_drive(client, entrance, {"message": "my secret is 4711", "session_id": sid}, leaver))
        await asyncio.wait_for(router.in_flight.wait(), 10)
        resp = await client.delete("/api/v1/auth/account", headers=leaver)
        assert resp.status == 200, await resp.text()
        assert await _drive(client, "/chat", {"message": "from device two", "session_id": sid}, device2) == 200
        router.release.set()
        await asyncio.wait_for(turn, 15)

        conv, agent = _rows_with(memory, "4711")
        assert not conv and not agent, (entrance, conv, agent)
        kept_conv, kept_agent = _rows_with(memory, "from device two")
        assert kept_conv and kept_agent, (entrance, kept_conv, kept_agent)


# ── The erasure log must not cost the erasure, nor keep the account ─────────
#
# 4580977 read conversation_erasure_log_seconds with float() inside the
# transaction that erases an account. A value float() rejects ("1h", a YAML
# null) raised there, rolled the whole erasure back, and the handler swallowed
# it: DELETE /api/v1/auth/account answered 200 and erased nothing. It also
# logged the account's own default conversation id, user:<subject>, which
# names the account, while the docs said the log keeps "no owner". And the log
# was pruned only by a deletion that erased a conversation, not "on the next
# deletion". If the state row was ever missing, erasure never advanced the
# sequence and a pre-claim anonymous turn was written back again.

def _erasure_ids(memory) -> list[str]:
    return [r["session_id"] for r in memory.db.fetchall_sync("SELECT session_id FROM conversation_erasures")]


@pytest.mark.parametrize("retention", ["1h", None, "nan", float("inf"), -5, True])
async def test_account_deletion_erases_the_account_whatever_the_erasure_log_retention_is_set_to(retention):
    scratch = tempfile.mkdtemp(prefix="the-matrix-claims-retention-")
    server = GatewayServer({**_config(scratch), "conversation_erasure_log_seconds": retention})
    server.react_loop.router.complete = _HeldRouter("never-held").complete
    memory = server.react_loop.memory
    async with TestClient(TestServer(server.create_app())) as client:
        account = await _session(server, "apple:misconf")
        assert await _drive(client, "/chat", {"message": "MISCONF-SECRET-8", "session_id": "mc-conv"}, account) == 200
        assert _rows_with(memory, "MISCONF-SECRET-8") != ([], [])
        resp = await client.delete("/api/v1/auth/account", headers=account)
        assert resp.status == 200, await resp.text()
        assert _rows_with(memory, "MISCONF-SECRET-8") == ([], []), f"retention={retention!r} undid the erasure"
        assert memory.conversation_claim("mc-conv").owner == "", f"retention={retention!r} left the claim"
        assert _erasure_ids(memory) == ["mc-conv"]


async def test_a_failing_prune_does_not_undo_the_accounts_erasure():
    server = _server()
    router = _HeldRouter("never-held")
    server.react_loop.router.complete = router.complete
    memory = server.react_loop.memory

    def broken_prune(conn, now):
        raise RuntimeError("prune failed")

    memory._prune_erasure_log_in = broken_prune
    async with TestClient(TestServer(server.create_app())) as client:
        account = await _session(server, "apple:prunefail")
        assert await _drive(client, "/chat", {"message": "PRUNEFAIL-SECRET", "session_id": "pf-conv"}, account) == 200
        resp = await client.delete("/api/v1/auth/account", headers=account)
        assert resp.status == 200, await resp.text()
        assert _rows_with(memory, "PRUNEFAIL-SECRET") == ([], []), "a prune failure rolled the erasure back"
        assert memory.conversation_claim("pf-conv").owner == ""
        assert _erasure_ids(memory) == ["pf-conv"], "the erasure was not logged"
        # Nor the gateway's copy: the next caller naming the id is shown none of it.
        router.shown.clear()
        assert await _drive(client, "/chat", {"message": "anyone?", "session_id": "pf-conv"}) == 200
        assert router.shown and "PRUNEFAIL-SECRET" not in router.shown[-1], router.shown


@pytest.mark.parametrize("retention", ["1h", None, "nan", float("inf"), -5, True, [60]])
async def test_an_unusable_retention_falls_back_to_the_default_window(retention, caplog):
    from runtime.memory.manager import ERASURE_LOG_SECONDS

    with caplog.at_level("WARNING", logger="runtime.memory.manager"):
        memory = MemoryManager({**_config(tempfile.mkdtemp(prefix="the-matrix-claims-badret-")),
                                "conversation_erasure_log_seconds": retention})
    memory.claim_conversation("c9", "apple:badret")
    assert await memory.erase_owner("apple:badret") == ["c9"]
    assert _erasure_ids(memory) == ["c9"], f"retention={retention!r}: pruned at once"
    now = time.time()
    await memory.db.run_in_transaction(lambda conn: memory._prune_erasure_log_in(conn, now + ERASURE_LOG_SECONDS - 60))
    assert _erasure_ids(memory) == ["c9"], f"retention={retention!r}: pruned inside the default window"
    await memory.db.run_in_transaction(lambda conn: memory._prune_erasure_log_in(conn, now + ERASURE_LOG_SECONDS + 60))
    assert _erasure_ids(memory) == [], f"retention={retention!r}: never pruned"
    assert any("conversation_erasure_log_seconds" in r.getMessage() for r in caplog.records), retention


async def test_a_deletion_that_erases_no_conversation_still_prunes_the_log():
    memory = MemoryManager({**_config(tempfile.mkdtemp(prefix="the-matrix-claims-emptyprune-")),
                            "conversation_erasure_log_seconds": 0})
    memory.claim_conversation("c9", "apple:first")
    assert await memory.erase_owner("apple:first") == ["c9"]
    assert _erasure_ids(memory) == ["c9"]
    await asyncio.sleep(0.01)
    assert await memory.erase_owner("apple:owns-nothing") == []
    assert _erasure_ids(memory) == [], "a deletion that erased no conversation did not prune"


async def test_account_deletion_keeps_no_user_subject_id_in_the_erasure_log():
    server = _server()
    server.react_loop.router.complete = _HeldRouter("never-held").complete
    memory = server.react_loop.memory
    subject = "apple:001234.deadbeef"
    async with TestClient(TestServer(server.create_app())) as client:
        account = await _session(server, subject)
        # No session_id: the conversation is the account's own user:<subject>.
        assert await _drive(client, "/chat", {"message": "DEFAULT-CONV-SECRET"}, account) == 200
        assert await _drive(client, "/chat", {"message": "named", "session_id": "named-conv"}, account) == 200
        assert memory.conversation_owner(f"user:{subject}") == subject
        resp = await client.delete("/api/v1/auth/account", headers=account)
        assert resp.status == 200, await resp.text()
        assert _rows_with(memory, "DEFAULT-CONV-SECRET") == ([], [])
        assert _erasure_ids(memory) == ["named-conv"], f"the log kept the account's own id: {_erasure_ids(memory)}"


async def test_an_unclaimed_claim_on_an_account_conversation_id_never_stands():
    """What makes leaving user:<subject> out of the log safe: no turn stands
    on such an id without its account's claim, whichever entrance admits it
    (the gateway answers 403 to every caller but the account)."""
    memory = MemoryManager(_config(tempfile.mkdtemp(prefix="the-matrix-claims-userid-")))
    sid = "user:apple:x"
    before = memory.conversation_claim(sid)
    assert before.owner == "" and not memory.claim_stands(before)
    assert not await memory.save_conversation(sid, [{"role": "user", "content": "squat"}], expect_claim=before)
    assert not await memory.save_turn("trinity", "squat", "r", scope=f"conv:{sid}", claim=before)
    memory.claim_conversation(sid, "apple:x")
    mine = memory.conversation_claim(sid)
    assert memory.claim_stands(mine)
    assert await memory.erase_owner("apple:x") == [sid]
    assert _erasure_ids(memory) == []
    assert not memory.claim_stands(before), "a pre-claim unclaimed turn on user:<subject> stood after the erasure"
    assert not memory.claim_stands(mine)


async def test_a_missing_erasure_state_row_refuses_unclaimed_turns_and_erasure_restores_it():
    memory = MemoryManager(_config(tempfile.mkdtemp(prefix="the-matrix-claims-staterow-")))
    before = memory.conversation_claim("c1")
    assert memory.claim_stands(before)
    memory.db.execute_sync("DELETE FROM conversation_erasure_state")
    gap = memory.conversation_claim("c2")
    assert not memory.claim_stands(gap), "an unclaimed turn stood with no erasure state to check it against"
    assert not memory.claim_stands(before)

    memory.claim_conversation("c1", "apple:x")
    assert await memory.erase_owner("apple:x") == ["c1"]
    assert not memory.claim_stands(before), "erasure with the state row missing restored the pre-claim state"
    assert not memory.claim_stands(gap)
    after = memory.conversation_claim("c1")
    assert memory.claim_stands(after), "erasure did not restore the erasure state"
    assert await memory.save_conversation("c1", [{"role": "user", "content": "fresh"}], expect_claim=after)


async def test_a_fresh_process_restores_a_missing_erasure_state_row():
    scratch = tempfile.mkdtemp(prefix="the-matrix-claims-staterow-boot-")
    memory = MemoryManager(_config(scratch))
    memory.claim_conversation("c1", "apple:x")
    assert await memory.erase_owner("apple:x") == ["c1"]
    memory.db.execute_sync("DELETE FROM conversation_erasure_state")
    again = MemoryManager(_config(scratch))
    fresh = again.conversation_claim("c1")
    assert again.claim_stands(fresh), "a fresh process refused every unclaimed turn"
    again.claim_conversation("c1", "apple:y")
    assert await again.erase_owner("apple:y") == ["c1"]
    assert not again.claim_stands(fresh)


async def test_restoring_a_missing_state_row_revives_no_turn_whose_erasure_was_pruned_meanwhile():
    """The restored row starts past every sequence number a live turn could
    hold, not just past the log: a log pruned while the row was missing no
    longer says how far erasures had gone."""
    from runtime.memory.manager import ERASURE_LOG_SECONDS

    memory = MemoryManager(_config(tempfile.mkdtemp(prefix="the-matrix-claims-staterow-prune-")))
    memory.claim_conversation("c0", "apple:a")
    assert await memory.erase_owner("apple:a") == ["c0"]
    mid = memory.conversation_claim("c1")          # admitted unclaimed after erasure 1
    assert memory.claim_stands(mid)
    memory.claim_conversation("c1", "apple:b")
    assert await memory.erase_owner("apple:b") == ["c1"]  # erasure 2 erases c1
    assert not memory.claim_stands(mid)
    memory.db.execute_sync("DELETE FROM conversation_erasure_state")
    await memory.db.run_in_transaction(
        lambda conn: memory._prune_erasure_log_in(conn, time.time() + ERASURE_LOG_SECONDS + 60))
    assert _erasure_ids(memory) == []
    memory.claim_conversation("c5", "apple:c")
    assert await memory.erase_owner("apple:c") == ["c5"]  # restores the row
    assert not memory.claim_stands(mid), "restoring the state row revived a turn whose erasure was pruned"


# ── A deletion that erased nothing is not answered as a success ─────────────
#
# handle_account_delete caught every exception from erase_owner at debug level
# and went on: it removed the push tokens and the session and answered 200
# {"success": true} with the account's conversations, scoped memory and claim
# all still stored — and the session gone, so the client could not retry. A
# retention value float() rejected was one way in (fixed in 7254f38); a store
# that raises for any other reason was still answered the same way.

async def test_a_deletion_whose_erasure_fails_is_answered_as_a_failure_and_can_be_retried():
    from runtime.notifications.token_store import PushTokenStore

    server = _server()
    server.react_loop.router.complete = _HeldRouter("never-held").complete
    memory = server.react_loop.memory
    subject = "apple:erasefail"
    real_erase_owner = memory.erase_owner

    async def store_unavailable(owner):
        raise RuntimeError("store unavailable")

    async with TestClient(TestServer(server.create_app())) as client:
        account = await _session(server, subject)
        assert await _drive(client, "/chat", {"message": "ERASEFAIL-SECRET", "session_id": "ef-conv"}, account) == 200
        r = await client.post("/bridge/v1/push/register", headers=account, json={"push_token": "DEV-EF"})
        assert r.status == 200, await r.text()
        store = PushTokenStore(memory.db)
        assert "DEV-EF" in await store.all_tokens()

        memory.erase_owner = store_unavailable
        resp = await client.delete("/api/v1/auth/account", headers=account)
        body = await resp.json()
        assert resp.status == 503, (resp.status, body)
        assert body.get("success") is not True and body.get("error"), body
        # Nothing after the erasure was removed: the session stays valid and the
        # device registered, so the same client can retry the deletion.
        assert server.wallet_sessions.get(f"tok-{subject}"), "a failed deletion removed the session"
        assert "DEV-EF" in await store.all_tokens(), "a failed deletion removed the push token"
        assert _rows_with(memory, "ERASEFAIL-SECRET") != ([], [])

        memory.erase_owner = real_erase_owner
        resp = await client.delete("/api/v1/auth/account", headers=account)
        assert resp.status == 200, await resp.text()
        assert _rows_with(memory, "ERASEFAIL-SECRET") == ([], [])
        assert memory.conversation_claim("ef-conv").owner == ""
        assert not server.wallet_sessions.get(f"tok-{subject}")
        assert "DEV-EF" not in await store.all_tokens()


# ── ...and a deletion the store fails PART WAY through is not a success either ─
#
# erase_owner erased the conversations and their claims in one transaction and
# then erased the scoped agent memory — the owner's scope and each conv:<id> —
# as separate statements after the commit. A statement that raised there was
# answered 503, correctly, but the erasure had already committed: the retry
# found no conversation of the account left (the claims were gone), returned
# [], and the handler forgot nothing and answered 200 {"success": true} while
# the gateway still held the account's conversation in ``conversations`` and
# the conv:<id> memory was still stored. The next caller naming the id was
# handed that history and wrote it back, ownerless — the resurrection this
# file's earlier tests close, reachable again through the retry path. One
# transaction now erases all of it, so a failure erases nothing and the retry
# does the whole job; and the gateway drops its own copies of the account's
# conversations whatever the erasure did, using ids read before it ran.

class _TrippingConn:
    """The real connection, with a trip wire on the statements it is given."""

    def __init__(self, conn, trip):
        self._conn = conn
        self._trip = trip

    def execute(self, sql, params=()):
        self._trip(sql)
        return self._conn.execute(sql, params)

    def executemany(self, sql, seq_of_params):
        self._trip(sql)
        return self._conn.executemany(sql, seq_of_params)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _store_fails_once_on(memory, needle: str, occurrence: int = 1) -> None:
    """Make the *occurrence*-th store statement containing *needle* raise,
    wherever the manager issues it: through ``Database.execute`` or inside a
    transaction.

    The injection does not care which of the two the erasure uses, so the same
    control holds whether the statement runs after a commit or within it. The
    erasure deletes the account's own scope before each conversation's, so
    occurrence 1 trips on the account's memory and occurrence 2 on the memory
    of a conversation it claimed."""
    import sqlite3

    db = memory.db
    armed = {"left": occurrence}
    real_execute, real_transaction = db.execute, db.run_in_transaction

    def trip(sql):
        if armed["left"] and needle in " ".join(str(sql).split()):
            armed["left"] -= 1
            if not armed["left"]:
                raise sqlite3.OperationalError("database is locked")

    async def execute(sql, params=None, *args, **kwargs):
        trip(sql)
        return await real_execute(sql, params, *args, **kwargs)

    async def run_in_transaction(work):
        return await real_transaction(lambda conn: work(_TrippingConn(conn, trip)))

    db.execute, db.run_in_transaction = execute, run_in_transaction


@pytest.mark.parametrize("occurrence", [1, 2])
async def test_a_deletion_the_store_fails_part_way_erases_nothing_and_the_retry_finishes_it(occurrence):
    server = _server()
    router = _HeldRouter("never-held")
    server.react_loop.router.complete = router.complete
    memory = server.react_loop.memory
    subject = "apple:partial"
    sid = "pt-conv"
    async with TestClient(TestServer(server.create_app())) as client:
        # Memory the conversation gathered before the account claimed it...
        assert await _drive(client, "/chat", {"message": "ANON-PRECLAIM-55", "session_id": sid}) == 200
        account = await _session(server, subject)
        # ...and the account's own turn in it.
        assert await _drive(client, "/chat", {"message": "ACCT-SECRET-66", "session_id": sid}, account) == 200
        assert memory.conversation_owner(sid) == subject

        _store_fails_once_on(memory, "DELETE FROM agent_turns", occurrence)
        resp = await client.delete("/api/v1/auth/account", headers=account)
        assert resp.status == 503, (resp.status, await resp.text())
        # A deletion that failed erased NOTHING: the retry has it all to do.
        for text in ("ACCT-SECRET-66", "ANON-PRECLAIM-55"):
            conv, agent = _rows_with(memory, text)
            assert conv and agent, f"a failed deletion half-erased {text!r}: conversation={conv} memory={agent}"
        assert memory.conversation_claim(sid).owner == subject, "a failed deletion erased the claim"
        assert server.wallet_sessions.get(f"tok-{subject}"), "a failed deletion removed the session"

        resp = await client.delete("/api/v1/auth/account", headers=account)
        assert resp.status == 200, await resp.text()
        for text in ("ACCT-SECRET-66", "ANON-PRECLAIM-55"):
            assert _rows_with(memory, text) == ([], []), f"the retry left {text!r} stored"
        assert memory.conversation_claim(sid).owner == ""
        assert not server.wallet_sessions.get(f"tok-{subject}")
        # Not in the gateway's working set either, and not in what the next
        # caller naming the id is shown or writes back.
        assert sid not in server.conversations, f"the retry left the gateway's copy: {server.conversations.get(sid)}"
        router.shown.clear()
        assert await _drive(client, "/chat", {"message": "anyone there?", "session_id": sid}) == 200
        assert len(router.shown) == 1, router.shown
        for text in ("ACCT-SECRET-66", "ANON-PRECLAIM-55"):
            assert text not in router.shown[0], f"the next caller naming the id was shown {text!r}"
            assert _rows_with(memory, text) == ([], []), f"{text!r} was written back by the next turn"


async def test_a_deletion_that_raised_after_its_erasure_committed_leaves_the_gateway_no_copy():
    """The other end of the same class: the erasure went through and something
    after it raised. The client is told the deletion failed and retries, and
    that retry finds no conversation of the account left to name — so the
    gateway's own copies must already be gone. They are dropped from ids read
    BEFORE the erasure, on the failure path too, not from what it returned."""
    server = _server()
    router = _HeldRouter("never-held")
    server.react_loop.router.complete = router.complete
    memory = server.react_loop.memory
    subject = "apple:postcommit"
    sid = "pc-conv"
    real_erase_owner = memory.erase_owner

    async def erase_then_raise(owner):
        await real_erase_owner(owner)
        raise RuntimeError("the store went away after the erasure committed")

    async with TestClient(TestServer(server.create_app())) as client:
        assert await _drive(client, "/chat", {"message": "ANON-PRECLAIM-77", "session_id": sid}) == 200
        account = await _session(server, subject)
        assert await _drive(client, "/chat", {"message": "ACCT-SECRET-88", "session_id": sid}, account) == 200

        memory.erase_owner = erase_then_raise
        resp = await client.delete("/api/v1/auth/account", headers=account)
        assert resp.status == 503, (resp.status, await resp.text())

        memory.erase_owner = real_erase_owner
        resp = await client.delete("/api/v1/auth/account", headers=account)
        assert resp.status == 200, await resp.text()
        assert sid not in server.conversations, f"the retry left the gateway's copy: {server.conversations.get(sid)}"
        router.shown.clear()
        assert await _drive(client, "/chat", {"message": "anyone there?", "session_id": sid}) == 200
        assert len(router.shown) == 1, router.shown
        for text in ("ACCT-SECRET-88", "ANON-PRECLAIM-77"):
            assert text not in router.shown[0], f"the next caller naming the id was shown {text!r}"
            assert _rows_with(memory, text) == ([], []), f"{text!r} was written back by the next turn"


# ── A deletion with no live session deleted nothing and said it had ──────────
#
# With an expired (or absent) session the handler had no subject, erased
# nothing, removed no device — and answered 200 {"success": true}, which the
# client shows the user as "your account was deleted". There is nothing here to
# delete without a session: it answers 401, so the client re-authenticates and
# sends the deletion again.

async def test_a_deletion_with_no_live_session_is_not_answered_as_a_success():
    server = _server()
    server.react_loop.router.complete = _HeldRouter("never-held").complete
    memory = server.react_loop.memory
    subject = "apple:expired"
    async with TestClient(TestServer(server.create_app())) as client:
        account = await _session(server, subject)
        assert await _drive(client, "/chat", {"message": "EXPIRED-SECRET", "session_id": "ex-conv"}, account) == 200
        now = time.time()
        await server.wallet_sessions.add(token="expired-tok", address=subject,
                                         issued_at=now - 7200, expires_at=now - 1)

        for headers in ({"Authorization": "Bearer expired-tok"},
                        {"X-Wallet-Session": "never-issued"},
                        {}):
            resp = await client.delete("/api/v1/auth/account", headers=headers)
            body = await resp.json()
            assert resp.status == 401, (headers, resp.status, body)
            assert body.get("success") is not True, (headers, body)
        assert _rows_with(memory, "EXPIRED-SECRET") != ([], []), "nothing was deleted, as the 401 says"
