"""Durable execution (engines Phase 2): the four tables, the run journal's state
machine and recovery, and the idempotency store.

What these pin: migration 10 is additive and creates exactly the four tables;
a run moves only START → RUNNING → COMPLETE | FAIL, or START → ABORT, each move
a compare-and-set; recovery ends an abandoned START run ABORT only when an
engine that owned it recorded it (its call cannot have begun), leaves any
other START and every RUNNING one where it is (its call may have acted), and
does the same thing however often and on whichever copy it runs; a key binds
once, and answers hit / conflict / in_flight / expired without binding again.
"""

from __future__ import annotations

import sqlite3
import sys

import pytest

sys.path.insert(0, "tests")

from durable_harness import Clock, copy_file, database, projection  # noqa: E402
from runtime.blockchain.services.service_dispatcher import params_digest  # noqa: E402
from runtime.db.database import MIGRATIONS  # noqa: E402
from runtime.durable import journal, keys, wiring  # noqa: E402

NEW_TABLES = {"workflow_runs", "workflow_steps", "outbox", "idempotency_keys"}


def _tables(db) -> set[str]:
    return {r[0] for r in db.fetchall_sync("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(db, table: str) -> list[str]:
    return [r[1] for r in db.fetchall_sync(f"PRAGMA table_info({table})")]


# ── migration 10 ─────────────────────────────────────────────────────────────

def test_migration_10_creates_the_four_tables_and_nothing_else(tmp_path):
    (v10,) = [m for m in MIGRATIONS if m[0] == 10]
    assert max(v for v, _, _ in MIGRATIONS) == 10
    for stmt in v10[2]:
        assert "IF NOT EXISTS" in stmt, stmt
        assert not any(w in stmt.upper() for w in ("DROP ", "ALTER ", "DELETE ", "UPDATE ")), stmt
    created = {stmt.split("EXISTS", 1)[1].split("(", 1)[0].strip()
               for stmt in v10[2] if "CREATE TABLE" in stmt}
    assert created == NEW_TABLES
    db = database(tmp_path / "a.db")
    assert NEW_TABLES <= _tables(db)
    assert _columns(db, "workflow_runs") == [
        "run_id", "key", "action", "service", "actor_hash", "params_digest", "state",
        "decision_ref", "started_at", "terminal_at"]
    assert _columns(db, "workflow_steps") == [
        "run_id", "seq", "kind", "payload_digest", "tx_hash", "state", "at"]
    assert _columns(db, "outbox") == [
        "id", "run_id", "kind", "payload", "payload_digest", "state", "attempts", "next_at",
        "done_at", "last_error", "created_at"]
    assert _columns(db, "idempotency_keys") == [
        "key", "run_id", "first_seen", "response_digest", "request_digest", "status",
        "response", "expires_at"]


def test_a_version_9_file_upgrades_and_keeps_its_rows(tmp_path):
    """Additive: a database written before migration 10 gains the tables and
    loses nothing."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, "
                 "description TEXT NOT NULL, applied_at REAL NOT NULL)")
    conn.commit()
    conn.close()
    import runtime.db.database as dbmod
    before = [m for m in dbmod.MIGRATIONS if m[0] <= 9]
    original = dbmod.MIGRATIONS
    dbmod.MIGRATIONS = before
    try:
        db = database(path)
        db.execute_sync("INSERT INTO evidence_shadow (run_id, action, service, params_digest, "
                        "legacy_verdict, observed_at) VALUES ('r', 'a', 's', 'd', 'settled', 1)")
        assert db.schema_version == 9 and not (NEW_TABLES & _tables(db))
        db._conn.close()
    finally:
        dbmod.MIGRATIONS = original
    db = database(path)
    assert db.schema_version == 10 and NEW_TABLES <= _tables(db)
    assert db.fetchall_sync("SELECT COUNT(*) FROM evidence_shadow")[0][0] == 1


def test_a_run_state_outside_the_five_is_refused_by_the_table(tmp_path):
    db = database(tmp_path / "a.db")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute_sync("INSERT INTO workflow_runs (run_id, action, params_digest, state, "
                        "started_at) VALUES ('r', 'a', 'd', 'VERIFIED', 1)")


# ── the journal ──────────────────────────────────────────────────────────────

def _start(db, run_id="run_a", state=journal.START, at=100.0, word=journal.START_OWNED):
    def work(conn):
        journal.insert_run(conn, run_id=run_id, action="transfer_stablecoin", service="stablecoin",
                           actor_hash="h", params_digest="p", state=state, started_at=at)
        journal.append_step(conn, run_id, journal.STEP_START, word, at=at)
    db.transaction_sync(work)


def test_the_only_moves_a_run_makes(tmp_path):
    allowed = {(journal.START, journal.RUNNING), (journal.START, journal.ABORT),
               (journal.RUNNING, journal.COMPLETE), (journal.RUNNING, journal.FAIL)}
    assert journal.TRANSITIONS == allowed
    db = database(tmp_path / "a.db")
    _start(db)
    for a in journal.STATES:
        for b in journal.STATES:
            if (a, b) in allowed:
                continue
            with pytest.raises(ValueError):
                db.transaction_sync(lambda c, a=a, b=b: journal.transition(c, "run_a", a, b, at=1))


def test_a_move_from_the_wrong_state_changes_nothing(tmp_path):
    db = database(tmp_path / "a.db")
    _start(db)
    assert db.transaction_sync(lambda c: journal.transition(c, "run_a", journal.RUNNING,
                                                            journal.COMPLETE, at=1)) is False
    assert journal.get_run(db, "run_a")["state"] == journal.START
    assert db.transaction_sync(lambda c: journal.transition(c, "run_a", journal.START,
                                                            journal.RUNNING, at=1)) is True
    assert db.transaction_sync(lambda c: journal.transition(c, "run_a", journal.START,
                                                            journal.RUNNING, at=1)) is False
    assert db.transaction_sync(lambda c: journal.transition(c, "run_a", journal.RUNNING,
                                                            journal.FAIL, at=2)) is True
    run = journal.get_run(db, "run_a")
    assert run["state"] == journal.FAIL and run["terminal_at"] == 2


def test_steps_are_numbered_in_order(tmp_path):
    db = database(tmp_path / "a.db")
    _start(db)
    db.transaction_sync(lambda c: journal.append_step(c, "run_a", journal.STEP_CALL,
                                                      "attempting", at=2))
    assert [(s["seq"], s["kind"]) for s in journal.get_steps(db, "run_a")] == [
        (1, "start"), (2, "call")]


def test_recovery_aborts_an_abandoned_start_and_never_moves_a_running_run(tmp_path):
    db = database(tmp_path / "a.db")
    _start(db, "run_s", journal.START, at=100.0)
    _start(db, "run_r", journal.RUNNING, at=100.0)
    _start(db, "run_fresh", journal.START, at=100.0 + 290)
    now = 100.0 + journal.ABANDONED_AFTER_S + 1
    result = db.transaction_sync(lambda c: journal.recover_runs(c, now=now))
    assert result == {"aborted": ["run_s"], "undetermined": [], "unknown": ["run_r"]}
    assert journal.get_run(db, "run_s")["state"] == journal.ABORT
    assert journal.get_steps(db, "run_s")[-1]["kind"] == journal.STEP_ABORT
    assert journal.get_run(db, "run_r")["state"] == journal.RUNNING
    assert [(s["kind"], s["state"]) for s in journal.get_steps(db, "run_r")][-1] == (
        journal.STEP_UNKNOWN, journal.NO_ANSWER_RECORDED)
    assert journal.get_run(db, "run_fresh")["state"] == journal.START, "inside the window"


@pytest.mark.parametrize("word", [journal.START_OBSERVED, "", "anything else"])
def test_recovery_never_reads_a_start_it_did_not_own_as_not_attempted(word, tmp_path):
    """Only an engine that owned a run keeps its call from beginning before the
    RUNNING mark. A START left by any other writer — shadow, mode on outside its
    canary, or a start step that says neither — may have been called unmarked:
    it is not closed, and its key is not given back, so a replay never acts."""
    db = database(tmp_path / "a.db")
    _start(db, "run_o", journal.START, at=100.0, word=word)
    db.transaction_sync(lambda c: keys.claim(c, key="k", request_digest="d", run_id="run_o",
                                             now=100.0))
    eng = wiring.DurableEngine(db, mode="on", canary="state_modifying",
                               clock=Clock(100.0 + journal.ABANDONED_AFTER_S + 1))
    first = eng.maintain()
    assert first["runs"] == {"aborted": [], "undetermined": ["run_o"], "unknown": []}
    assert journal.get_run(db, "run_o")["state"] == journal.START
    assert [(s["kind"], s["state"]) for s in journal.get_steps(db, "run_o")][-1] == (
        journal.STEP_UNKNOWN, journal.NOT_KNOWN_IF_CALLED)
    assert _claim(db, key="k", digest="d", run_id="run_new", now=500.0).outcome == keys.IN_FLIGHT
    assert eng.maintain()["runs"] == {"aborted": [], "undetermined": [], "unknown": []}
    assert eng._maintenance_due(eng._clock()) is False, "nothing left to write"


def test_recovery_is_idempotent_and_the_same_on_every_copy(tmp_path):
    db = database(tmp_path / "a.db")
    _start(db, "run_s", journal.START, at=1.0)
    _start(db, "run_r", journal.RUNNING, at=1.0)
    db._conn.close()
    copies = [database(copy_file(tmp_path / "a.db", tmp_path / f"c{i}.db")) for i in range(2)]
    for i, copy in enumerate(copies):
        copy.transaction_sync(lambda c, i=i: journal.recover_runs(c, now=10_000.0 + i))
        again = copy.transaction_sync(lambda c: journal.recover_runs(c, now=20_000.0))
        assert again == {"aborted": [], "undetermined": [], "unknown": []}
    assert projection(copies[0]) == projection(copies[1])


def test_the_journal_digest_is_the_evidence_shadow_digest():
    for value in ({}, {"b": 1, "a": [1, 2]}, {"to": "0xé", "amount": 5.5}, {"x": object}):
        assert journal.digest(value) == params_digest(value)


# ── the keys ─────────────────────────────────────────────────────────────────

def _claim(db, key="k", digest="d1", run_id="run_1", now=0.0):
    return db.transaction_sync(lambda c: keys.claim(c, key=key, request_digest=digest,
                                                    run_id=run_id, now=now))


def test_a_key_binds_once_and_then_says_what_it_is_bound_to(tmp_path):
    db = database(tmp_path / "a.db")
    assert _claim(db).outcome == keys.MISS
    assert _claim(db, run_id="run_2").outcome == keys.IN_FLIGHT
    assert _claim(db, digest="d2", run_id="run_3").outcome == keys.CONFLICT
    assert db.transaction_sync(lambda c: keys.record_response(
        c, key="k", run_id="run_2", status=200, body="x")) is False, "only the binder records"
    assert db.transaction_sync(lambda c: keys.record_response(
        c, key="k", run_id="run_1", status=200, body='{"ok": true}')) is True
    assert db.transaction_sync(lambda c: keys.record_response(
        c, key="k", run_id="run_1", status=500, body="later")) is False, "recorded once"
    hit = _claim(db, run_id="run_4", now=10.0)
    assert (hit.outcome, hit.run_id, hit.status, hit.response) == (
        keys.HIT, "run_1", 200, '{"ok": true}')
    assert db.fetchall_sync("SELECT COUNT(*) FROM idempotency_keys")[0][0] == 1


def test_an_answer_is_kept_24_hours_and_the_key_for_ever(tmp_path):
    db = database(tmp_path / "a.db")
    _claim(db)
    db.transaction_sync(lambda c: keys.record_response(c, key="k", run_id="run_1",
                                                       status=200, body="{}"))
    late = keys.ANSWER_KEPT_S + 1
    assert _claim(db, now=late).outcome == keys.EXPIRED, "past the window, before the sweep"
    assert db.transaction_sync(lambda c: keys.drop_expired_answers(c, now=late)) == 1
    row = dict(db.fetchall_sync("SELECT * FROM idempotency_keys")[0])
    assert row["response"] is None and row["status"] == 200 and row["response_digest"]
    assert _claim(db, now=late * 5).outcome == keys.EXPIRED, "never a fresh bind"


def test_releasing_is_only_for_a_key_with_no_answer(tmp_path):
    db = database(tmp_path / "a.db")
    _claim(db)
    assert db.transaction_sync(lambda c: keys.release(c, key="k", run_id="run_x")) is False
    assert db.transaction_sync(lambda c: keys.release(c, key="k", run_id="run_1")) is True
    assert _claim(db, run_id="run_2").outcome == keys.MISS
    db.transaction_sync(lambda c: keys.record_response(c, key="k", run_id="run_2",
                                                       status=200, body="{}"))
    assert db.transaction_sync(lambda c: keys.release(c, key="k", run_id="run_2")) is False


def test_the_client_key_shape():
    for good in ("8f14e45f-ceea-467a-9575-1a2b3c4d5e6f", "abcdefgh", "a.b:c_d-e" + "x" * 55):
        assert keys.valid_client_key(good), good
    for bad in (None, 7, "", "short", "x" * 65, "has space12", "slash/in/it", "ünïcode12"):
        assert not keys.valid_client_key(bad), bad


def test_a_scoped_key_is_the_callers_own():
    a = keys.scoped_key("bridge.action", "session|0xA", "key-12345")
    assert a == keys.scoped_key("bridge.action", "session|0xA", "key-12345")
    assert a != keys.scoped_key("bridge.action", "session|0xB", "key-12345")
    assert a != keys.scoped_key("other.surface", "session|0xA", "key-12345")
    assert "key-12345" not in a and a.startswith("sha256:")


def test_secret_named_fields_are_withheld_at_any_depth_and_nothing_else_changes():
    same = {"ok": True, "data": {"token": "USDC", "key": "0xpub", "amount": 5}}
    assert keys.withhold_secrets(same) is same
    nested = {"ok": True, "data": '{"result": {"private_key": "0xdead", "tx_hash": "0x1"}}',
              "items": [{"Mnemonic": "a b c"}, {"fine": 1}]}
    cleaned = keys.withhold_secrets(nested)
    assert cleaned["items"][0]["Mnemonic"] == keys.WITHHELD
    assert cleaned["items"][1] == {"fine": 1}
    import json
    inner = json.loads(cleaned["data"])
    assert inner["result"] == {"private_key": keys.WITHHELD, "tx_hash": "0x1"}
    assert nested["items"][0]["Mnemonic"] == "a b c", "the original is not mutated"


def test_a_transaction_the_connection_already_holds_is_refused(tmp_path):
    db = database(tmp_path / "a.db")
    db._conn.execute("BEGIN")
    try:
        with pytest.raises(sqlite3.OperationalError):
            db.transaction_sync(lambda c: None)
    finally:
        db._conn.execute("ROLLBACK")


def test_a_write_that_must_not_wait_fails_at_once_and_restores_the_timeout(tmp_path):
    import time
    db = database(tmp_path / "a.db")
    other = sqlite3.connect(tmp_path / "a.db", isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    try:
        before = db.fetchall_sync("PRAGMA busy_timeout")[0][0]
        t0 = time.perf_counter()
        with pytest.raises(sqlite3.OperationalError):
            db.transaction_sync(lambda c: c.execute("DELETE FROM outbox"), wait=False)
        assert time.perf_counter() - t0 < 1.0
        assert db.fetchall_sync("PRAGMA busy_timeout")[0][0] == before
        assert not db._conn.in_transaction
    finally:
        other.execute("ROLLBACK")
        other.close()
