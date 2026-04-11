"""Tests for the Social Feed Engine.

Covers:
- FeedEvent dataclass serialisation/deserialisation
- FeedRankingEngine scoring dimensions
- SocialFeedEngine persistence, queries, pruning
- FeedFormatter presentation helpers
"""

import asyncio
import json
import sqlite3
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from runtime.social.feed_engine import (
    ACTION_LABELS,
    MAX_FEED_EVENTS,
    FeedEvent,
    FeedRankingEngine,
    SocialFeedEngine,
)
from runtime.social.feed_formatter import (
    CATEGORIES,
    ICONS,
    FeedFormatter,
)


# ── Helpers ──────────────────────────────────────────────────────────


class FakeDB:
    """Minimal in-memory database mock matching runtime.db.database.Database."""

    def __init__(self):
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row

    async def execute(self, sql, params=None):
        if params:
            self._conn.execute(sql, params)
        else:
            self._conn.execute(sql)
        self._conn.commit()

    async def executemany(self, sql, seq):
        self._conn.executemany(sql, seq)
        self._conn.commit()

    async def fetchall(self, sql, params=None):
        cur = self._conn.execute(sql, params or ())
        return cur.fetchall()

    async def fetchone(self, sql, params=None):
        cur = self._conn.execute(sql, params or ())
        return cur.fetchone()


# ── FeedEvent ────────────────────────────────────────────────────────


class TestFeedEvent(unittest.TestCase):
    def test_to_dict(self):
        ev = FeedEvent(
            id="abc123",
            event_type="deploy_contract",
            actor="0x1234",
            summary="deployed",
            timestamp=1000.0,
            ranked_score=0.75,
        )
        d = ev.to_dict()
        self.assertEqual(d["id"], "abc123")
        self.assertEqual(d["event_type"], "deploy_contract")
        self.assertEqual(d["ranked_score"], 0.75)

    def test_from_row(self):
        row = {
            "id": "xyz",
            "event_type": "mint_nft",
            "actor": "0xABCD",
            "summary": "minted",
            "detail": json.dumps({"name": "CoolNFT"}),
            "component": 5,
            "tx_hash": "0xtx",
            "value_usd": 100.0,
            "rarity_score": 0.8,
            "timestamp": 2000.0,
            "ranked_score": 0.65,
        }
        ev = FeedEvent.from_row(row)
        self.assertEqual(ev.id, "xyz")
        self.assertEqual(ev.detail["name"], "CoolNFT")
        self.assertEqual(ev.value_usd, 100.0)

    def test_from_row_bad_detail_json(self):
        row = {
            "id": "bad",
            "event_type": "vote",
            "actor": "",
            "summary": "",
            "detail": "not json{{{",
            "component": None,
            "tx_hash": None,
            "value_usd": None,
            "rarity_score": 0,
            "timestamp": 0,
            "ranked_score": 0,
        }
        ev = FeedEvent.from_row(row)
        self.assertEqual(ev.detail, {})

    def test_default_id_generated(self):
        ev = FeedEvent(event_type="test")
        self.assertTrue(len(ev.id) > 0)


# ── FeedRankingEngine ────────────────────────────────────────────────


class TestFeedRankingEngine(unittest.TestCase):
    def setUp(self):
        self.ranker = FeedRankingEngine()

    def test_recency_now_is_one(self):
        score = FeedRankingEngine._recency_score(time.time())
        self.assertAlmostEqual(score, 1.0, places=2)

    def test_recency_old_is_low(self):
        score = FeedRankingEngine._recency_score(time.time() - 86400)
        self.assertLess(score, 0.01)

    def test_rarity_unseen_action_is_one(self):
        score = self.ranker._rarity_score("never_seen_before")
        self.assertEqual(score, 1.0)

    def test_rarity_common_action_is_low(self):
        for _ in range(100):
            self.ranker.observe("swap_tokens", "0xactor")
        score = self.ranker._rarity_score("swap_tokens")
        self.assertLess(score, 0.3)

    def test_value_score_zero_for_none(self):
        self.assertEqual(FeedRankingEngine._value_score(None), 0.0)
        self.assertEqual(FeedRankingEngine._value_score(0), 0.0)
        self.assertEqual(FeedRankingEngine._value_score(-5), 0.0)

    def test_value_score_scales_log(self):
        low = FeedRankingEngine._value_score(10)
        high = FeedRankingEngine._value_score(10000)
        self.assertGreater(high, low)
        self.assertLessEqual(high, 1.0)

    def test_value_score_caps_at_one(self):
        score = FeedRankingEngine._value_score(1_000_000)
        self.assertEqual(score, 1.0)

    def test_novelty_new_actor(self):
        score = self.ranker._novelty_score("deploy_contract", "0xNewActor")
        self.assertGreater(score, 0.5)

    def test_novelty_known_actor(self):
        self.ranker.observe("deploy_contract", "0xKnown")
        score = self.ranker._novelty_score("deploy_contract", "0xKnown")
        self.assertEqual(score, 0.0)

    def test_composite_score_in_range(self):
        ev = FeedEvent(
            event_type="deploy_contract",
            actor="0x1234",
            value_usd=5000,
            timestamp=time.time(),
        )
        score = self.ranker.score(ev)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


