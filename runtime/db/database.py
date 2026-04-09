"""SQLite database layer for 0pnMatrx persistence.

A thin async wrapper around the standard ``sqlite3`` module, with:

- WAL journal mode for concurrent reads while writes are in flight
- One ``asyncio.Lock`` to serialise writes from inside an event loop
- Schema migrations applied at startup (idempotent ``CREATE TABLE IF NOT
  EXISTS`` statements)
- Row factory that yields ``dict``-like objects (``sqlite3.Row``)

The class is intentionally minimal — it does *not* try to be an ORM. The
memory manager, session store, etc. issue raw SQL through
:meth:`execute`, :meth:`executemany`, and :meth:`fetchall`.

The default database path is ``data/0pnmatrx.db``. Override via
``database.path`` in ``openmatrix.config.json`` (relative paths are
resolved against the project root).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)


SCHEMA: list[str] = [
    # ── Agent memory (key/value) ───────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS agent_memory (
        agent       TEXT NOT NULL,
        key         TEXT NOT NULL,
        value       TEXT NOT NULL,
        updated_at  REAL NOT NULL,
        PRIMARY KEY (agent, key)
    )
    """,
    # ── Per-agent conversation turn log ────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS agent_turns (
        agent       TEXT NOT NULL,
        seq         INTEGER NOT NULL,
        user_msg    TEXT NOT NULL,
        agent_msg   TEXT NOT NULL,
        ts          REAL NOT NULL,
        PRIMARY KEY (agent, seq)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_turns_ts
        ON agent_turns (agent, ts)
    """,
    # ── Per-session full conversation history ──────────────────────
    """
    CREATE TABLE IF NOT EXISTS conversation_turns (
        session_id  TEXT NOT NULL,
        seq         INTEGER NOT NULL,
        role        TEXT NOT NULL,
        content     TEXT NOT NULL,
        ts          REAL NOT NULL,
        PRIMARY KEY (session_id, seq)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_turns_ts
        ON conversation_turns (session_id, ts)
    """,
    # ── First-boot welcome tracking ────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS first_boot (
        session_id  TEXT PRIMARY KEY,
        sent_at     REAL NOT NULL
    )
    """,
    # ── SIWE wallet sessions ───────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS wallet_sessions (
        token       TEXT PRIMARY KEY,
        address     TEXT NOT NULL,
        issued_at   REAL NOT NULL,
        expires_at  REAL NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_wallet_sessions_address
        ON wallet_sessions (address)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_wallet_sessions_expires
        ON wallet_sessions (expires_at)
    """,
    # ── SIWE pending nonces ────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS wallet_nonces (
        nonce       TEXT PRIMARY KEY,
        issued_at   REAL NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_wallet_nonces_issued
        ON wallet_nonces (issued_at)
    """,
]


class Database:
    """Async-friendly SQLite wrapper.

    All write operations go through :meth:`execute`/:meth:`executemany`
    and are serialised via a single ``asyncio.Lock``. Reads are not
    locked — SQLite WAL mode lets readers proceed while a writer holds
    the lock at the SQLite level.
    """

    def __init__(self, config: dict) -> None:
        db_cfg = config.get("database", {}) if isinstance(config, dict) else {}
        path = db_cfg.get("path", "data/0pnmatrx.db")
        self.db_path: Path = Path(path).expanduser()
        if not self.db_path.is_absolute():
            # Resolve relative paths against the project root (cwd at startup).
            self.db_path = Path.cwd() / self.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # sqlite3.connect is synchronous and fast — open eagerly so the
        # rest of the codebase can use the database without an extra
        # async init step. The asyncio write lock is created lazily on
        # first use because the event loop may not exist yet.
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit; we manage transactions ourselves
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        for stmt in SCHEMA:
            self._conn.execute(stmt)

        self._write_lock: asyncio.Lock | None = None
        self._initialised = True
        logger.info("Database initialised at %s", self.db_path)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Backward-compat no-op (the DB is opened in __init__)."""
        return None

    async def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error as exc:
                logger.warning("Database close failed: %s", exc)
            self._conn = None  # type: ignore[assignment]
            self._initialised = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database is closed")
        return self._conn

    def _get_lock(self) -> asyncio.Lock:
        """Lazily create the write lock so we don't need a running loop in __init__."""
        if self._write_lock is None:
            self._write_lock = asyncio.Lock()
        return self._write_lock

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
        *,
        commit: bool = True,
    ) -> None:
        """Execute a single statement under the write lock."""
        async with self._get_lock():
            conn = self._require_conn()
            try:
                conn.execute(sql, params or ())
            except sqlite3.Error as exc:
                logger.error("DB execute failed: %s | sql=%s", exc, sql.strip()[:120])
                raise

    async def executemany(
        self,
        sql: str,
        seq_of_params: Iterable[Sequence[Any]],
    ) -> None:
        """Execute a batch under the write lock."""
        async with self._get_lock():
            conn = self._require_conn()
            try:
                conn.executemany(sql, seq_of_params)
            except sqlite3.Error as exc:
                logger.error("DB executemany failed: %s | sql=%s", exc, sql.strip()[:120])
                raise

    async def fetchall(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
    ) -> list[sqlite3.Row]:
        """Run a SELECT and return all rows."""
        conn = self._require_conn()
        try:
            cur = conn.execute(sql, params or ())
            return cur.fetchall()
        except sqlite3.Error as exc:
            logger.error("DB fetchall failed: %s | sql=%s", exc, sql.strip()[:120])
            raise

    async def fetchone(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
    ) -> sqlite3.Row | None:
        conn = self._require_conn()
        try:
            cur = conn.execute(sql, params or ())
            return cur.fetchone()
        except sqlite3.Error as exc:
            logger.error("DB fetchone failed: %s | sql=%s", exc, sql.strip()[:120])
            raise

    # Convenience: synchronous reads for cold-cache lookups during init
    def fetchall_sync(self, sql: str, params: Sequence[Any] | None = None) -> list[sqlite3.Row]:
        conn = self._require_conn()
        cur = conn.execute(sql, params or ())
        return cur.fetchall()

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def vacuum(self) -> None:
        """Reclaim space and defragment. Safe to run periodically."""
        async with self._get_lock():
            conn = self._require_conn()
            conn.execute("VACUUM")

    async def backup_to(self, dest_path: str | os.PathLike) -> None:
        """Create a consistent online backup at *dest_path*."""
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with self._get_lock():
            conn = self._require_conn()
            target = sqlite3.connect(str(dest))
            try:
                conn.backup(target)
            finally:
                target.close()
        logger.info("Database backup written to %s", dest)
