"""P2-10: minimal social follow-graph storage.

Backs GET /social/{address}/followers|following and POST /social/follow|unfollow.
Async sqlite, matching the feed_engine DB style.

Both ends of a follow are held in the one spelling the platform names a caller
by (runtime/auth/identity.py), and an address asked about is read in it too:
the follower is the session's caller, already in that spelling, and a followee
or a queried address written in another case is the same wallet.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from runtime.auth.identity import canonical_identity, same_caller

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
        follower, followee = canonical_identity(follower), canonical_identity(followee)
        if not follower or not followee or same_caller(follower, followee):
            return
        await self._db.execute(
            "INSERT OR IGNORE INTO social_follows (follower, followee, created_at) "
            "VALUES (?, ?, ?)",
            (follower, followee, time.time()),
        )

    async def unfollow(self, follower: str, followee: str) -> None:
        await self._ensure()
        follower, followee = canonical_identity(follower), canonical_identity(followee)
        await self._db.execute(
            "DELETE FROM social_follows WHERE follower = ? AND followee = ?",
            (follower, followee),
        )

    async def followers(self, address: str) -> list[str]:
        await self._ensure()
        rows = await self._db.fetchall(
            "SELECT follower FROM social_follows WHERE followee = ?",
            (canonical_identity(address),))
        return [r[0] for r in rows]

    async def following(self, address: str) -> list[str]:
        await self._ensure()
        rows = await self._db.fetchall(
            "SELECT followee FROM social_follows WHERE follower = ?",
            (canonical_identity(address),))
        return [r[0] for r in rows]
