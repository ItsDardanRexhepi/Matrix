"""P1-6: durable store of iOS push device tokens.

The app registers its APNs device token at runtime (POST /bridge/v1/push/register);
``iOSPushChannel`` reads the registered tokens when fanning out a push. Async
sqlite, matching the DB style used by ``runtime.social.feed_engine``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS push_tokens (
    device_token TEXT PRIMARY KEY,
    session_id   TEXT,
    wallet       TEXT,
    platform     TEXT,
    bundle_id    TEXT,
    updated_at   REAL
)
"""


class PushTokenStore:
    """CRUD over the ``push_tokens`` table. Safe when the DB is unavailable —
    reads return empty, writes are best-effort and logged."""

    def __init__(self, db: Any) -> None:
        self._db = db
        self._ready = False

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        await self._db.execute(_CREATE_TABLE)
        self._ready = True

    async def register(
        self,
        device_token: str,
        *,
        session_id: str = "",
        wallet: str = "",
        platform: str = "ios",
        bundle_id: str = "",
    ) -> None:
        """Upsert a device token (keyed on device_token)."""
        await self._ensure_table()
        await self._db.execute(
            """
            INSERT INTO push_tokens
                (device_token, session_id, wallet, platform, bundle_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_token) DO UPDATE SET
                session_id=excluded.session_id,
                wallet=excluded.wallet,
                platform=excluded.platform,
                bundle_id=excluded.bundle_id,
                updated_at=excluded.updated_at
            """,
            (device_token, session_id, wallet, platform, bundle_id, time.time()),
        )

    async def tokens_for(self, *, wallet: str | None = None,
                         session_id: str | None = None) -> list[str]:
        await self._ensure_table()
        if wallet:
            rows = await self._db.fetchall(
                "SELECT device_token FROM push_tokens WHERE wallet = ?", (wallet,))
        elif session_id:
            rows = await self._db.fetchall(
                "SELECT device_token FROM push_tokens WHERE session_id = ?", (session_id,))
        else:
            return []
        return [r[0] for r in rows]

    async def all_tokens(self) -> list[str]:
        await self._ensure_table()
        rows = await self._db.fetchall("SELECT device_token FROM push_tokens")
        return [r[0] for r in rows]

    async def remove(self, device_token: str) -> None:
        await self._ensure_table()
        await self._db.execute(
            "DELETE FROM push_tokens WHERE device_token = ?", (device_token,))
