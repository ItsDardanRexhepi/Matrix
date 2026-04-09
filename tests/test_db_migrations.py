"""Tests for runtime.db.database schema migrations."""

import sqlite3

import pytest

from runtime.db import database as db_module
from runtime.db.database import Database, MIGRATIONS


@pytest.fixture
def fresh_db(tmp_path):
    return Database({"database": {"path": str(tmp_path / "mig.db")}})


class TestSchemaVersion:
    def test_fresh_db_has_latest_version(self, fresh_db):
        latest = max(v for v, _, _ in MIGRATIONS)
        assert fresh_db.schema_version == latest

    def test_schema_version_table_created(self, fresh_db):
        rows = fresh_db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchall()
        assert len(rows) == 1

    def test_all_migrations_recorded(self, fresh_db):
        rows = fresh_db._conn.execute(
            "SELECT version, description, applied_at FROM schema_version ORDER BY version"
        ).fetchall()
        applied = [r[0] for r in rows]
        expected = [v for v, _, _ in sorted(MIGRATIONS)]
        assert applied == expected
        # applied_at is a real timestamp for every row
        assert all(isinstance(r[2], float) and r[2] > 0 for r in rows)


class TestIdempotency:
    def test_reopen_does_not_reapply(self, tmp_path):
        path = tmp_path / "same.db"
        Database({"database": {"path": str(path)}})

        # Open the file with a plain sqlite3 connection, count rows, then
        # reopen through Database and confirm nothing was duplicated.
        conn = sqlite3.connect(str(path))
        before = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        conn.close()

        Database({"database": {"path": str(path)}})

        conn = sqlite3.connect(str(path))
        after = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        conn.close()

        assert before == after


class TestNewMigrationIsApplied:
    def test_added_migration_runs_on_next_open(self, tmp_path, monkeypatch):
        # First open establishes v1 only.
        path = tmp_path / "upgrade.db"
        Database({"database": {"path": str(path)}})._conn.close()
        conn = sqlite3.connect(str(path))
        assert {r[0] for r in conn.execute("SELECT version FROM schema_version").fetchall()} == {1}
        conn.close()

        # Inject a fake v999 migration, reopen, and verify it ran.
        fake_migration = (
            999,
            "test migration",
            ["CREATE TABLE IF NOT EXISTS _mig_test (id INTEGER PRIMARY KEY)"],
        )
        original = list(db_module.MIGRATIONS)
        monkeypatch.setattr(db_module, "MIGRATIONS", original + [fake_migration])

        Database({"database": {"path": str(path)}})._conn.close()

        conn = sqlite3.connect(str(path))
        versions = {
            r[0] for r in conn.execute("SELECT version FROM schema_version").fetchall()
        }
        assert 999 in versions
        # The table from the new migration exists.
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "_mig_test" in tables
        conn.close()


class TestRollbackOnFailure:
    def test_failed_migration_does_not_record_version(self, tmp_path, monkeypatch):
        path = tmp_path / "rollback.db"
        # First bring the DB up to the normal state.
        Database({"database": {"path": str(path)}})._conn.close()

        # Add a broken migration that fails on its second statement.
        broken = (
            888,
            "broken migration",
            [
                "CREATE TABLE IF NOT EXISTS _mig_partial (id INTEGER PRIMARY KEY)",
                "THIS IS NOT VALID SQL",
            ],
        )
        original = list(db_module.MIGRATIONS)
        monkeypatch.setattr(db_module, "MIGRATIONS", original + [broken])

        with pytest.raises(sqlite3.Error):
            Database({"database": {"path": str(path)}})

        conn = sqlite3.connect(str(path))
        versions = {
            r[0] for r in conn.execute("SELECT version FROM schema_version").fetchall()
        }
        assert 888 not in versions
        # The partial table should not exist because the migration rolled back.
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "_mig_partial" not in tables
        conn.close()


class TestMigrationListIntegrity:
    def test_versions_are_unique_and_monotonic(self):
        versions = [v for v, _, _ in MIGRATIONS]
        assert len(versions) == len(set(versions)), "duplicate migration versions"
        assert versions == sorted(versions), "migrations not sorted by version"

    def test_each_migration_has_statements(self):
        for version, desc, statements in MIGRATIONS:
            assert desc, f"migration v{version} missing description"
            assert statements, f"migration v{version} has no statements"
