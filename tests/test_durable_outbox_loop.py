"""Durable execution (engines Phase 2): the outbox and its one loop.

The loop replaces two unowned deliveries — the attestation batch timer nothing
ever started, and the fire-and-forget feed publish — and it must be safer than
either, not merely durable:

* AT MOST ONCE. An attestation whose delivery answered ambiguously, or whose
  delivery was interrupted, is HELD and never sent again by the loop; it is
  tried again only when the answer proves no attestation exists (nothing was
  sent, or the chain mined a revert — sent, and paid for by the platform), five
  attempts in all — the first and four retries — then it is a dead letter. A
  feed entry is delivered again after an interruption because the feed stores
  it once under the run's id.
* NO AUTHORITY. The loop delivers exactly two kinds to exactly two clients, and
  only for a run the journal says COMPLETED with a settled answer. A hostile
  row — no run, a run that did not complete, an answer that was not settled, a
  payload that is not the one recorded, a kind nothing delivers — is held and
  delivered to nobody, and nothing in runtime/durable can reach a service, the
  dispatcher, a tool or a gate.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "tests")

from durable_harness import (  # noqa: E402
    SETTLED, WALLET, Clock, FakeEAS, FeedSpy, World, database, engine, feed_rows,
    stub_dispatcher,
)
from runtime.durable import journal, outbox, wiring  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ACTION = "transfer_stablecoin"


@pytest.fixture
def installed():
    holder = {}

    def _install(eng):
        holder["previous"] = wiring.install(eng)
        return eng
    yield _install
    wiring.install(holder.get("previous"))


def _rows(db):
    return [dict(r) for r in db.fetchall_sync("SELECT * FROM outbox ORDER BY id")]


async def _one_settled_run(tmp_path, monkeypatch, installed, *, eas_answer=None, feed=True,
                           clock=None):
    world = World()
    db = database(tmp_path / "a.db")
    spy = FeedSpy(db, world) if feed else None
    eas = FakeEAS(world, eas_answer) if eas_answer is not None else FakeEAS(world)
    eng = installed(engine(db, world=world, eas=eas, feed=spy, clock=clock,
                           monkeypatch=monkeypatch))
    d = stub_dispatcher(world, SETTLED, feed=spy)
    await d.execute(ACTION, params={"to": WALLET}, caller_identity=WALLET)
    return world, db, eng, spy


# ── what an attestation client's answer establishes ─────────────────────────

@pytest.mark.parametrize("answer,outcome", [
    ({"status": "attested", "attestation_tx": "0x1"}, "done"),
    ({"status": "pending", "settled": False, "broadcast": True, "tx_hash": "0x2"}, "done"),
    ({"status": "skipped", "reason": "blockchain not configured"}, "retry"),
    ({"status": "failed", "attestation_tx": "0x3", "block_number": 7}, "retry"),
    ({"status": "failed", "error": "connection reset"}, "held"),
    ({"status": "unknown", "returned": "None"}, "held"),
    # No status at all reads as a success, as it does everywhere report_of
    # reads an answer (and as the batch processor's own flush reads it); either
    # way it is not sent again.
    ({"weird": True}, "done"),
    (None, "held"),
    ("attested", "held"),
])
def test_what_an_attestation_answer_allows(answer, outcome):
    assert outbox.classify_attestation(answer).outcome == outcome


# ── retries, dead letters, held rows ────────────────────────────────────────

async def test_an_attestation_never_sent_is_tried_five_times_in_all_then_dead(
        tmp_path, monkeypatch, installed, caplog):
    clock = Clock()
    world, db, eng, _ = await _one_settled_run(
        tmp_path, monkeypatch, installed, clock=clock, feed=False,
        eas_answer={"status": "skipped", "reason": "blockchain not configured"})
    waits = []
    with caplog.at_level(logging.ERROR, logger="runtime.durable.outbox"):
        for attempt in range(1, outbox.MAX_ATTEMPTS + 1):
            assert await eng.loop.tick() == 1
            (row,) = _rows(db)
            assert row["attempts"] == attempt
            if attempt < outbox.MAX_ATTEMPTS:
                assert row["state"] == outbox.PENDING
                waits.append(row["next_at"] - clock.now)
                assert await eng.loop.tick() == 0, "not before its backoff"
                clock.advance(row["next_at"] - clock.now + 0.001)
    (row,) = _rows(db)
    assert row["state"] == outbox.DEAD and row["payload"] == "" and row["payload_digest"]
    assert [int(w) for w in waits] == [30, 60, 120, 240]
    assert world.count("attest") == outbox.MAX_ATTEMPTS, "each attempt proved nothing was sent"
    assert sum("DEAD LETTER" in r.getMessage() for r in caplog.records) == 1
    clock.advance(10_000)
    assert await eng.loop.tick() == 0


@pytest.mark.parametrize("answer", [
    {"status": "failed", "error": "connection reset"},
    {"status": "pending", "settled": False, "broadcast": True, "tx_hash": "0x9"},
])
async def test_an_attestation_that_may_have_gone_out_is_never_sent_again(answer, tmp_path,
                                                                         monkeypatch, installed):
    clock = Clock()
    world, db, eng, _ = await _one_settled_run(tmp_path, monkeypatch, installed, clock=clock,
                                               feed=False, eas_answer=answer)
    await eng.loop.tick()
    for _ in range(5):
        clock.advance(outbox.RETRY_CAP_S + outbox.LEASE_S + 1)
        await eng.loop.tick()
    assert world.count("attest") == 1
    (row,) = _rows(db)
    assert row["state"] in (outbox.HELD, outbox.DONE)


async def test_a_raising_delivery_holds_an_attestation_and_retries_a_feed_entry(tmp_path, monkeypatch,
                                                                                 installed):
    clock = Clock()
    world, db, eng, spy = await _one_settled_run(tmp_path, monkeypatch, installed, clock=clock)

    async def attest_raises(_payload, _row):
        raise ConnectionError("rpc")
    eng.loop._deliverers["attest"] = attest_raises
    spy.before_insert = lambda: (_ for _ in ()).throw(RuntimeError("disk"))
    await eng.loop.tick()
    by_kind = {r["kind"]: r for r in _rows(db)}
    assert by_kind["attest"]["state"] == outbox.HELD
    assert by_kind["feed"]["state"] == outbox.PENDING
    spy.before_insert = None
    clock.advance(outbox.RETRY_BASE_S + 2)
    await eng.loop.tick()
    assert {r["kind"]: r["state"] for r in _rows(db)} == {"attest": outbox.HELD, "feed": outbox.DONE}
    assert len(feed_rows(db)) == 1


# ── interrupted deliveries (a process that died mid-delivery) ───────────────

async def test_an_interrupted_attestation_is_held_and_an_interrupted_feed_entry_lands_once(
        tmp_path, monkeypatch, installed):
    clock = Clock()
    world, db, eng, spy = await _one_settled_run(tmp_path, monkeypatch, installed, clock=clock)
    # Claim both rows, as a delivery would, and "die" before either answers.
    for row in _rows(db):
        assert eng.loop._claim(row["id"]) is not None
    # The feed entry did land before the death.
    run_id = _rows(db)[0]["run_id"]
    await spy.ingest(event_id=outbox.feed_event_id(run_id), **json.loads(
        [r for r in _rows(db) if r["kind"] == "feed"][0]["payload"]))
    assert {r["state"] for r in _rows(db)} == {outbox.ATTEMPTING}
    await eng.loop.tick()
    assert {r["state"] for r in _rows(db)} == {outbox.ATTEMPTING}, "inside the lease"
    clock.advance(outbox.LEASE_S + 1)
    await eng.loop.tick()
    by_kind = {r["kind"]: r for r in _rows(db)}
    assert by_kind["attest"]["state"] == outbox.HELD
    assert "not sent again" in by_kind["attest"]["last_error"]
    assert by_kind["feed"]["state"] == outbox.DONE
    assert len(feed_rows(db)) == 1, "delivered again, stored once"
    assert world.count("attest") == 0


# ── hostile rows ────────────────────────────────────────────────────────────

def _insert(db, run_id, kind, payload, *, digest=None, state="pending"):
    text = outbox.payload_text(payload)
    db.execute_sync(
        "INSERT INTO outbox (run_id, kind, payload, payload_digest, state, attempts, next_at, "
        "created_at) VALUES (?, ?, ?, ?, ?, 0, 0, 0)",
        (run_id, kind, text, digest or outbox.text_digest(text), state))


def _run(db, run_id, state, answer="settled", action=ACTION):
    def work(conn):
        journal.insert_run(conn, run_id=run_id, action=action, service="stablecoin",
                           actor_hash="", params_digest="p", state=journal.RUNNING, started_at=0)
        journal.append_step(conn, run_id, journal.STEP_RETURN, answer, at=0)
        if state != journal.RUNNING:
            journal.transition(conn, run_id, journal.RUNNING, state, at=0)
    db.transaction_sync(work)


async def test_a_hostile_row_is_held_and_delivered_to_nobody(tmp_path, monkeypatch, installed):
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
    world = World()
    db = database(tmp_path / "a.db")
    spy = FeedSpy(db, world)
    eng = installed(engine(db, world=world, feed=spy, monkeypatch=monkeypatch))

    async def never(*a, **k):
        raise AssertionError("the loop reached the dispatcher")
    monkeypatch.setattr(ServiceDispatcher, "execute", never)
    attest = {"schema_uid": "", "data": {"action": ACTION}, "recipient": "0x0"}
    feed = {"action": ACTION, "actor": "", "detail": {}}
    _run(db, "run_ok", journal.COMPLETE)
    _run(db, "run_refused", journal.FAIL, answer="refused")
    _run(db, "run_broadcast", journal.COMPLETE, answer="broadcast")
    _run(db, "run_open", journal.RUNNING)
    cases = [
        ("run_missing", "attest", attest, None),
        ("run_refused", "attest", attest, None),
        ("run_broadcast", "feed", feed, None),
        ("run_open", "attest", attest, None),
        ("run_ok", "notify", {"to": "everyone"}, None),
        ("run_ok", "attest", attest, "0" * 64),
        ("run_ok", "feed", {**feed, "action": "mint_nft"}, None),
    ]
    for run_id, kind, payload, digest in cases:
        _insert(db, run_id, kind, payload, digest=digest)
    with pytest.raises(Exception):
        # The outbox refuses a kind the table does not know at all.
        _insert(db, "run_ok", "execute", {"action": ACTION})
    assert await eng.loop.tick() == 0
    assert {r["state"] for r in _rows(db)} == {outbox.HELD}
    assert all(r["last_error"] for r in _rows(db))
    assert world.effects == [] and feed_rows(db) == [] and spy.calls == 0


def test_a_row_is_written_once_per_run_and_kind(tmp_path):
    import sqlite3
    db = database(tmp_path / "a.db")
    _insert(db, "run_x", "attest", {"a": 1})
    with pytest.raises(sqlite3.IntegrityError):
        _insert(db, "run_x", "attest", {"a": 2})


# ── the loop itself ─────────────────────────────────────────────────────────

async def test_a_dispatch_wakes_the_running_loop(tmp_path, monkeypatch, installed):
    world = World()
    db = database(tmp_path / "a.db")
    spy = FeedSpy(db, world)
    eng = installed(engine(db, world=world, feed=spy, monkeypatch=monkeypatch))
    eng.loop.tick_s = 3600
    eng.start()
    try:
        await asyncio.sleep(0.05)
        await stub_dispatcher(world, SETTLED, feed=spy).execute(ACTION, params={"to": WALLET})
        for _ in range(100):
            if len(feed_rows(db)) == 1 and world.count("attest") == 1:
                break
            await asyncio.sleep(0.01)
    finally:
        await eng.stop()
    assert len(feed_rows(db)) == 1 and world.count("attest") == 1
    assert not eng.loop.alive


@pytest.mark.parametrize("grace,landed", [(5.0, True), (0.05, False)])
async def test_a_stopping_loop_lets_the_delivery_in_hand_finish_within_its_grace(
        grace, landed, tmp_path, monkeypatch, installed):
    """A restart should not turn every attestation in flight into a held row:
    the one in hand gets its grace. One cut off by the grace is left
    `attempting` — never marked done, never sent twice."""
    world = World()
    db = database(tmp_path / "a.db")
    started = asyncio.Event()

    async def slow(_kwargs):
        started.set()
        await asyncio.sleep(0.3)
    eng = installed(engine(db, world=world, eas=FakeEAS(world, on_call=slow),
                           monkeypatch=monkeypatch))
    eng.loop.tick_s = 3600
    eng.start()
    await stub_dispatcher(world, SETTLED).execute(ACTION, params={"to": WALLET})
    await asyncio.wait_for(started.wait(), 5)
    await eng.loop.stop(grace_s=grace)
    (row,) = _rows(db)
    assert not eng.loop.alive
    if landed:
        assert row["state"] == outbox.DONE and world.count("attest") == 1
    else:
        assert row["state"] == outbox.ATTEMPTING and world.count("attest") == 0


async def test_a_tick_that_fails_does_not_stop_the_loop(tmp_path, installed):
    db = database(tmp_path / "a.db")
    eng = installed(wiring.DurableEngine(db, mode="on", tick_s=0.01))
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("once")
    eng.loop._maintain = flaky
    eng.start()
    try:
        for _ in range(100):
            if calls["n"] >= 3:
                break
            await asyncio.sleep(0.01)
        assert eng.loop.alive and calls["n"] >= 3
    finally:
        await eng.stop()


async def test_a_shadow_loop_maintains_and_delivers_nothing(tmp_path, monkeypatch, installed):
    world = World()
    db = database(tmp_path / "a.db")
    spy = FeedSpy(db, world)
    eng = installed(engine(db, mode="shadow", world=world, feed=spy, monkeypatch=monkeypatch))
    assert eng.loop.deliver is False
    _run(db, "run_ok", journal.COMPLETE)
    _insert(db, "run_ok", "attest", {"schema_uid": "", "data": {"action": ACTION}, "recipient": ""})
    await eng.loop.tick()
    assert _rows(db)[0]["state"] == outbox.PENDING and world.effects == []


# ── what runtime/durable can reach ──────────────────────────────────────────

#: Every module runtime/durable may import, and nothing else. None of them
#: dispatches an action, runs a tool, calls a service or decides on one.
_ALLOWED_IMPORTS = {
    "__future__", "asyncio", "contextlib", "contextvars", "dataclasses", "hashlib", "json",
    "logging", "os", "re", "sqlite3", "time", "typing", "uuid",
    "runtime.durable", "runtime.durable.journal", "runtime.durable.keys",
    "runtime.durable.outbox", "runtime.durable.wiring",
    # the twin table, read to know which tool calls sign
    "runtime.security.action_map",
    # the platform's reading of an answer's own verdict, never a new one
    "runtime.protocols.outcome_truth",
    # the batch processor's submission path: the outbox's attestation client
    "runtime.blockchain.services.attestation.batch_processor",
}

#: Names no module in runtime/durable may call: the ways into a service, the
#: dispatcher, a tool, a gate or the security core.
_FORBIDDEN_CALLS = {"execute", "dispatch", "gate_action", "evaluate", "pre_action",
                    "handle", "method", "get_morpheus_security", "attest_now"}


def test_runtime_durable_imports_nothing_that_can_act():
    for path in sorted((ROOT / "runtime" / "durable").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name in _ALLOWED_IMPORTS, f"{path.name} imports {name}"
            if isinstance(node, ast.ImportFrom) and node.module == "runtime.security.action_map":
                # The classification, and the declared-verb table (data) that
                # names a twin run without writing the model's own verb out.
                assert {a.name for a in node.names} <= {"TWIN_TOOLS", "SIGNING_ACTIONS",
                                                        "canonical_action"}
            if isinstance(node, ast.ImportFrom) and node.module == "runtime.protocols.outcome_truth":
                assert {a.name for a in node.names} <= {"FAILURE", "SUCCESS", "report_of"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name == "execute":
                    # A statement on a database connection, and nothing else.
                    receiver = fn.value if isinstance(fn, ast.Attribute) else None
                    assert isinstance(receiver, ast.Name) and receiver.id in ("conn", "source"), (
                        f"{path.name} calls execute on something that is not a connection")
                    continue
                assert name not in _FORBIDDEN_CALLS, f"{path.name} calls {name}"


def test_the_loop_delivers_two_kinds_to_two_clients_and_only_submit_now_signs():
    """The attestation client the loop is given is the batch processor's
    submission path, and nothing else calls it."""
    callers = set()
    for top in ("runtime", "gateway"):
        for path in (ROOT / top).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "submit_now"):
                    callers.add(str(path.relative_to(ROOT)))
    assert callers == {"runtime/durable/outbox.py"}
    source = (ROOT / "runtime" / "durable" / "wiring.py").read_text(encoding="utf-8")
    assert '"attest": outbox.attestation_deliverer(' in source
    assert 'deliverers["feed"] = outbox.feed_deliverer(' in source
