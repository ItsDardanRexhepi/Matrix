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
    updated_at   REAL,
    owner        TEXT
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
        # `owner` arrived after the table shipped: a device registered before
        # it has no owner, which is the truth (nobody recorded one).
        columns = {row[1] for row in await self._db.fetchall("PRAGMA table_info(push_tokens)")}
        if "owner" not in columns:
            await self._db.execute("ALTER TABLE push_tokens ADD COLUMN owner TEXT")
        self._ready = True

    async def register(
        self,
        device_token: str,
        *,
        session_id: str = "",
        wallet: str = "",
        platform: str = "ios",
        bundle_id: str = "",
        owner: str = "",
    ) -> None:
        """Upsert a device token (keyed on device_token).

        *owner* is the account (session subject) that registered it — what
        account deletion finds a user's devices by. The session id a token is
        filed under is a conversation name the client chose, not the account.
        Re-registering the device WITHOUT an owner keeps the owner it had: an
        upsert that wrote "" there hid the device from its account's deletion.
        """
        await self._ensure_table()
        await self._db.execute(
            """
            INSERT INTO push_tokens
                (device_token, session_id, wallet, platform, bundle_id, updated_at, owner)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_token) DO UPDATE SET
                session_id=excluded.session_id,
                wallet=excluded.wallet,
                platform=excluded.platform,
                bundle_id=excluded.bundle_id,
                updated_at=excluded.updated_at,
                owner=CASE WHEN COALESCE(excluded.owner, '') <> ''
                           THEN excluded.owner ELSE push_tokens.owner END
            """,
            (device_token, session_id, wallet, platform, bundle_id, time.time(), owner),
        )

    async def tokens_for(self, *, wallet: str | None = None,
                         session_id: str | None = None,
                         owner: str | None = None) -> list[str]:
        await self._ensure_table()
        if owner:
            rows = await self._db.fetchall(
                "SELECT device_token FROM push_tokens WHERE owner = ?", (owner,))
        elif wallet:
            rows = await self._db.fetchall(
                "SELECT device_token FROM push_tokens WHERE wallet = ?", (wallet,))
        elif session_id:
            rows = await self._db.fetchall(
                "SELECT device_token FROM push_tokens WHERE session_id = ?", (session_id,))
        else:
            return []
        return [r[0] for r in rows]

    async def adopt_ownerless(self, owner: str, session_ids=()) -> list[str]:
        """Record *owner* on every OWNERLESS device filed under one of
        *session_ids*, and return the tokens adopted.

        WHY THIS EXISTS, AND WHY IT IS NOT A NEW CLAIM. A device registered
        before this table had an ``owner`` column is the account's only through
        its conversation ids — and account deletion reads those ids, then
        erases the rows they live in. So the handle survived exactly one
        attempt: if anything after the erasure failed, the retry looked for the
        account's conversations, found none, and the device was unreachable for
        every deletion that would ever run again — while the retry answered
        ``{"success": true}`` over it.

        Writing the owner down first is the same inference :meth:`remove_for_account`
        already acts on (filed under a conversation this account owns, and
        nobody else has claimed it), made durable BEFORE the evidence for it is
        erased, so a retry can finish the job by owner alone. It removes
        nothing: a deletion that then fails leaves the device registered, which
        is what a deletion that did not happen must leave behind."""
        await self._ensure_table()
        adopted: set[str] = set()
        if not owner:
            return []
        for sid in {s for s in session_ids if s}:
            rows = await self._db.fetchall(
                "SELECT device_token FROM push_tokens "
                "WHERE session_id = ? AND (owner IS NULL OR owner = '')", (sid,))
            for row in rows:
                adopted.add(row[0])
        for device_token in sorted(adopted):
            await self._db.execute(
                "UPDATE push_tokens SET owner = ? WHERE device_token = ? "
                "AND (owner IS NULL OR owner = '')", (owner, device_token))
        return sorted(adopted)

    async def remove_for_account(self, owner: str, session_ids=()) -> list[str]:
        """Remove every device *owner* registered, and every device with NO
        recorded owner filed under one of *session_ids* (the account's own
        conversations): a token stored before tokens carried an owner is found
        by the conversation it was filed under. A device another account
        registered is never removed through a conversation id. Returns the
        tokens removed."""
        await self._ensure_table()
        found: set[str] = set()
        if owner:
            found |= {r[0] for r in await self._db.fetchall(
                "SELECT device_token FROM push_tokens WHERE owner = ?", (owner,))}
        for sid in {s for s in session_ids if s}:
            found |= {r[0] for r in await self._db.fetchall(
                "SELECT device_token FROM push_tokens "
                "WHERE session_id = ? AND (owner IS NULL OR owner = '')", (sid,))}
        for token in found:
            await self.remove(token)
        return sorted(found)

    async def all_tokens(self) -> list[str]:
        await self._ensure_table()
        rows = await self._db.fetchall("SELECT device_token FROM push_tokens")
        return [r[0] for r in rows]

    async def remove(self, device_token: str) -> None:
        await self._ensure_table()
        await self._db.execute(
            "DELETE FROM push_tokens WHERE device_token = ?", (device_token,))
