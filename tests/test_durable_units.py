"""The durable engine's parts, one at a time: the schema, the journal, the keys,
the outbox and its one loop (engines Phase 2, runtime/durable).

The end-to-end tests drive a dispatch through all of these at once; a defect in
one part can hide behind another there. These pin each part's own contract,
measured against the real code over a real platform ``Database``:

  * migration 11 creates exactly the four tables the spec names, with exactly
    its columns and the CHECK on a run's state, and applying it again — to a
    fresh database, to one reopened, to one whose version row was lost —
    changes nothing it already holds; the tables of earlier migrations are left
    exactly as they were;
  * after dispatches in shadow and in on whose caller, parameters, client key
    and answer carry distinctive values, not one cell of the four tables holds
    any of them — digests and fixed words only;
  * ``journal.move`` is a compare-and-set and refuses every transition outside
    ``TRANSITIONS``; ``journal.recover`` closes START → ABORT and RUNNING →
    FAIL (``unknown_effect``) only for runs older than the window that no live
    engine holds, and a second pass changes nothing;
  * ``keys.scoped`` keeps surface, scope and key apart (no two triples collide
    by concatenation), ``valid_client_key`` holds its bounds, ``AnswerCache``
    forgets by age and pushes out the oldest answer first;
  * the outbox loop delivers a held row once; retries on the backoff
    ``outbox.backoff_s`` computes up to ``MAX_ATTEMPTS`` and then gives up; gives
    up at once, without retrying, a delivery that raised; gives up a row it
    does not hold only after the row has been due for ``abandoned_after_s``;
    gives up at once, and never delivers, a row whose digest, run or kind does
    not match what it holds or whose run is not COMPLETE; starts, stops, wakes
    and reports its health; and ``outbox.counts`` says where rows stand.

Why: every guarantee the engine makes — nothing acts twice, nothing raw is
written, every run ends — is the sum of these parts' contracts. Each is small
enough to hold exactly, so each is held here.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import sqlite3
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, "tests")

from runtime.db import database as database_module  # noqa: E402
from runtime.durable import journal, keys, outbox, wiring  # noqa: E402
from runtime.durable.outbox import Delivery, Held, OutboxLoop  # noqa: E402
from test_durable_harness import (  # noqa: E402
    REFUSED, SETTLED, STATE_MODIFYING, Boom, Clock, Effects, bridge_like,
    dispatcher, drain, engine, installed, open_db, rows,
)

TABLES = ("workflow_runs", "workflow_steps", "outbox", "idempotency_keys")

SPEC_COLUMNS = {
    "workflow_runs": ["run_id", "key", "action", "service", "actor_hash", "params_digest",
                      "state", "decision_ref", "started_at", "terminal_at"],
    "workflow_steps": ["run_id", "seq", "name", "state", "detail", "at"],
    "outbox": ["id", "run_id", "kind", "payload_digest", "attempts", "next_at", "done_at"],
    "idempotency_keys": ["key", "run_id", "response_digest", "created_at"],
}
SPEC_PRIMARY_KEYS = {"workflow_runs": ["run_id"], "outbox": ["id"], "idempotency_keys": ["key"]}


#: The durable tables' migration: numbered after the one-spelling rewrite of
#: stored callers, which is 10.
DURABLE_VERSION = 11


def _v11_statements() -> list[str]:
    return [stmts for version, _d, stmts in database_module.MIGRATIONS
            if version == DURABLE_VERSION][0]


def _schema(db) -> dict[str, str]:
    return {r["name"]: r["sql"] for r in db.fetchall_sync(
        "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name")}


# ── migration 11 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", TABLES)
def test_each_v11_table_has_exactly_the_spec_columns(tmp_path, table):
    db = open_db(tmp_path / "a.db")
    info = db.fetchall_sync(f"PRAGMA table_info({table})")
    names = [r["name"] for r in info]
    assert names == SPEC_COLUMNS[table], (
        f"{table} has columns {names}; the spec names exactly {SPEC_COLUMNS[table]}")
    if table in SPEC_PRIMARY_KEYS:
        pk = [r["name"] for r in sorted(info, key=lambda r: r["pk"]) if r["pk"]]
        assert pk == SPEC_PRIMARY_KEYS[table], f"{table}'s primary key is {pk}"


def test_a_run_state_outside_the_five_is_refused_by_the_table_itself(tmp_path):
    db = open_db(tmp_path / "a.db")
    for i, state in enumerate(journal.STATES):
        db.execute_sync("INSERT INTO workflow_runs (run_id, action, params_digest, state, "
                        "started_at) VALUES (?, 'a', 'd', ?, 1)", (f"ok{i}", state))
    for bad in ("DONE", "complete", "", "START "):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute_sync("INSERT INTO workflow_runs (run_id, action, params_digest, state, "
                            "started_at) VALUES ('bad', 'a', 'd', ?, 1)", (bad,))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute_sync("UPDATE workflow_runs SET state = ? WHERE run_id = 'ok0'", (bad,))
    assert [r["state"] for r in rows(db, "workflow_runs")] == list(journal.STATES), (
        "a refused state reached the table")


def test_migration_11_is_additive_and_idempotent(tmp_path, monkeypatch):
    path = tmp_path / "a.db"
    # A database at the version before this migration, as main leaves it.
    earlier = [m for m in database_module.MIGRATIONS if m[0] < DURABLE_VERSION]
    monkeypatch.setattr(database_module, "MIGRATIONS", earlier)
    before = open_db(path)
    at_before = _schema(before)
    assert before.schema_version == max(m[0] for m in earlier)
    assert not set(TABLES) & set(at_before), "a v11 table existed before migration 11 ran"
    monkeypatch.undo()

    db = open_db(path)
    upgraded = _schema(db)
    assert db.schema_version == DURABLE_VERSION
    assert {k: v for k, v in upgraded.items() if k in at_before} == at_before, (
        "migration 11 changed an object an earlier migration created")
    assert set(TABLES) <= set(upgraded)

    db.execute_sync("INSERT INTO idempotency_keys (key, run_id, response_digest, created_at) "
                    "VALUES ('k', 'r', 'x', 1)")
    db.execute_sync("INSERT INTO workflow_runs (run_id, action, params_digest, state, "
                    "started_at) VALUES ('r', 'a', 'd', 'COMPLETE', 1)")

    # Reopened: nothing re-applied.
    again = open_db(path)
    assert again.fetchall_sync("SELECT COUNT(*) FROM schema_version WHERE version = ?",
                               (DURABLE_VERSION,))[0][0] == 1
    assert _schema(again) == upgraded

    # Its statements run again by hand, and its version row lost and re-applied.
    for stmt in _v11_statements():
        again.execute_sync(stmt)
    again.execute_sync("DELETE FROM schema_version WHERE version = ?", (DURABLE_VERSION,))
    third = open_db(path)
    assert third.schema_version == DURABLE_VERSION
    assert _schema(third) == upgraded, "re-applying migration 11 changed the schema"
    assert [r["key"] for r in rows(third, "idempotency_keys")] == ["k"], "a re-run lost a row"
    assert [r["run_id"] for r in rows(third, "workflow_runs")] == ["r"], "a re-run lost a row"


def test_a_fresh_database_has_the_four_tables_empty(tmp_path):
    db = open_db(tmp_path / "a.db")
    assert db.schema_version >= DURABLE_VERSION
    for table in TABLES:
        assert rows(db, table) == [], f"a fresh database has rows in {table}"


# ── nothing raw reaches the tables ─────────────────────────────────────────

ADDRESS = "0x5A0b54D5dc17e0AadC383d2db43B0a0D3E029c4c"
CALLER = "0x9f3Cd81B7a2E4c05D6e1F8a93b7C2d4E5f6A1b0C"
CLAIMED = "0x7E1d02c3B4a5968776F5e4D3c2B1a0918273645f"
CLIENT_KEY = "order-QX7-client-key-zulu"
PARAM_VALUES = ("memo-sentinel-hotel-4417", "913.77731", "marker-sentinel-kilo")
ANSWER_SENTINEL = "answer-sentinel-yankee-2291"
RAISE_SENTINEL = "raise-sentinel-victor-5530"
OVERRIDE_SENTINEL = "service-override-sentinel-lima"
DECISION = {"evaluation_id": "eval_0001"}


def _needles() -> list[str]:
    out = [CLIENT_KEY, ANSWER_SENTINEL, RAISE_SENTINEL, OVERRIDE_SENTINEL, *PARAM_VALUES]
    for address in (ADDRESS, CALLER, CLAIMED):
        out += [address, address[2:]]
    return [n.lower() for n in out]


def _scan(db, needles: list[str]) -> list[str]:
    found = []
    for table in TABLES:
        for row in rows(db, table):
            for column, cell in row.items():
                text = str(cell).lower()
                for needle in needles:
                    if needle in text:
                        found.append(f"{table}.{column} holds {needle!r}")
    return found


@pytest.mark.parametrize("mode", ["shadow", "on"])
async def test_no_table_holds_a_raw_address_param_key_or_answer(tmp_path, mode):
    clock = Clock()
    effects = Effects()
    db = open_db(tmp_path / "a.db")
    eng = engine(db, mode, clock, effects)
    d = dispatcher(effects)
    settled, refused, raising, overridden = STATE_MODIFYING[:4]
    d._services.answers[settled] = {**SETTLED, "note": ANSWER_SENTINEL}
    d._services.answers[refused] = {**REFUSED, "note": ANSWER_SENTINEL}
    d._services.answers[raising] = Boom(RAISE_SENTINEL)
    params = {"to": ADDRESS, "wallet": CLAIMED, "amount": PARAM_VALUES[1],
              "memo": PARAM_VALUES[0], "marker": PARAM_VALUES[2]}
    answers: list[str] = []
    with installed(eng):
        for i, action in enumerate((settled, refused, raising)):
            answers.append(await bridge_like(d, action, dict(params), key=f"{CLIENT_KEY}-{i}",
                                             identity=CALLER, decision=DECISION))
        # the first request replayed under its key
        answers.append(await bridge_like(d, settled, dict(params), key=f"{CLIENT_KEY}-0",
                                         identity=CALLER, decision=DECISION))
        # a service the caller named, which does not serve the method (ABORT)
        answers.append(await d.execute(overridden, params=dict(params),
                                       caller_identity=CALLER, service=OVERRIDE_SENTINEL))
        # a twin tool's platform-key signing call

        async def signing_call():
            return {**SETTLED, "note": ANSWER_SENTINEL}
        await eng.run_tool("nft", {"action": "mint", "to": ADDRESS, "memo": PARAM_VALUES[0]},
                           CALLER, signing_call)
        await drain(eng)

    assert all(isinstance(a, str) for a in answers)
    assert ANSWER_SENTINEL in answers[0], "the stand-in's answer did not reach the envelope"
    assert RAISE_SENTINEL in answers[2], "the raise did not reach the envelope"
    runs = rows(db, "workflow_runs")
    assert len(runs) >= 5, f"only {len(runs)} runs were written; the scan would prove little"
    assert rows(db, "outbox"), "no outbox row was written; the scan would prove little"
    assert rows(db, "idempotency_keys"), "no key was written; the scan would prove little"
    if mode == "on":
        assert effects.count("attest_sent", settled) == 1 and effects.count("feed", settled) == 1

    found = _scan(db, _needles() + [a.lower() for a in answers])
    assert found == [], f"raw values reached the durable tables in {mode}: {found}"
    services = {r["action"]: r["service"] for r in runs}
    assert services[overridden].startswith("sha256:"), (
        f"the caller-named service was written as {services[overridden]!r}")


# ── the journal ────────────────────────────────────────────────────────────

def _run(db, run_id: str, state: str, *, started_at: float, key: str = "") -> None:
    journal.transaction(db, lambda tx: journal.insert_run(
        tx, run_id=run_id, action="a", service="s", actor_hash="", params_digest="d",
        state=state, started_at=started_at, key=key,
        terminal_at=started_at if state in journal.TERMINAL else None), wait=True)


def _state(db, run_id: str) -> str:
    return journal.get_run(db, run_id)["state"]


def test_move_is_a_compare_and_set(tmp_path):
    db = open_db(tmp_path / "a.db")
    _run(db, "r1", journal.RUNNING, started_at=1.0)
    lost = journal.transaction(db, lambda tx: journal.move(
        tx, "r1", journal.START, journal.ABORT, at=2.0), wait=True)
    assert lost is False and _state(db, "r1") == journal.RUNNING, (
        "a move from a state the run is not in changed it")
    won = journal.transaction(db, lambda tx: journal.move(
        tx, "r1", journal.RUNNING, journal.COMPLETE, at=3.0), wait=True)
    assert won is True
    run = journal.get_run(db, "r1")
    assert (run["state"], run["terminal_at"]) == (journal.COMPLETE, 3.0)
    again = journal.transaction(db, lambda tx: journal.move(
        tx, "r1", journal.RUNNING, journal.FAIL, at=4.0), wait=True)
    assert again is False and _state(db, "r1") == journal.COMPLETE, (
        "a second move from RUNNING rewrote a COMPLETE run")
    missing = journal.transaction(db, lambda tx: journal.move(
        tx, "nope", journal.START, journal.RUNNING, at=5.0), wait=True)
    assert missing is False


def test_move_refuses_every_transition_outside_transitions(tmp_path):
    db = open_db(tmp_path / "a.db")
    refused = [(a, b) for a, b in itertools.product(journal.STATES, repeat=2)
               if (a, b) not in journal.TRANSITIONS]
    assert len(refused) == 25 - 4
    for i, (a, b) in enumerate(refused):
        run_id = f"r{i}"
        _run(db, run_id, a, started_at=1.0)
        with pytest.raises(ValueError):
            journal.transaction(db, lambda tx: journal.move(tx, run_id, a, b, at=2.0), wait=True)
        assert _state(db, run_id) == a, f"a refused move {a} -> {b} changed the run"
    with pytest.raises(ValueError):
        journal.transaction(db, lambda tx: journal.insert_run(
            tx, run_id="x", action="a", service="s", actor_hash="", params_digest="d",
            state="DONE", started_at=1.0), wait=True)
    _run(db, "open", journal.RUNNING, started_at=1.0)
    assert journal.get_run(db, "open")["terminal_at"] is None, "an open run has a terminal_at"


def test_a_transaction_that_raises_writes_nothing_and_restores_the_busy_timeout(tmp_path):
    db = open_db(tmp_path / "a.db")
    before = db.fetchall_sync("PRAGMA busy_timeout")[0][0]

    def work(tx):
        journal.insert_run(tx, run_id="r", action="a", service="s", actor_hash="",
                           params_digest="d", state=journal.START, started_at=1.0)
        raise Boom("after the insert")
    with pytest.raises(Boom):
        journal.transaction(db, work, wait=False)
    assert rows(db, "workflow_runs") == [], "a raised transaction left its insert behind"
    assert db.fetchall_sync("PRAGMA busy_timeout")[0][0] == before


def test_recover_closes_only_old_unheld_open_runs_and_is_idempotent(tmp_path):
    db = open_db(tmp_path / "a.db")
    now = 10_000.0
    window = journal.ABANDONED_AFTER_S
    old = now - window - 1
    _run(db, "old_start", journal.START, started_at=old, key="k_start")
    _run(db, "old_running", journal.RUNNING, started_at=old, key="k_running")
    _run(db, "held_running", journal.RUNNING, started_at=old)
    _run(db, "young_start", journal.START, started_at=now - window + 1)
    _run(db, "edge_running", journal.RUNNING, started_at=now - window)
    _run(db, "old_complete", journal.COMPLETE, started_at=old)
    _run(db, "old_fail", journal.FAIL, started_at=old)
    journal.transaction(db, lambda tx: journal.step(tx, "old_running", 1, "start", "opened",
                                                    at=old), wait=True)

    found = journal.abandoned(db, now=now, held={"held_running"})
    assert sorted(r[0] for r in found) == ["old_running", "old_start"], (
        f"recovery would close {found}")
    closed = journal.transaction(db, lambda tx: journal.recover(tx, found, now=now), wait=True)
    assert closed == {"aborted": ["old_start"], "failed": ["old_running"]}
    assert _state(db, "old_start") == journal.ABORT
    assert _state(db, "old_running") == journal.FAIL
    for untouched, state in (("held_running", journal.RUNNING), ("young_start", journal.START),
                             ("edge_running", journal.RUNNING),
                             ("old_complete", journal.COMPLETE), ("old_fail", journal.FAIL)):
        assert _state(db, untouched) == state, f"recovery touched {untouched}"
    steps = {r: [(s["seq"], s["name"], s["state"]) for s in journal.get_steps(db, r)]
             for r in ("old_start", "old_running")}
    assert steps["old_start"] == [(1, journal.STEP_ABORT, "not_attempted")]
    assert steps["old_running"] == [(1, "start", "opened"),
                                    (2, journal.STEP_UNKNOWN, "no_answer_recorded")]
    assert journal.get_run(db, "old_running")["terminal_at"] == now

    # A second pass — the same list again, or a fresh read — changes nothing.
    snapshot = (rows(db, "workflow_runs"), rows(db, "workflow_steps"))
    again = journal.transaction(db, lambda tx: journal.recover(tx, found, now=now + 1),
                                wait=True)
    assert again == {"aborted": [], "failed": []}
    assert journal.abandoned(db, now=now, held=set()) == [
        ("held_running", journal.RUNNING, "")], "a closed run is still found open"
    assert (rows(db, "workflow_runs"), rows(db, "workflow_steps")) == snapshot, (
        "a second recovery pass changed the journal")


async def test_maintain_releases_an_aborted_runs_key_keeps_a_failed_ones_and_skips_held(
        tmp_path):
    clock = Clock()
    effects = Effects()
    db = open_db(tmp_path / "a.db")
    eng = engine(db, "on", clock, effects)
    old = clock.now - journal.ABANDONED_AFTER_S - 1
    _run(db, "gone_start", journal.START, started_at=old, key="k1")
    _run(db, "gone_running", journal.RUNNING, started_at=old, key="k2")
    for key, run_id in (("k1", "gone_start"), ("k2", "gone_running")):
        journal.transaction(db, lambda tx: keys.bind(tx, key=key, run_id=run_id, now=old),
                            wait=True)

    # A dispatch this engine holds open, older than the window by the time maintain runs.
    d = dispatcher(effects)
    action = STATE_MODIFYING[0]
    gate = d._services.gates[action] = asyncio.Event()
    with installed(eng):
        task = asyncio.ensure_future(bridge_like(d, action, {"marker": 1}, key="live"))
        for _ in range(20):
            await asyncio.sleep(0)
        held = [r["run_id"] for r in rows(db, "workflow_runs") if r["state"] == journal.RUNNING
                and r["run_id"] not in ("gone_running",)]
        assert len(held) == 1, "the live dispatch's run was not written RUNNING"
        clock.advance(journal.ABANDONED_AFTER_S + 10)
        closed = eng.maintain()
        assert closed == {"aborted": ["gone_start"], "failed": ["gone_running"]}
        assert _state(db, held[0]) == journal.RUNNING, "recovery closed a run this engine holds"
        assert keys.lookup(db, "k1") is None, "an ABORT run's key was not given back"
        assert keys.lookup(db, "k2") == ("gone_running", ""), "a FAIL run's key was released"
        assert eng.maintain() == {"aborted": [], "failed": []}, "a second pass closed more"
        gate.set()
        answer = await task
    assert json.loads(answer)["status"] == "ok"
    assert _state(db, held[0]) == journal.COMPLETE
    assert effects.count("service", action) == 1


# ── the keys ───────────────────────────────────────────────────────────────

def test_scoped_keeps_surface_scope_and_key_apart():
    triples = [("ab", "c", "d"), ("a", "bc", "d"), ("a", "b", "cd"), ("abc", "", "d"),
               ("", "abc", "d"), ("a|b", "c", "d"), ("a", "b|c", "d"), ("a", "b", "c|d"),
               ("bridge.action", "operator|0xab", "k"), ("bridge.action", "operator", "|0xabk"),
               ("bridge.action", "operator|0xab", "k "), ("bridge.action", "operator|0xAB", "k")]
    digests = [keys.scoped(*t) for t in triples]
    assert len(set(digests)) == len(triples), "two different triples share a stored key"
    for t, dg in zip(triples, digests):
        assert len(dg) == 64 and all(c in "0123456789abcdef" for c in dg)
        assert keys.scoped(*t) == dg, "scoped is not deterministic"
    assert CLIENT_KEY not in keys.scoped("bridge.action", "operator|x", CLIENT_KEY)


@pytest.mark.parametrize("value,ok", [
    ("a", True), ("x" * keys.MAX_CLIENT_KEY, True), ("a b", True), ("~!@#$%^&*()", True),
    ("x" * (keys.MAX_CLIENT_KEY + 1), False), ("", False), (" a", False), ("a ", False),
    ("a\tb", False), ("a\nb", False), ("café", False), ("a\x7f", False),
    ("a\x00", False), (None, False), (b"abc", False), (12, False),
])
def test_valid_client_key_bounds(value, ok):
    assert keys.valid_client_key(value) is ok, f"valid_client_key({value!r}) is not {ok}"


def test_bind_is_first_come_and_release_only_frees_its_own_run(tmp_path):
    db = open_db(tmp_path / "a.db")
    tx = lambda work: journal.transaction(db, work, wait=True)  # noqa: E731
    assert tx(lambda t: keys.bind(t, key="k", run_id="r1", now=1.0)) is True
    assert tx(lambda t: keys.bind(t, key="k", run_id="r2", now=2.0)) is False
    tx(lambda t: keys.answered(t, key="k", run_id="r2", response_digest="wrong"))
    assert keys.lookup(db, "k") == ("r1", ""), "another run wrote the key's answer digest"
    tx(lambda t: keys.answered(t, key="k", run_id="r1", response_digest="dg"))
    tx(lambda t: keys.release(t, key="k", run_id="r2"))
    assert keys.lookup(db, "k") == ("r1", "dg"), "another run released the key"
    tx(lambda t: keys.release(t, key="k", run_id="r1"))
    assert keys.lookup(db, "k") is None


def test_answer_cache_forgets_by_age():
    clock = Clock()
    cache = keys.AnswerCache(size=10, ttl_s=100.0, clock=clock)
    cache.put("k", "first")
    clock.advance(100.0)
    assert cache.get("k") == "first", "an answer was forgotten before its TTL"
    clock.advance(0.001)
    assert cache.get("k") is None, "an answer outlived its TTL"
    assert len(cache) == 0, "an expired answer is still held"
    assert keys.AnswerCache().get("missing") is None
    default = keys.AnswerCache(clock=clock)
    default.put("k", "v")
    clock.advance(keys.ANSWER_TTL_S + 1)
    assert default.get("k") is None, "the default TTL is not 24 h"


def test_answer_cache_pushes_out_the_oldest_answer_first():
    clock = Clock()
    cache = keys.AnswerCache(size=3, ttl_s=100.0, clock=clock)
    for k in "abc":
        cache.put(k, k.upper())
    cache.put("a", "A2")                 # a is now the newest
    cache.put("d", "D")                  # b is the oldest: pushed out
    assert len(cache) == 3
    assert cache.get("b") is None, "the oldest answer was not the one pushed out"
    assert [cache.get(k) for k in "acd"] == ["A2", "C", "D"]
    for i in range(10):
        cache.put(f"n{i}", "x")
    assert len(cache) == 3 and [cache.get(k) for k in "acd"] == [None, None, None]
    assert keys.AnswerCache()._size == keys.ANSWER_CACHE_SIZE == 4096


# ── the outbox and its loop ────────────────────────────────────────────────

class Deliverer:
    """A delivery closure that answers what the test chose, once per call."""

    def __init__(self, answer=None) -> None:
        self.calls = 0
        self.answer = answer if answer is not None else Delivery(outbox.DELIVERED, "landed")
        self.gate: asyncio.Event | None = None

    async def __call__(self):
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


def _outbox_row(db, run_id: str, kind: str, digest: str, now: float) -> int:
    return journal.transaction(db, lambda tx: outbox.insert(
        tx, run_id=run_id, kind=kind, payload_digest=digest, now=now, deliver=True), wait=True)


def _row(db, row_id: int) -> dict:
    return dict(db.fetchall_sync("SELECT * FROM outbox WHERE id = ?", (row_id,))[0])


def _outbox_steps(db, run_id: str) -> list[tuple[str, str, str]]:
    return [(s["name"], s["state"], s["detail"]) for s in journal.get_steps(db, run_id)
            if s["name"].startswith("outbox:")]


def _held_row(db, clock, *, kind="attest", deliverer=None, run_state=journal.COMPLETE,
              run_id="run_a"):
    _run(db, run_id, run_state, started_at=clock.now)
    row_id = _outbox_row(db, run_id, kind, "dg", clock.now)
    deliverer = deliverer or Deliverer()
    return row_id, deliverer, Held(run_id=run_id, kind=kind, payload_digest="dg",
                                   deliver=deliverer)


async def test_a_held_row_is_delivered_once(tmp_path):
    db = open_db(tmp_path / "a.db")
    clock = Clock()
    loop = OutboxLoop(db, deliver=True, clock=clock)
    row_id, deliverer, held = _held_row(db, clock)
    loop.hold(row_id, held)
    assert await loop.tick() == 1
    for _ in range(3):
        clock.advance(outbox.LEASE_S + 1)
        assert await loop.tick() == 0
    assert deliverer.calls == 1, f"a delivered row was delivered {deliverer.calls} times"
    row = _row(db, row_id)
    assert (row["attempts"], row["next_at"], row["done_at"]) == (1, None, clock.now - 3 * (
        outbox.LEASE_S + 1))
    assert _outbox_steps(db, "run_a") == [("outbox:attest", outbox.DELIVERED, "landed")]
    assert loop.held_count() == 0, "a delivered payload is still held"


def test_backoff_doubles_from_thirty_seconds_caps_at_an_hour_and_repeats():
    for attempts, base in ((1, 30.0), (2, 60.0), (3, 120.0), (4, 240.0), (8, 3600.0),
                           (40, 3600.0)):
        b = outbox.backoff_s(attempts, 7)
        assert base <= b < base + 1.0, f"backoff after {attempts} attempt(s) is {b}"
        assert outbox.backoff_s(attempts, 7) == b, "the backoff is drawn, not derived"
    assert outbox.backoff_s(0, 1) >= outbox.RETRY_BASE_S


async def test_a_retried_row_waits_its_backoff_and_is_given_up_after_max_attempts(tmp_path):
    db = open_db(tmp_path / "a.db")
    clock = Clock()
    loop = OutboxLoop(db, deliver=True, clock=clock)
    row_id, deliverer, held = _held_row(db, clock, deliverer=Deliverer(
        Delivery(outbox.RETRY, "not_landed")))
    loop.hold(row_id, held)
    for attempt in range(1, outbox.MAX_ATTEMPTS + 1):
        await loop.tick()
        assert deliverer.calls == attempt
        row = _row(db, row_id)
        assert row["attempts"] == attempt and row["done_at"] is None
        if attempt == outbox.MAX_ATTEMPTS:
            assert row["next_at"] is None, "a row past MAX_ATTEMPTS is still due"
            break
        assert row["next_at"] == pytest.approx(clock.now + outbox.backoff_s(attempt, row_id)), (
            f"after attempt {attempt} the row is due at {row['next_at'] - clock.now} s")
        clock.now = row["next_at"] - 0.001
        await loop.tick()
        assert deliverer.calls == attempt, "a row was retried before its backoff ran out"
        clock.now = row["next_at"]
    clock.advance(10 * outbox.RETRY_CAP_S)
    await loop.tick()
    assert deliverer.calls == outbox.MAX_ATTEMPTS == 5, "a given-up row was delivered again"
    assert _outbox_steps(db, "run_a") == (
        [("outbox:attest", outbox.RETRY, "not_landed")] * (outbox.MAX_ATTEMPTS - 1)
        + [("outbox:attest", outbox.GIVEN_UP, "not_landed")])
    assert loop.held_count() == 0
    assert outbox.counts(db) == {"due": 0, "handed_off": 0, "given_up": 1}


@pytest.mark.parametrize("answer,detail", [
    (Boom("the chain client raised"), "raised:Boom"),
    ("not a delivery", "no_answer"),
    (Delivery("maybe", "x"), "no_answer"),
    (Delivery(outbox.GIVEN_UP, "feed_reported_failure"), "feed_reported_failure"),
])
async def test_a_delivery_that_raised_or_answered_nothing_is_given_up_not_retried(
        tmp_path, answer, detail):
    db = open_db(tmp_path / "a.db")
    clock = Clock()
    loop = OutboxLoop(db, deliver=True, clock=clock)
    row_id, deliverer, held = _held_row(db, clock, kind="feed", deliverer=Deliverer(answer))
    loop.hold(row_id, held)
    await loop.tick()
    for _ in range(3):
        clock.advance(outbox.RETRY_CAP_S + outbox.LEASE_S)
        await loop.tick()
    assert deliverer.calls == 1, f"the delivery was tried {deliverer.calls} times"
    row = _row(db, row_id)
    assert (row["attempts"], row["next_at"], row["done_at"]) == (1, None, None)
    assert _outbox_steps(db, "run_a") == [("outbox:feed", outbox.GIVEN_UP, detail)]


async def test_a_row_not_held_is_given_up_only_after_it_was_due_for_the_window(tmp_path):
    db = open_db(tmp_path / "a.db")
    clock = Clock()
    window = 120.0
    loop = OutboxLoop(db, deliver=True, clock=clock, abandoned_after_s=window)
    _run(db, "run_a", journal.COMPLETE, started_at=clock.now)
    due_at = clock.now
    row_id = _outbox_row(db, "run_a", "attest", "dg", due_at)
    for at in (0.0, window / 2, window):
        clock.now = due_at + at
        assert await loop.tick() == 0
        row = _row(db, row_id)
        assert (row["attempts"], row["next_at"], row["done_at"]) == (0, due_at, None), (
            f"a row another process may hold was touched {at} s after it fell due")
    assert _outbox_steps(db, "run_a") == []
    clock.now = due_at + window + 0.001
    await loop.tick()
    row = _row(db, row_id)
    assert (row["attempts"], row["next_at"], row["done_at"]) == (0, None, None)
    assert _outbox_steps(db, "run_a") == [("outbox:attest", outbox.GIVEN_UP, "payload_not_held")]
    # The default window is the journal's.
    assert OutboxLoop(db, deliver=True)._abandoned_after_s == journal.ABANDONED_AFTER_S


@pytest.mark.parametrize("case", ["digest", "run", "kind", "run_running", "run_missing",
                                  "run_fail"])
async def test_a_row_that_does_not_match_its_payload_is_given_up_at_once(tmp_path, case):
    db = open_db(tmp_path / "a.db")
    clock = Clock()
    loop = OutboxLoop(db, deliver=True, clock=clock)
    run_state = {"run_running": journal.RUNNING, "run_fail": journal.FAIL}.get(
        case, journal.COMPLETE)
    if case == "run_missing":
        row_id = _outbox_row(db, "run_gone", "attest", "dg", clock.now)
        deliverer = Deliverer()
        held = Held(run_id="run_gone", kind="attest", payload_digest="dg", deliver=deliverer)
        run_id = "run_gone"
    else:
        row_id, deliverer, held = _held_row(db, clock, run_state=run_state)
        run_id = "run_a"
        if case == "digest":
            held = Held(run_id=run_id, kind="attest", payload_digest="other", deliver=deliverer)
        elif case == "run":
            _run(db, "run_b", journal.COMPLETE, started_at=clock.now)
            held = Held(run_id="run_b", kind="attest", payload_digest="dg", deliver=deliverer)
        elif case == "kind":
            held = Held(run_id=run_id, kind="feed", payload_digest="dg", deliver=deliverer)
    loop.hold(row_id, held)
    await loop.tick()
    clock.advance(journal.ABANDONED_AFTER_S + outbox.LEASE_S + 1)
    await loop.tick()
    assert deliverer.calls == 0, f"a row with a mismatched {case} was delivered"
    row = _row(db, row_id)
    assert (row["attempts"], row["next_at"], row["done_at"]) == (0, None, None), (
        f"a mismatched ({case}) row is {row}")
    why = "payload_mismatch" if case in ("digest", "run", "kind") else "run_not_complete"
    expected = [] if case == "run_missing" else [("outbox:attest", outbox.GIVEN_UP, why)]
    assert _outbox_steps(db, run_id) == expected
    assert loop.held_count() == 0, "a mismatched payload is still held"


async def test_two_loops_over_one_row_deliver_it_once(tmp_path):
    """The claim is a compare-and-set on ``next_at``: a loop that read a row
    before another claimed it skips it."""
    db = open_db(tmp_path / "a.db")
    clock = Clock()
    first, second = (OutboxLoop(db, deliver=True, clock=clock) for _ in range(2))
    _run(db, "run_a", journal.COMPLETE, started_at=clock.now)
    ids = [_outbox_row(db, "run_a", k, "dg", clock.now) for k in ("attest", "feed")]
    deliverers = {k: Deliverer() for k in ("attest", "feed")}
    for d in deliverers.values():
        d.gate = asyncio.Event()
    for loop in (first, second):
        for row_id, kind in zip(ids, ("attest", "feed")):
            loop.hold(row_id, Held(run_id="run_a", kind=kind, payload_digest="dg",
                                   deliver=deliverers[kind]))
    ticks = asyncio.gather(first.tick(), second.tick())
    for _ in range(10):
        await asyncio.sleep(0)
    for d in deliverers.values():
        d.gate.set()
    await ticks
    assert {k: d.calls for k, d in deliverers.items()} == {"attest": 1, "feed": 1}, (
        "a row was delivered by both loops")
    assert outbox.counts(db) == {"due": 0, "handed_off": 2, "given_up": 0}


async def test_a_tick_over_a_full_batch_of_unheld_rows_returns(tmp_path):
    """After a restart the rows a dead process wrote are due and held by no one
    for ``abandoned_after_s``. A tick must still return — and reach the rows
    this process does hold — however many of them there are."""
    db = open_db(tmp_path / "a.db")
    clock = Clock()
    reads = {"n": 0}

    def counting_clock():
        reads["n"] += 1
        if reads["n"] > 200:
            raise RuntimeError("the tick re-read the clock 200 times without returning")
        return clock.now

    loop = OutboxLoop(db, deliver=True, clock=counting_clock)
    for i in range(outbox.BATCH):
        _outbox_row(db, f"run_dead_{i}", "feed", "dg", clock.now - 1)
    row_id, deliverer, held = _held_row(db, clock)
    loop.hold(row_id, held)
    try:
        await loop.tick()
    except RuntimeError as exc:
        pytest.fail(f"with {outbox.BATCH} due rows this process does not hold, a tick "
                    f"re-selects the same batch forever without awaiting anything: {exc}")
    assert deliverer.calls == 1, "a held row behind a batch of unheld rows was never reached"


async def test_the_loop_starts_ticks_wakes_reports_health_and_stops(tmp_path):
    db = open_db(tmp_path / "a.db")
    clock = Clock()
    maintained = []
    loop = OutboxLoop(db, deliver=True, clock=clock, tick_s=3600.0,
                      maintain=lambda: maintained.append(clock.now))
    assert not loop.alive and not loop.healthy(), "a loop never started reports healthy"
    loop.wake()                                   # nothing to wake: no error

    async def settle():
        for _ in range(20):
            await asyncio.sleep(0)

    loop.start()
    task = loop._task
    await settle()
    assert loop.alive and loop.ticks == 1 and len(maintained) == 1
    assert loop.last_tick_at == clock.now
    loop.start()
    assert loop._task is task, "a second start began a second loop"

    row_id, deliverer, held = _held_row(db, clock)
    loop.hold(row_id, held)
    await settle()
    assert deliverer.calls == 0, "the loop ticked without being woken or its interval passing"
    loop.wake()
    await settle()
    assert loop.ticks == 2 and deliverer.calls == 1, "wake did not start a tick"

    # Health follows progress — a tick beginning or a delivery answering — so a
    # loop busy with slow deliveries stays healthy and a stuck one does not.
    assert loop.last_progress_at is not None and loop.last_progress_at >= loop.last_tick_at
    bound = outbox.DELIVERY_TIMEOUT_S + max(60.0, 12 * loop.tick_s)
    assert loop.healthy() and loop.healthy(now=loop.last_progress_at + bound)
    assert not loop.healthy(now=loop.last_progress_at + bound + 0.001), (
        "a loop that has made no progress for longer than its bound reports healthy")

    await loop.stop(grace_s=1.0)
    assert not loop.alive and not loop.healthy() and task.done()
    await loop.stop()                             # a second stop is a no-op
    loop.start()
    await settle()
    assert loop.alive and loop.ticks == 3, "the loop did not start again after a stop"
    await loop.stop(grace_s=1.0)
    assert not loop.alive


async def test_a_tick_that_raises_does_not_end_the_loop(tmp_path):
    db = open_db(tmp_path / "a.db")
    calls = []

    def maintain():
        calls.append(1)
        if len(calls) == 1:
            raise Boom("maintenance failed once")

    loop = OutboxLoop(db, deliver=True, clock=Clock(), tick_s=3600.0, maintain=maintain)
    loop.start()
    for _ in range(20):
        await asyncio.sleep(0)
    assert loop.alive, "a tick that raised ended the loop"
    loop.wake()
    for _ in range(20):
        await asyncio.sleep(0)
    assert len(calls) == 2 and loop.healthy()
    await loop.stop(grace_s=1.0)


async def test_stop_cancels_a_delivery_past_its_grace_and_gives_its_row_up(tmp_path):
    db = open_db(tmp_path / "a.db")
    clock = Clock()
    loop = OutboxLoop(db, deliver=True, clock=clock, tick_s=3600.0)
    row_id, deliverer, held = _held_row(db, clock)
    deliverer.gate = asyncio.Event()             # never set: the delivery hangs
    loop.hold(row_id, held)
    loop.start()
    for _ in range(20):
        await asyncio.sleep(0)
    assert deliverer.calls == 1
    await asyncio.wait_for(loop.stop(grace_s=0.01), timeout=5.0)
    assert not loop.alive
    row = _row(db, row_id)
    # Whether the cut-off delivery went out is not known, so it is never tried
    # again: given up at once, with the step that says why.
    assert (row["attempts"], row["next_at"], row["done_at"]) == (
        1, None, None), f"a row cancelled mid-delivery is {row}"
    assert loop.held_count() == 0
    assert await loop.tick() == 0, "a stopped loop began a delivery"


async def test_a_delivery_cancelled_by_stop_is_not_sent_again_by_a_restarted_loop(tmp_path):
    """A delivery cut off mid-flight may have gone out: like one that raised, it
    must never be retried blind."""
    db = open_db(tmp_path / "a.db")
    clock = Clock()
    effects = Effects()
    loop = OutboxLoop(db, deliver=True, clock=clock, tick_s=3600.0)
    hang = asyncio.Event()

    async def deliver():
        effects.log.append(("attest_sent", "a"))
        await hang.wait()
        return Delivery(outbox.DELIVERED, "landed")

    _run(db, "run_a", journal.COMPLETE, started_at=clock.now)
    row_id = _outbox_row(db, "run_a", "attest", "dg", clock.now)
    loop.hold(row_id, Held(run_id="run_a", kind="attest", payload_digest="dg", deliver=deliver))
    loop.start()
    for _ in range(20):
        await asyncio.sleep(0)
    await loop.stop(grace_s=0.01)
    hang.set()
    loop.start()
    clock.advance(outbox.LEASE_S + 1)
    loop.wake()
    for _ in range(20):
        await asyncio.sleep(0)
    await loop.stop(grace_s=1.0)
    assert effects.count("attest_sent") == 1, (
        "a delivery cancelled mid-flight was sent again once its lease ran out")


def test_insert_writes_a_due_row_or_a_handed_off_one_and_refuses_an_unknown_kind(tmp_path):
    db = open_db(tmp_path / "a.db")
    due = _outbox_row(db, "r", "attest", "dg", 5.0)
    shadow = journal.transaction(db, lambda tx: outbox.insert(
        tx, run_id="r", kind="feed", payload_digest="dg", now=6.0, deliver=False), wait=True)
    assert {k: _row(db, due)[k] for k in ("attempts", "next_at", "done_at")} == {
        "attempts": 0, "next_at": 5.0, "done_at": None}
    assert {k: _row(db, shadow)[k] for k in ("attempts", "next_at", "done_at")} == {
        "attempts": 0, "next_at": None, "done_at": 6.0}
    with pytest.raises(ValueError):
        journal.transaction(db, lambda tx: outbox.insert(
            tx, run_id="r", kind="email", payload_digest="dg", now=1.0, deliver=True), wait=True)
    assert len(rows(db, "outbox")) == 2


def test_counts_says_where_every_row_stands(tmp_path):
    db = open_db(tmp_path / "a.db")
    assert outbox.counts(db) == {"due": 0, "handed_off": 0, "given_up": 0}
    for i in range(3):
        _outbox_row(db, "r", "attest", "dg", float(i))
    handed = [journal.transaction(db, lambda tx: outbox.insert(
        tx, run_id="r", kind="feed", payload_digest="dg", now=9.0, deliver=False), wait=True)
        for _ in range(2)]
    db.execute_sync("UPDATE outbox SET next_at = NULL WHERE id = 1")
    db.execute_sync("UPDATE outbox SET next_at = 99.0, attempts = 2 WHERE id = 2")
    assert outbox.counts(db) == {"due": 2, "handed_off": 2, "given_up": 1}
    assert len(handed) == 2


def _legacy_attestation(d, effects) -> list:
    """The attestation service the legacy path queues on, counting what it is
    handed. (The harness's own ``registry.get("attestation")`` raises, because
    ``create_attestation`` maps to ``attestation.attest`` and collides with its
    stand-in ``attest``; the legacy call swallows that as a warning.)"""
    registry = d._get_registry()
    queued: list = []

    async def attest(**kwargs):
        queued.append(kwargs.get("data", {}).get("action"))
        return {"status": "queued"}

    d._get_registry = lambda: SimpleNamespace(
        get=lambda name: SimpleNamespace(attest=attest) if name == "attestation"
        else registry.get(name))
    return queued


async def test_an_engine_in_shadow_never_drains_what_it_records(tmp_path):
    """Shadow writes rows already handed off, and its loop only maintains."""
    clock = Clock()
    effects = Effects()
    db = open_db(tmp_path / "a.db")
    eng = engine(db, "shadow", clock, effects)
    d = dispatcher(effects)
    legacy_attest = _legacy_attestation(d, effects)
    action = STATE_MODIFYING[0]
    before = wiring.current()
    with installed(eng):
        await bridge_like(d, action, {"marker": 1}, key="k")
        await drain(eng)
    assert eng.loop.deliver is False
    assert outbox.counts(db)["due"] == 0 and outbox.counts(db)["handed_off"] == 2
    assert all(r["attempts"] == 0 and r["next_at"] is None for r in rows(db, "outbox"))
    assert legacy_attest == [action] and effects.count("feed", action) == 1, (
        "the legacy path did not deliver the attestation and the feed entry in shadow")
    assert effects.count("attest_sent") == 0, "shadow delivered through the outbox"
    assert wiring.current() is before, "the test left another engine installed"

