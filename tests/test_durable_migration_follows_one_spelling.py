"""A database main left behind gets the durable tables, and the one-spelling
rewrite of its stored callers exactly once.

THE DEFECT. Main numbered the rewrite of every stored caller into the one
spelling schema migration 10 (runtime/db/database.py). This branch had numbered
its four durable tables (workflow_runs, workflow_steps, outbox,
idempotency_keys) 10 as well. The migration runner applies every version a
database has not recorded, once, in order. With two migrations under one
number, a database main left at schema 10 had version 10 recorded already, so
the four tables were never created there; and a database left at schema 9 took
the rewrite, then failed to record the tables' migration under the version the
rewrite had just recorded, so the migration rolled back and the database could
not be opened at all. And a database a build of this branch opened before the
renumbering recorded the four tables as version 10 and never took the rewrite;
with the tables renumbered 11 it still would not, since it has a version 10
recorded already.

THE RULE. The durable tables are migration 11, after the rewrite. A database
left at schema 9 (the last before either) takes the rewrite and then the four
tables; one left at schema 10 (the rewrite applied) takes the four tables and
not the rewrite again; one a build from before the renumbering left at 10 (the
four tables recorded as 10, no rewrite) takes the rewrite in migration 11's
last step and records version 10 as the rewrite. Every way, each version is
recorded once, the four tables exist, and the rewrite has run once over the
database's whole life: a caller stored before it in another spelling is in the
one spelling after it, and a value stored after it is not rewritten by a
second pass. Numbering alone keeps the first two apart, so the order is pinned
here as well as the outcome.

§CC, measured against the tree at the commit "Merge main into
engines/phase-2-durable: the one-spelling rewrite is schema migration 10 and
the durable tables 11, and /ready holds both the gate's check and the outbox
loop's", with this file's first three checks added and the durable tables'
migration numbered 10 again: all 3 failed. The database left at schema 9 could
not be opened (UNIQUE constraint failed: schema_version.version, and the
migration rolled back); the one left at schema 10 opened with none of the four
tables; the order check found the tables numbered 10, not after the rewrite's
10. tests/test_db_migrations.py failed 4 and errored 3 of its 8 on the same
tree, its check that no two migrations share a version among them. Numbered
11, all 3 here and all 8 there pass.

§CC, second round: measured against the tree at the commit "The security scan
reads the durable outbox's statements clean: each suppression sits on the line
the scanner reports", with the fourth check added (a database whose version 10
is the four tables): it failed, the rewrite having run 0 times, and the other
3 passed. A database of that kind exists: a development database this
branch's build opened on 2026-09-24 records exactly that. With migration 11's
last step, all 4 pass.
"""

from __future__ import annotations

import sqlite3

import pytest

from runtime.db import database

#: The rewrite's migration and the durable tables', found by what they are
#: rather than by the numbers this file checks.
RULE_PREFIX = "a caller stored in one spelling"
DURABLE_PREFIX = "durable execution"
DURABLE_TABLES = ("workflow_runs", "workflow_steps", "outbox", "idempotency_keys")

CHECKSUM = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
LOWER = CHECKSUM.lower()
LATER = "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359"   # stored after the rewrite ran


def _version(prefix: str) -> int:
    found = [v for v, description, _ in database.MIGRATIONS if description.startswith(prefix)]
    assert len(found) == 1, f"{len(found)} migrations are described {prefix!r}"
    return found[0]


def _open(path) -> database.Database:
    return database.Database({"database": {"path": str(path)}})


def _session(path, token: str, address: str) -> None:
    conn = sqlite3.connect(str(path))
    with conn:
        conn.execute("INSERT INTO wallet_sessions VALUES (?, ?, ?, ?)", (token, address, 1.0, 2.0))
    conn.close()


