"""P2-10: minimal social follow-graph storage.

Backs GET /social/{address}/followers|following and POST /social/follow|unfollow.
Async sqlite, matching the feed_engine DB style.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS social_follows (
    follower   TEXT,
    followee   TEXT,
    created_at REAL,
    PRIMARY KEY (follower, followee)
)
"""


class FollowStore:
    def __init__(self, db: Any) -> None:
        self._db = db
        self._ready = False

    async def _ensure(self) -> None:
        if not self._ready:
            await self._db.execute(_CREATE_TABLE)
            self._ready = True

    async def follow(self, follower: str, followee: str) -> None:
        await self._ensure()
        if not follower or not followee or follower == followee:
            return
        await self._db.execute(
            "INSERT OR IGNORE INTO social_follows (follower, followee, created_at) "
            "VALUES (?, ?, ?)",
            (follower, followee, time.time()),
        )

    async def unfollow(self, follower: str, followee: str) -> None:
        await self._ensure()
        await self._db.execute(
            "DELETE FROM social_follows WHERE follower = ? AND followee = ?",
            (follower, followee),
        )

    async def followers(self, address: str) -> list[str]:
        await self._ensure()
        rows = await self._db.fetchall(
            "SELECT follower FROM social_follows WHERE followee = ?", (address,))
        return [r[0] for r in rows]

    async def following(self, address: str) -> list[str]:
        await self._ensure()
        rows = await self._db.fetchall(
            "SELECT followee FROM social_follows WHERE follower = ?", (address,))
        return [r[0] for r in rows]
