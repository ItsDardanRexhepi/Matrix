"""Two feed invariants that were stated in one place and broken in another.

NEW-12, written into both feed modules: "no deploy_contract label — the
platform cannot deploy, so no feed row may ever narrate one", and "no
deploy_contract icon — the feed can never render a deployment".
`deploy_contract` was indeed removed. `create_game` was not, and its label is
the word the invariant forbids: "deployed a blockchain game", with a 🎮 icon
and a Gaming category to render it in. It was latent — no action named
`create_game` exists anywhere in the platform — and a label that is one
dispatcher entry away from narrating a deployment is not an invariant, it is a
coincidence.

19-D, written above the value ceiling: the bound exists "so one row cannot
dominate a public ranking or a `MAX(value_usd)` statistic", and values above it
are "recorded AT the ceiling and flagged, never silently truncated". Both
halves were false where it counts:

  * `get_trending` runs `MAX(value_usd)` over the stored column in SQL. It
    passes through neither the ingest sanitiser nor the hydration one, so a row
    written before the fix — `Infinity`, or 1e18 — is still the maximum, and
    the statistic the ceiling was built to protect is the one place it does not
    reach;
  * `sanitize_value_usd` ends in `return min(v, _MAX_EVENT_VALUE_USD)`. That is
    a silent truncation, and the sentence directly above it says values are
    flagged instead. Nothing anywhere carried a flag.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from runtime.social.feed_engine import (
    ACTION_LABELS,
    SocialFeedEngine,
    _MAX_EVENT_VALUE_USD,
    sanitize_value_usd,
)
from runtime.social.feed_formatter import CATEGORIES, ICONS


class _DB:
    """Same minimal shape tests/test_feed_engine.py already uses."""

    def __init__(self):
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row

    async def execute(self, sql, params=None):
        self._conn.execute(sql, params or ())
        self._conn.commit()

    async def executemany(self, sql, seq):
        self._conn.executemany(sql, seq)
        self._conn.commit()

    async def fetchall(self, sql, params=None):
        return self._conn.execute(sql, params or ()).fetchall()

    async def fetchone(self, sql, params=None):
        return self._conn.execute(sql, params or ()).fetchone()


# ── no feed row narrates a deployment ───────────────────────────────────────

_DEPLOY_WORDS = ("deploy", "deployed", "deployment")


def test_no_action_label_narrates_a_deployment():
    offenders = {
        action: label for action, label in ACTION_LABELS.items()
        if any(w in label.lower() for w in _DEPLOY_WORDS)
    }
    assert offenders == {}, (
        f"these labels narrate a deployment: {offenders}")


def test_no_icon_or_category_survives_a_removed_label():
    # A label, an icon and a category are three places one action is written
    # down. Deleting one and leaving the others is how a removed row comes back.
    assert set(ICONS) <= set(ACTION_LABELS), (
        f"icons with no label: {set(ICONS) - set(ACTION_LABELS)}")
    categorised = {a for actions in CATEGORIES.values() for a in actions}
    assert categorised <= set(ACTION_LABELS), (
        f"categorised actions with no label: {categorised - set(ACTION_LABELS)}")


# ── the value ceiling reaches the statistic it was built for ────────────────

def test_a_value_above_the_ceiling_is_flagged_not_just_clamped():
    from runtime.social.feed_engine import sanitize_value_usd_report

    value, clamped = sanitize_value_usd_report(_MAX_EVENT_VALUE_USD * 10)
    assert value == _MAX_EVENT_VALUE_USD
    assert clamped is True, "a truncated value reported nothing about it"

    value, clamped = sanitize_value_usd_report(5.0)
    assert (value, clamped) == (5.0, False)


def test_sanitize_still_refuses_what_is_not_a_value():
    assert sanitize_value_usd(float("inf")) is None
    assert sanitize_value_usd(float("nan")) is None
    assert sanitize_value_usd(-1) is None
    assert sanitize_value_usd("Infinity") is None
    assert sanitize_value_usd(True) is None
    assert sanitize_value_usd(12.5) == 12.5


@pytest.mark.asyncio
async def test_trending_max_value_is_bounded_even_for_a_poisoned_row():
    # The row is written straight to the table, which is exactly how a row
    # written before the sanitiser landed still sits there today.
    db = _DB()
    engine = SocialFeedEngine(db)
    await engine._ensure_table()
    now = time.time()
    for i, value in enumerate((1.0, 1e30)):
        await db.execute(
            "INSERT INTO social_feed_events (id, event_type, actor, summary, "
            "detail, component, tx_hash, value_usd, rarity_score, timestamp, "
            "ranked_score) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f"e{i}", "swap_tokens", "0xa", "swapped tokens", "{}", None,
             None, value, 0.0, now, 0.5),
        )

    trending = await engine.get_trending(window_hours=24)
    row = next(r for r in trending if r["event_type"] == "swap_tokens")
    assert row["max_value_usd"] <= _MAX_EVENT_VALUE_USD, (
        f"MAX(value_usd) answered {row['max_value_usd']} — the ceiling does not "
        "reach the statistic it was written to protect")


@pytest.mark.asyncio
async def test_an_ingested_over_ceiling_value_carries_its_flag_to_the_row():
    # CONNECTED, NOT MERELY PRESENT: the report helper is reached from ingest,
    # and what it reports survives into the stored row rather than staying a
    # return value nobody reads.
    from runtime.social.feed_engine import VALUE_CLAMPED_KEY

    db = _DB()
    engine = SocialFeedEngine(db)
    caller_detail = {"pair": "ETH/USDC"}
    event = await engine.ingest(
        "swap_tokens", actor="0xabc", detail=caller_detail,
        value_usd=_MAX_EVENT_VALUE_USD * 10,
    )
    assert event.value_usd == _MAX_EVENT_VALUE_USD
    assert event.detail.get(VALUE_CLAMPED_KEY) is True
    assert caller_detail == {"pair": "ETH/USDC"}, "ingest mutated the caller's dict"

    row = await db.fetchone(
        "SELECT detail FROM social_feed_events WHERE id = ?", (event.id,))
    assert VALUE_CLAMPED_KEY in row["detail"], "the flag did not reach the row"


@pytest.mark.asyncio
async def test_an_ordinary_value_carries_no_flag():
    from runtime.social.feed_engine import VALUE_CLAMPED_KEY

    engine = SocialFeedEngine(_DB())
    event = await engine.ingest("swap_tokens", actor="0xabc", value_usd=42.0)
    assert event.value_usd == 42.0
    assert VALUE_CLAMPED_KEY not in event.detail
