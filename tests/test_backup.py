"""Tests for runtime.db.backup.BackupManager."""

import sqlite3

import pytest

from runtime.db.database import Database
from runtime.db.backup import BackupManager, BACKUP_PREFIX, BACKUP_SUFFIX


@pytest.fixture
def db(tmp_path):
    return Database({"database": {"path": str(tmp_path / "live.db")}})


class TestBackupManagerCreate:
    @pytest.mark.asyncio
    async def test_creates_backup_file(self, tmp_path, db):
        await db.execute(
            "INSERT INTO agent_memory (agent, key, value, updated_at) VALUES (?, ?, ?, ?)",
            ("neo", "k", '"v"', 1.0),
        )
        mgr = BackupManager(db, backup_dir=tmp_path / "backups")
        dest = await mgr.create_backup()
        assert dest.exists()
        assert dest.name.startswith(BACKUP_PREFIX)
        assert dest.name.endswith(BACKUP_SUFFIX)

    @pytest.mark.asyncio
    async def test_backup_contains_data(self, tmp_path, db):
        await db.execute(
            "INSERT INTO agent_memory (agent, key, value, updated_at) VALUES (?, ?, ?, ?)",
            ("trinity", "level", "42", 1.0),
        )
        mgr = BackupManager(db, backup_dir=tmp_path / "backups")
        dest = await mgr.create_backup()

        # Open the backup as a separate database and verify the row.
        conn = sqlite3.connect(str(dest))
        try:
            row = conn.execute(
                "SELECT value FROM agent_memory WHERE agent = ? AND key = ?",
                ("trinity", "level"),
            ).fetchone()
            assert row is not None
            assert row[0] == "42"
        finally:
            conn.close()


class TestBackupRetention:
    @pytest.mark.asyncio
    async def test_prunes_old_backups(self, tmp_path, db):
        mgr = BackupManager(db, backup_dir=tmp_path / "backups", retention=3)

        # Pre-create five fake backups with monotonically increasing names.
        for i in range(5):
            (mgr.backup_dir / f"{BACKUP_PREFIX}2026010{i}T000000Z{BACKUP_SUFFIX}").write_bytes(b"x")

        deleted = mgr.prune_old()
        assert len(deleted) == 2
        remaining = mgr.list_backups()
        assert len(remaining) == 3
        # Newest survive.
        assert any("20260104" in p.name for p in remaining)

    @pytest.mark.asyncio
    async def test_create_backup_prunes(self, tmp_path, db):
        mgr = BackupManager(db, backup_dir=tmp_path / "backups", retention=2)
        await mgr.create_backup()
        await mgr.create_backup()
        await mgr.create_backup()
        # The oldest should be gone — only 2 left.
        assert len(mgr.list_backups()) == 2

    @pytest.mark.asyncio
    async def test_retention_zero_clamped_to_one(self, tmp_path, db):
        mgr = BackupManager(db, backup_dir=tmp_path / "backups", retention=0)
        assert mgr.retention == 1


class TestBackupListing:
    @pytest.mark.asyncio
    async def test_list_returns_oldest_first(self, tmp_path, db):
        mgr = BackupManager(db, backup_dir=tmp_path / "backups", retention=10)
        for ts in ("20260101T000000Z", "20260103T000000Z", "20260102T000000Z"):
            (mgr.backup_dir / f"{BACKUP_PREFIX}{ts}{BACKUP_SUFFIX}").write_bytes(b"x")
        files = mgr.list_backups()
        assert [f.name for f in files] == [
            f"{BACKUP_PREFIX}20260101T000000Z{BACKUP_SUFFIX}",
            f"{BACKUP_PREFIX}20260102T000000Z{BACKUP_SUFFIX}",
            f"{BACKUP_PREFIX}20260103T000000Z{BACKUP_SUFFIX}",
        ]

    @pytest.mark.asyncio
    async def test_list_ignores_unrelated_files(self, tmp_path, db):
        mgr = BackupManager(db, backup_dir=tmp_path / "backups", retention=10)
        (mgr.backup_dir / "notes.txt").write_text("hi")
        (mgr.backup_dir / f"{BACKUP_PREFIX}20260101T000000Z{BACKUP_SUFFIX}").write_bytes(b"x")
        files = mgr.list_backups()
        assert len(files) == 1