def _tables(db) -> set[str]:
    return {r[0] for r in db._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


@pytest.fixture
def rewrites(monkeypatch):
    """Every run of the one-spelling rewrite, counted over a database's whole
    life. The migration calls the module's function by name when it runs, so
    the count sees each run."""
    runs: list[int] = []
    rewrite = database._one_spelling_for_stored_callers

    def counted(conn):
        runs.append(1)
        return rewrite(conn)
    monkeypatch.setattr(database, "_one_spelling_for_stored_callers", counted)
    return runs


def _left_at(path, monkeypatch, version: int) -> None:
    """A database as main leaves it: every migration up to *version* applied,
    the durable tables' not, whatever number they carry."""
    with monkeypatch.context() as m:
        m.setattr(database, "MIGRATIONS", [x for x in database.MIGRATIONS if x[0] <= version
                                           and not x[1].startswith(DURABLE_PREFIX)])
        db = _open(path)
        assert db.schema_version == version
        assert not set(DURABLE_TABLES) & _tables(db), "a durable table existed before its migration"
        db._conn.close()


def test_the_durable_tables_are_numbered_after_the_rewrite():
    rule, durable = _version(RULE_PREFIX), _version(DURABLE_PREFIX)
    assert (rule, durable) == (10, 11), (
        f"the rewrite is migration {rule} and the durable tables {durable}: a database main "
        "left at the rewrite's schema must still take the tables, so they come after it")


@pytest.mark.parametrize("left_at", [9, 10])
def test_a_database_main_left_gets_the_tables_and_the_rewrite_once(
        tmp_path, monkeypatch, rewrites, left_at):
    path = tmp_path / "left.db"
    _left_at(path, monkeypatch, left_at)
    assert len(rewrites) == (1 if left_at >= 10 else 0)
    if left_at < 10:
        # Before the rewrite: a session stored under the address as it was sent.
        _session(path, "before", CHECKSUM)
    else:
        # After it: a value in another spelling that only a second pass would reach.
        _session(path, "after", LATER)

    db = _open(path)
    for table in DURABLE_TABLES:
        assert table in _tables(db), f"{table} was not created on a database left at {left_at}"
        assert db._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0  # nosec B608
    assert len(rewrites) == 1, f"the rewrite ran {len(rewrites)} times"
    versions = [r[0] for r in db._conn.execute("SELECT version FROM schema_version")]
    assert len(versions) == len(set(versions)), f"a version was recorded twice: {versions}"
    assert sorted(versions) == sorted(v for v, _, _ in database.MIGRATIONS), versions
    assert db.schema_version == _version(DURABLE_PREFIX)
    stored = sorted(tuple(r) for r in db._conn.execute("SELECT token, address FROM wallet_sessions"))
    assert stored == ([("before", LOWER)] if left_at < 10 else [("after", LATER)]), stored
    db._conn.close()

    again = _open(path)
    assert len(rewrites) == 1, "reopening the database ran the rewrite again"
    assert [r[0] for r in again._conn.execute(
        "SELECT COUNT(*) FROM schema_version GROUP BY version HAVING COUNT(*) > 1")] == []
    again._conn.close()


def _left_at_ten_by_a_build_before_the_renumbering(path, monkeypatch) -> None:
    """A database a build of this branch from before the renumbering left:
    versions 1 to 9, then the four durable tables recorded as version 10. That
    build had no rewrite, so the database never took it."""
    durable = next(x for x in database.MIGRATIONS if x[1].startswith(DURABLE_PREFIX))
    with monkeypatch.context() as m:
        m.setattr(database, "MIGRATIONS", [x for x in database.MIGRATIONS if x[0] <= 9] + [
            (10, durable[1], [s for s in durable[2] if not callable(s)])])
        db = _open(path)
        assert db.schema_version == 10
        assert set(DURABLE_TABLES) <= _tables(db)
        db._conn.close()


def test_a_database_whose_10_was_the_durable_tables_takes_the_rewrite_once(
        tmp_path, monkeypatch, rewrites):
    path = tmp_path / "left.db"
    _left_at_ten_by_a_build_before_the_renumbering(path, monkeypatch)
    assert rewrites == []
    _session(path, "before", CHECKSUM)

    db = _open(path)
    assert len(rewrites) == 1, (
        f"the rewrite ran {len(rewrites)} times on a database whose version 10 was the "
        "durable tables: it recorded 10, so the runner never gives it the rewrite's 10")
    stored = sorted(tuple(r) for r in db._conn.execute("SELECT token, address FROM wallet_sessions"))
    assert stored == [("before", LOWER)], stored
    for table in DURABLE_TABLES:
        assert table in _tables(db)
    versions = [r[0] for r in db._conn.execute("SELECT version FROM schema_version")]
    assert sorted(versions) == sorted(v for v, _, _ in database.MIGRATIONS), versions
    (ten,) = db._conn.execute("SELECT description FROM schema_version WHERE version = 10").fetchone()
    assert ten.startswith(RULE_PREFIX), f"version 10 is still recorded as {ten!r}"
    db._conn.close()

    again = _open(path)
    assert len(rewrites) == 1, "reopening the database ran the rewrite again"
    again._conn.close()