# ── SocialFeedEngine ────────────────────────────────────────────────


class TestSocialFeedEngine(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.engine = SocialFeedEngine(self.db)

    def test_ingest_creates_event(self):
        ev = asyncio.run(self.engine.ingest(
            action="deploy_contract",
            actor="0x1234567890abcdef",
            detail={"chain": "base"},
            value_usd=500.0,
        ))
        self.assertEqual(ev.event_type, "deploy_contract")
        self.assertIn("0x1234", ev.summary)
        self.assertGreater(ev.ranked_score, 0)

    def test_ingest_persists(self):
        asyncio.run(self.engine.ingest(action="mint_nft", actor="0xABCD"))
        events = asyncio.run(self.engine.get_feed(limit=10))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "mint_nft")

    def test_get_feed_filters_by_type(self):
        asyncio.run(self.engine.ingest(action="mint_nft"))
        asyncio.run(self.engine.ingest(action="deploy_contract"))
        asyncio.run(self.engine.ingest(action="mint_nft"))

        nft_events = asyncio.run(self.engine.get_feed(event_type="mint_nft"))
        self.assertEqual(len(nft_events), 2)

    def test_get_feed_filters_by_actor(self):
        asyncio.run(self.engine.ingest(action="stake", actor="0xAlice"))
        asyncio.run(self.engine.ingest(action="stake", actor="0xBob"))

        alice = asyncio.run(self.engine.get_feed(actor="0xAlice"))
        self.assertEqual(len(alice), 1)

    def test_get_feed_pagination(self):
        for i in range(5):
            asyncio.run(self.engine.ingest(action="vote", actor=f"0x{i:04x}"))

        page1 = asyncio.run(self.engine.get_feed(limit=2, offset=0))
        page2 = asyncio.run(self.engine.get_feed(limit=2, offset=2))
        self.assertEqual(len(page1), 2)
        self.assertEqual(len(page2), 2)
        ids_1 = {e.id for e in page1}
        ids_2 = {e.id for e in page2}
        self.assertTrue(ids_1.isdisjoint(ids_2))

    def test_get_trending(self):
        for _ in range(5):
            asyncio.run(self.engine.ingest(action="swap_tokens"))
        for _ in range(2):
            asyncio.run(self.engine.ingest(action="deploy_contract"))

        trending = asyncio.run(self.engine.get_trending(window_hours=1))
        self.assertGreater(len(trending), 0)
        self.assertEqual(trending[0]["event_type"], "swap_tokens")
        self.assertEqual(trending[0]["count"], 5)

    def test_get_actor_feed(self):
        asyncio.run(self.engine.ingest(action="mint_nft", actor="0xAlice"))
        asyncio.run(self.engine.ingest(action="stake", actor="0xAlice"))
        asyncio.run(self.engine.ingest(action="vote", actor="0xBob"))

        feed = asyncio.run(self.engine.get_actor_feed("0xAlice"))
        self.assertEqual(len(feed), 2)

    def test_get_stats(self):
        asyncio.run(self.engine.ingest(action="deploy_contract", actor="0xA"))
        asyncio.run(self.engine.ingest(action="mint_nft", actor="0xB"))
        asyncio.run(self.engine.ingest(action="deploy_contract", actor="0xA"))

        stats = asyncio.run(self.engine.get_stats())
        self.assertEqual(stats["total_events"], 3)
        self.assertEqual(stats["unique_actors"], 2)
        self.assertEqual(stats["unique_action_types"], 2)
        self.assertIsNotNone(stats["most_active_actor"])
        self.assertEqual(stats["most_active_actor"]["address"], "0xA")

    def test_prune_respects_cap(self):
        # Use a smaller cap for test speed
        original_cap = MAX_FEED_EVENTS
        import runtime.social.feed_engine as mod
        mod.MAX_FEED_EVENTS = 5
        try:
            for i in range(8):
                asyncio.run(self.engine.ingest(action="vote", actor=f"0x{i:04x}"))

            all_events = asyncio.run(self.engine.get_feed(limit=100))
            self.assertLessEqual(len(all_events), 5)
        finally:
            mod.MAX_FEED_EVENTS = original_cap

    def test_ingest_never_raises(self):
        """ingest() should swallow errors and return a bare FeedEvent."""
        # Corrupt the DB to force an error
        self.db._conn.close()
        ev = asyncio.run(self.engine.ingest(action="crash_test"))
        self.assertEqual(ev.event_type, "crash_test")

    def test_min_score_filter(self):
        # Ingest events with known different scores
        asyncio.run(self.engine.ingest(
            action="deploy_contract", actor="0xHigh", value_usd=50000
        ))
        asyncio.run(self.engine.ingest(action="vote", actor="0xLow"))

        high = asyncio.run(self.engine.get_feed(min_score=0.5))
        all_ev = asyncio.run(self.engine.get_feed(min_score=0.0))
        self.assertLessEqual(len(high), len(all_ev))


