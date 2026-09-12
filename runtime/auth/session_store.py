"""Persistent SIWE wallet sessions and pending nonces.

Both stores are write-through: an in-memory cache backed by SQLite. Reads
go through the cache so callers don't need to ``await`` (which keeps the
gateway request handler simple), and writes are mirrored to disk so a
process restart doesn't kick every signed-in user back to the auth flow.

Cleanup of expired sessions and nonces is driven by
:func:`run_cleanup_loop`, which is started as a background task in the
gateway's ``on_startup`` hook.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from runtime.db.database import Database

logger = logging.getLogger(__name__)


# Default TTL for unconsumed nonces, in seconds.
NONCE_TTL_SECONDS = 300


class WalletSessionStore:
    """SQLite-backed map of session token → wallet session record.

    The shape of each record matches the legacy in-memory dict::

        {"address": str, "issued_at": float, "expires_at": float}

    so existing callers (gateway/server.py, gateway/bridge.py) keep
    working without changes to their access patterns.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._cache: dict[str, dict[str, Any]] = {}
        self._loaded = False

    async def initialize(self) -> None:
        """Populate the cache from disk. Safe to call multiple times."""
        if self._loaded:
            return
        rows = await self._db.fetchall(
            "SELECT token, address, issued_at, expires_at FROM wallet_sessions"
        )
        now = time.time()
        for r in rows:
            if r["expires_at"] <= now:
                continue
            self._cache[r["token"]] = {
                "address": r["address"],
                "issued_at": r["issued_at"],
                "expires_at": r["expires_at"],
            }
        self._loaded = True
        logger.info("Loaded %d active wallet sessions", len(self._cache))

    # ── Dict-like read API (sync for hot path) ─────────────────────

    def get(self, token: str, default: Any = None) -> dict[str, Any] | None:
        """The live record for *token*, or *default* when unknown OR EXPIRED.

        Expiry is honoured here, at the one read path, so no consumer can
        accept a stale session by forgetting to compare ``expires_at`` (the
        rate limiter did; the IAP binding and account deletion did not).
        The expired row stays for ``cleanup()`` to sweep.
        """
        record = self._cache.get(token)
        if record is None:
            return default
        if float(record.get("expires_at", 0)) <= time.time():
            return default
        return record

    def __contains__(self, token: str) -> bool:
        return self.get(token) is not None

    def __len__(self) -> int:
        return len(self._cache)

    def __iter__(self):
        return iter(self._cache)

    def items(self):
        return self._cache.items()

    # ── Async writes ───────────────────────────────────────────────

    async def add(
        self,
        token: str,
        address: str,
        issued_at: float,
        expires_at: float,
    ) -> dict[str, Any]:
        record = {
            "address": address,
            "issued_at": issued_at,
            "expires_at": expires_at,
        }
        self._cache[token] = record
        await self._db.execute(
            """
            INSERT INTO wallet_sessions (token, address, issued_at, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(token) DO UPDATE SET
                address = excluded.address,
                issued_at = excluded.issued_at,
                expires_at = excluded.expires_at
            """,
            (token, address, issued_at, expires_at),
        )
        return record

    async def remove(self, token: str) -> None:
        self._cache.pop(token, None)
        await self._db.execute(
            "DELETE FROM wallet_sessions WHERE token = ?",
            (token,),
        )

    async def cleanup(self) -> int:
        """Remove expired sessions from cache and disk. Returns drop count."""
        now = time.time()
        expired = [t for t, s in self._cache.items() if s["expires_at"] <= now]
        for t in expired:
            self._cache.pop(t, None)
        if expired:
            await self._db.execute(
                "DELETE FROM wallet_sessions WHERE expires_at <= ?",
                (now,),
            )
        return len(expired)


