"""A row the public feed stored before its door existed is held to the door.

The door (`SocialFeedEngine.ingest`) refuses what is not public and stores no
caller params, and it reads only what arrives after it. The release before it
stored every settled action with the caller's params in the row's detail: a
followers-only share with its proof_data, an encrypted message, the privacy
service's pins. Nothing reread those rows. GET /social/feed and
/social/actor/{wallet}, which need no session, served them with their params,
/social/trending and /social/stats counted them, and only 10 000 newer events
would have pushed them out. On an install that ran the earlier release, "never
surfaced" was false the day the door shipped.

When the engine opens its table it now deletes each row the door would have
refused and strips the params from each row it would have kept, in one
transaction; and a row read back never hands on params, whoever wrote it.
Each row below is written the way the earlier release's ingest wrote it.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest

from runtime.db.database import Database
from runtime.social.feed_engine import SocialFeedEngine
from runtime.social.feed_formatter import FeedFormatter

OWNER = "0x" + "a" * 40

#: (event_type, the detail the earlier ingest stored) for rows the door refuses.
_REFUSED = [
    ("send_message", {"service": "social", "params": {
        "sharer": OWNER, "proof_type": "achievement",
        "proof_data": {"attestation_uid": "0xUID", "visibility": "followers",
                       "description": "followers only: my diagnosis came back"}}}),
    ("ipfs_pin", {"service": "privacy", "params": {"content": "my medical record"}}),
    ("message_encrypt", {"service": "social", "params": {
        "sender": OWNER, "recipient": "0x" + "b" * 40, "content": "meet me at nine"}}),
]
_KEPT = ("swap_tokens", {"service": "dex", "params": {"amount_in": 5, "memo": "rent money"}})


async def _write_as_the_earlier_release(db, event_type, detail, actor=OWNER) -> str:
    row_id = uuid.uuid4().hex[:16]
    await db.execute(
        "INSERT INTO social_feed_events (id, event_type, actor, summary, detail, component,"
        " tx_hash, value_usd, rarity_score, timestamp, ranked_score)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row_id, event_type, actor, f"{actor[:6]}…{actor[-4:]} did something",
         json.dumps(detail), None, None, None, 0.1, time.time(), 1.0))
    return row_id


@pytest.fixture
async def earlier_table(tmp_path):
    """A database whose feed table the earlier release filled."""
    path = str(tmp_path / "feed.db")
    db = Database({"database": {"path": path}})
    await SocialFeedEngine(db)._ensure_table()
    for event_type, detail in _REFUSED + [_KEPT]:
        await _write_as_the_earlier_release(db, event_type, detail)
    await db.close()
    db = Database({"database": {"path": path}})
    yield db
    await db.close()


async def test_a_row_the_door_refuses_is_not_served_counted_or_kept(earlier_table):
    feed = SocialFeedEngine(earlier_table)
    served = FeedFormatter.format_feed(await feed.get_feed(limit=50))
    actor = await feed.get_actor_feed(OWNER)
    trending = {t["event_type"] for t in await feed.get_trending()}
    stats = await feed.get_stats()
    left = await earlier_table.fetchall("SELECT event_type FROM social_feed_events")

    assert [e["event_type"] for e in served] == ["swap_tokens"], served
    assert [e.event_type for e in actor] == ["swap_tokens"]
    assert trending == {"swap_tokens"}, trending
    assert stats["total_events"] == 1, stats
    assert [r["event_type"] for r in left] == ["swap_tokens"], [dict(r) for r in left]


async def test_a_row_the_door_keeps_loses_the_callers_params_in_the_table(earlier_table):
    feed = SocialFeedEngine(earlier_table)
    served = FeedFormatter.format_feed(await feed.get_feed(limit=50))
    stored = await earlier_table.fetchall("SELECT detail FROM social_feed_events")

    assert served and all("params" not in e["detail"] for e in served), served
    assert "rent money" not in repr(served)
    assert [json.loads(r["detail"]) for r in stored] == [{"service": "dex"}]


async def test_a_row_read_back_never_hands_on_params_whoever_wrote_it(tmp_path):
    """A writer that is not this engine's ingest (an older process on the
    same file) can still write a row with params after the table was opened;
    reading it hands none of them on."""
    db = Database({"database": {"path": str(tmp_path / "feed.db")}})
    feed = SocialFeedEngine(db)
    await feed._ensure_table()
    await _write_as_the_earlier_release(db, *_KEPT)
    served = FeedFormatter.format_feed(await feed.get_feed(limit=10))
    await db.close()
    assert len(served) == 1 and "params" not in served[0]["detail"], served


async def test_scope_pin_a_table_the_door_filled_is_left_as_it_is(tmp_path):
    """SCOPE PIN: rows this release stored are already held to the door, and
    opening the table again changes none of them."""
    path = str(tmp_path / "feed.db")
    db = Database({"database": {"path": path}})
    feed = SocialFeedEngine(db)
    await feed.ingest(action="swap_tokens", actor=OWNER,
                      detail={"service": "dex", "params": {"amount_in": 5}})
    before = [dict(r) for r in await db.fetchall("SELECT * FROM social_feed_events")]
    await db.close()
    db = Database({"database": {"path": path}})
    await SocialFeedEngine(db)._ensure_table()
    after = [dict(r) for r in await db.fetchall("SELECT * FROM social_feed_events")]
    await db.close()
    assert len(before) == 1 and before == after, (before, after)