# ── FeedFormatter ────────────────────────────────────────────────────


class TestFeedFormatter(unittest.TestCase):
    def test_icon_known_action(self):
        self.assertEqual(FeedFormatter.icon("deploy_contract"), "\U0001f4dc")
        self.assertEqual(FeedFormatter.icon("swap_tokens"), "\U0001f504")

    def test_icon_unknown_action(self):
        self.assertEqual(FeedFormatter.icon("unknown_xyz"), "\u26a1")

    def test_colour_high_score(self):
        self.assertEqual(FeedFormatter.colour(0.9), "#00ff41")

    def test_colour_low_score(self):
        self.assertEqual(FeedFormatter.colour(0.1), "#444444")

    def test_category_known(self):
        self.assertEqual(FeedFormatter.category("swap_tokens"), "DeFi")
        self.assertEqual(FeedFormatter.category("mint_nft"), "NFT")
        self.assertEqual(FeedFormatter.category("vote"), "Governance")

    def test_category_unknown(self):
        self.assertEqual(FeedFormatter.category("unknown_action"), "Other")

    def test_time_ago_just_now(self):
        result = FeedFormatter.time_ago(time.time())
        self.assertIn("just now", result)

    def test_time_ago_minutes(self):
        result = FeedFormatter.time_ago(time.time() - 300)
        self.assertIn("m ago", result)

    def test_time_ago_hours(self):
        result = FeedFormatter.time_ago(time.time() - 7200)
        self.assertIn("h ago", result)

    def test_format_event_adds_presentation(self):
        ev = FeedEvent(
            event_type="mint_nft",
            actor="0xTest",
            summary="minted",
            timestamp=time.time(),
            ranked_score=0.7,
        )
        formatted = FeedFormatter.format_event(ev)
        self.assertIn("icon", formatted)
        self.assertIn("colour", formatted)
        self.assertIn("category", formatted)
        self.assertIn("time_ago", formatted)
        self.assertEqual(formatted["category"], "NFT")

    def test_format_feed_returns_list(self):
        events = [
            FeedEvent(event_type="stake", timestamp=time.time()),
            FeedEvent(event_type="vote", timestamp=time.time()),
        ]
        result = FeedFormatter.format_feed(events)
        self.assertEqual(len(result), 2)
        self.assertTrue(all("icon" in r for r in result))


# ── Action labels coverage ───────────────────────────────────────────


class TestActionLabels(unittest.TestCase):
    def test_all_icons_have_labels(self):
        for action in ICONS:
            self.assertIn(action, ACTION_LABELS,
                          f"Icon defined for {action} but no ACTION_LABEL")

    def test_all_category_actions_have_labels(self):
        for cat, actions in CATEGORIES.items():
            for action in actions:
                self.assertIn(action, ACTION_LABELS,
                              f"Category {cat} lists {action} but no ACTION_LABEL")


if __name__ == "__main__":
    unittest.main()