class NonceStore:
    """SQLite-backed set of in-flight SIWE nonces."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._cache: dict[str, float] = {}
        self._loaded = False

    async def initialize(self) -> None:
        if self._loaded:
            return
        rows = await self._db.fetchall(
            "SELECT nonce, issued_at FROM wallet_nonces"
        )
        cutoff = time.time() - NONCE_TTL_SECONDS
        for r in rows:
            if r["issued_at"] < cutoff:
                continue
            self._cache[r["nonce"]] = r["issued_at"]
        self._loaded = True
        logger.info("Loaded %d pending wallet nonces", len(self._cache))

    # ── Read API (sync) ────────────────────────────────────────────

    def __contains__(self, nonce: str) -> bool:
        return nonce in self._cache

    def __len__(self) -> int:
        return len(self._cache)

    # ── Async writes ───────────────────────────────────────────────

    async def add(self, nonce: str) -> None:
        ts = time.time()
        self._cache[nonce] = ts
        await self._db.execute(
            """
            INSERT INTO wallet_nonces (nonce, issued_at)
            VALUES (?, ?)
            ON CONFLICT(nonce) DO UPDATE SET issued_at = excluded.issued_at
            """,
            (nonce, ts),
        )

    async def consume(self, nonce: str) -> bool:
        """Atomically remove *nonce* from the store. Returns True if it existed."""
        existed = self._cache.pop(nonce, None) is not None
        await self._db.execute(
            "DELETE FROM wallet_nonces WHERE nonce = ?",
            (nonce,),
        )
        return existed

    async def cleanup(self, ttl_seconds: int = NONCE_TTL_SECONDS) -> int:
        cutoff = time.time() - ttl_seconds
        expired = [n for n, ts in self._cache.items() if ts < cutoff]
        for n in expired:
            self._cache.pop(n, None)
        if expired:
            await self._db.execute(
                "DELETE FROM wallet_nonces WHERE issued_at < ?",
                (cutoff,),
            )
        return len(expired)


class AppleUserStore:
    """SQLite-backed record of every Apple user the gateway has issued a session
    to, keyed by Apple's stable ``sub``, with the wallet linked to it (if any).

    Until this existed, ``/api/v1/auth/apple`` answered ``isNewUser: true`` and
    ``walletAddress: ""`` for everyone on every sign-in — two constants dressed
    as facts. Write-through like the session store: sync reads, async writes.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._cache: dict[str, dict[str, Any]] = {}
        self._loaded = False

    async def initialize(self) -> None:
        if self._loaded:
            return
        rows = await self._db.fetchall(
            "SELECT sub, first_seen, last_seen, wallet_address FROM apple_users"
        )
        for r in rows:
            self._cache[r["sub"]] = {
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
                "wallet_address": r["wallet_address"] or "",
            }
        self._loaded = True
        logger.info("Loaded %d Apple users", len(self._cache))

    # ── Read API (sync) ───────────────────────────────────────────────

    def get(self, sub: str) -> dict[str, Any] | None:
        return self._cache.get(sub)

    def wallet_for(self, sub: str) -> str:
        record = self._cache.get(sub)
        return str(record.get("wallet_address", "")) if record else ""

    def __len__(self) -> int:
        return len(self._cache)

    # ── Async writes ──────────────────────────────────────────────────

    async def touch(self, sub: str) -> bool:
        """Record a sign-in. Returns True when this is the first time *sub* is seen."""
        now = time.time()
        record = self._cache.get(sub)
        is_new = record is None
        if is_new:
            record = {"first_seen": now, "last_seen": now, "wallet_address": ""}
            self._cache[sub] = record
        else:
            record["last_seen"] = now
        await self._db.execute(
            """
            INSERT INTO apple_users (sub, first_seen, last_seen, wallet_address)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(sub) DO UPDATE SET last_seen = excluded.last_seen
            """,
            (sub, record["first_seen"], record["last_seen"], record["wallet_address"]),
        )
        return is_new

    async def link_wallet(self, sub: str, wallet_address: str) -> None:
        """Bind a wallet the user has proven (SIWE) to their Apple identity."""
        now = time.time()
        record = self._cache.setdefault(
            sub, {"first_seen": now, "last_seen": now, "wallet_address": ""})
        record["wallet_address"] = wallet_address
        await self._db.execute(
            """
            INSERT INTO apple_users (sub, first_seen, last_seen, wallet_address)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(sub) DO UPDATE SET wallet_address = excluded.wallet_address,
                                          last_seen = excluded.last_seen
            """,
            (sub, record["first_seen"], now, wallet_address),
        )


async def run_cleanup_loop(
    sessions: WalletSessionStore,
    nonces: NonceStore,
    interval_seconds: int = 300,
) -> None:
    """Periodic cleanup task — cancel via ``task.cancel()`` on shutdown."""
    logger.info(
        "Wallet auth cleanup loop started (interval=%ds)", interval_seconds
    )
    try:
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                dropped_sessions = await sessions.cleanup()
                dropped_nonces = await nonces.cleanup()
                if dropped_sessions or dropped_nonces:
                    logger.info(
                        "Auth cleanup: dropped %d sessions, %d nonces",
                        dropped_sessions, dropped_nonces,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Auth cleanup iteration failed: %s", exc)
    except asyncio.CancelledError:
        logger.info("Wallet auth cleanup loop stopped")
        raise
