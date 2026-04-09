"""Backup manager for the SQLite database.

Uses :meth:`Database.backup_to` (the SQLite online backup API) so backups
are consistent even while the gateway is serving requests. Old backups
are pruned by retention count to keep disk usage bounded.

A simple async loop (:func:`run_backup_loop`) drives daily snapshots and
is started from the gateway alongside the other cleanup tasks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from runtime.db.database import Database

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60  # daily
DEFAULT_RETENTION = 7  # keep one week of daily snapshots
BACKUP_PREFIX = "0pnmatrx-"
BACKUP_SUFFIX = ".db"


class BackupManager:
    """Snapshot the live SQLite database to a backup directory."""

    def __init__(
        self,
        db: Database,
        backup_dir: str | Path,
        retention: int = DEFAULT_RETENTION,
    ) -> None:
        self.db = db
        self.backup_dir = Path(backup_dir).expanduser()
        if not self.backup_dir.is_absolute():
            self.backup_dir = Path.cwd() / self.backup_dir
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.retention = max(1, int(retention))

    def _timestamp(self) -> str:
        # UTC ISO timestamp safe for filenames (no colons). Microsecond
        # precision so backups taken in quick succession don't collide.
        now = datetime.now(timezone.utc)
        return now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond:06d}Z"

    async def create_backup(self) -> Path:
        """Write a single backup snapshot and prune old ones."""
        dest = self.backup_dir / f"{BACKUP_PREFIX}{self._timestamp()}{BACKUP_SUFFIX}"
        await self.db.backup_to(dest)
        self.prune_old()
        return dest

    def list_backups(self) -> list[Path]:
        """Return existing backup files, oldest first."""
        files = sorted(
            p for p in self.backup_dir.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}")
            if p.is_file()
        )
        return files

    def prune_old(self) -> list[Path]:
        """Delete backups beyond the retention count. Returns deleted paths."""
        files = self.list_backups()
        if len(files) <= self.retention:
            return []
        excess = files[: len(files) - self.retention]
        deleted: list[Path] = []
        for path in excess:
            try:
                path.unlink()
                deleted.append(path)
            except OSError as exc:
                logger.warning("Failed to delete old backup %s: %s", path, exc)
        return deleted

    def latest_backup(self) -> Path | None:
        """Return the most recent backup file, or ``None`` if there are none."""
        files = self.list_backups()
        return files[-1] if files else None

    async def restore_latest(self) -> Path:
        """Restore the database from the most recent snapshot.

        WARNING: this overwrites the live database file. The caller MUST
        stop the gateway (or at least the backup loop and request
        handlers) first — see ``docs/RUNBOOK.md``.
        """
        latest = self.latest_backup()
        if latest is None:
            raise FileNotFoundError(
                f"No backups found in {self.backup_dir}"
            )
        await self.db.restore_from(latest)
        return latest

    async def restore_from(self, source: str | Path) -> Path:
        """Restore the database from an explicit backup path."""
        path = Path(source)
        await self.db.restore_from(path)
        return path


async def run_backup_loop(
    manager: BackupManager,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
) -> None:
    """Background task: run :meth:`BackupManager.create_backup` periodically.

    The first snapshot is taken after one full interval, not immediately,
    so a frequently restarted process doesn't spam the backup directory.
    """
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            start = time.monotonic()
            dest = await manager.create_backup()
            elapsed = time.monotonic() - start
            logger.info("Database backup written to %s (%.2fs)", dest, elapsed)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Backup loop iteration failed: %s", exc)
