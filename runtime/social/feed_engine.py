"""
runtime/social/feed_engine.py
=============================

Live social feed engine for The Matrix — ranks, persists, and serves
blockchain activity events so every user sees what the platform is
doing in real time.

Architecture
------------

* **FeedEvent** — immutable value object representing a single action
  (deployment, swap, NFT mint, vote …).
* **FeedRankingEngine** — scores each event on four dimensions:
  recency (exponential decay), rarity (inverse frequency), value
  (log-scaled USD), and novelty (first-time actors or action types).
* **SocialFeedEngine** — SQLite-backed store with a 10 000 event cap.
  Exposes ``ingest()`` (fire-and-forget from the service dispatcher),
  paginated feed queries, trending aggregation, per-actor history,
  and global stats.

Ingest is designed to **never block the main request path**.  The
service dispatcher creates an ``asyncio.Task`` that calls
``SocialFeedEngine.ingest()``; if it fails or is slow the caller
is unaffected.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Maximum persisted events before pruning ──────────────────────────
MAX_FEED_EVENTS = 10_000

# ── Ranking weights ──────────────────────────────────────────────────
RECENCY_WEIGHT = 0.35
RARITY_WEIGHT = 0.25
VALUE_WEIGHT = 0.25
NOVELTY_WEIGHT = 0.15

# Recency half-life in seconds (1 hour → score ≈ 0.5)
RECENCY_HALF_LIFE = 3600.0

# ── Human-readable action labels ─────────────────────────────────────
ACTION_LABELS: Dict[str, str] = {
    # NEW-12: no label here narrates a deployment, and a test walks this table
    # to keep it that way (tests/test_feed_labels_and_value_ceiling_hold.py).
    #
    # The original reason given was "the platform cannot deploy". That is no
    # longer the reason, because it is no longer true: with
    # `conversion.auto_deploy` on, ContractConversionService compiles the
    # generated Solidity and broadcasts a constructor transaction with the
    # platform's own key. It is off by default and no shipped config turns it
    # on, and `smart_contracts.deploy` — the surface an agent could reach —
    # answers `not_implemented`. So the accurate statement is narrower and
    # still enough: the feed has no row for the one path that can deploy, and
    # `convert_contract` reads "converted a contract to blockchain", which
    # does not claim a deployment happened.
    #
    # `create_game` used to sit in this table as "deployed a blockchain game",
    # with an icon and a category behind it. No action by that name exists
    # anywhere in the platform, so it never rendered — a label one dispatcher
    # entry away from narrating a deployment is not an invariant, it is a
    # coincidence, and it has been removed from all three places.
    "swap_tokens": "swapped tokens",
    "add_liquidity": "added liquidity",
    "remove_liquidity": "removed liquidity",
    "mint_nft": "minted an NFT",
    "transfer_nft": "transferred an NFT",
    "create_collection": "created an NFT collection",
    "create_proposal": "created a DAO proposal",
    "vote": "voted on a proposal",
    "execute_proposal": "executed a proposal",
    "create_dao": "created a DAO",
    "stake": "staked tokens",
    "unstake": "unstaked tokens",
    # NEW-97: was "claimed staking rewards". Nothing is transferred — see
    # StakingService.claim_rewards, which now returns `recorded_unsettled`.
    #
    # AND THE LABEL WAS UNREACHABLE, WHICH I GOT WRONG FIRST TIME. `ingest` does
    # `ACTION_LABELS.get(action, f"performed {action}")` and the dispatcher
    # passes the ACTION name, "claim_staking_rewards", while this map is keyed
    # by the SERVICE METHOD name, "claim_rewards". The keys never met, so the
    # live feed emitted "performed claim_staking_rewards" and the false
    # sentence was never actually published. The danger was LATENT, not live:
    # repair the key mismatch with the old text in place and the false claim
    # goes live that day. Both keys are fixed so neither ordering can surface
    # it, and the action-keyed entry makes the honest sentence reachable now.
    "claim_rewards": "recorded a staking reward claim (not settled)",
    "claim_staking_rewards": "recorded a staking reward claim (not settled)",
    "send_payment": "sent a payment",
    "create_invoice": "created an invoice",
    "register_ip": "registered intellectual property",
    "create_license": "created a license agreement",
    "issue_badge": "issued a Glasswing badge",
    "verify_social": "verified a social profile",
    "create_social_profile": "created a social profile",
    "deploy_token": "launched a token",
    "bridge_assets": "bridged assets cross-chain",
    "request_loan": "requested a DeFi loan",
    "repay_loan": "repaid a DeFi loan",
    "create_insurance_policy": "created an insurance policy",
    "file_insurance_claim": "filed an insurance claim",
    "convert_contract": "converted a contract to blockchain",
    "register_supply_item": "registered a supply chain item",
    "verify_product": "verified a product's origin",
    "create_attestation": "created an on-chain attestation",
    "tokenize_asset": "tokenized a real-world asset",
    "list_security": "listed a tokenized security",
    "trade_security": "traded a tokenized security",
    "create_subscription": "created a subscription plan",
}


# ── Data model ───────────────────────────────────────────────────────


@dataclass
class FeedEvent:
    """A single social feed entry."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    event_type: str = ""
    actor: str = ""
    summary: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)
    component: Optional[int] = None
    tx_hash: Optional[str] = None
    value_usd: Optional[float] = None
    rarity_score: float = 0.0
    timestamp: float = field(default_factory=time.time)
    ranked_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> "FeedEvent":
        detail = row.get("detail") or "{}"
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except (json.JSONDecodeError, TypeError):
                detail = {}
        return cls(
            id=row["id"],
            event_type=row["event_type"],
            actor=row.get("actor", ""),
            summary=row.get("summary", ""),
            detail=detail,
            component=row.get("component"),
            tx_hash=row.get("tx_hash"),
            # 19-D: sanitised on READ too, so a row poisoned before
            # this fix cannot keep the feed unserialisable.
            value_usd=sanitize_value_usd(row.get("value_usd")),
            rarity_score=row.get("rarity_score", 0.0),
            timestamp=row.get("timestamp", 0.0),
            ranked_score=row.get("ranked_score", 0.0),
        )


# ── Ranking engine ───────────────────────────────────────────────────

#: 19-D. The declared ceiling for a single feed event's reported value. Not a
#: risk model — a bound, so one row cannot dominate a public ranking or a
#: `MAX(value_usd)` statistic. Values above it are recorded AT the ceiling and
#: flagged, never silently truncated to look ordinary.
_MAX_EVENT_VALUE_USD = 1_000_000_000.0

#: Where a clamped value announces itself. `sanitize_value_usd` ends in
#: `min(v, ceiling)`, which is a silent truncation — the exact thing the line
#: above says does not happen. `sanitize_value_usd_report` returns the value
#: AND whether it was clamped, so a caller that stores or renders the number
#: can say the reported figure was larger than the feed is willing to hold.
VALUE_CLAMPED_KEY = "value_usd_clamped"


def sanitize_value_usd(raw: Any) -> Optional[float]:
    """Coerce a reported event value into something a public feed can hold.

    19-D. `value_usd` arrives from `params[...]` — the request body — through
    `ServiceDispatcher`'s feed-ingest block, unvalidated and unbounded. Two
    measured consequences, both from an ordinary well-formed request:

      * `"Infinity"` is a PLAIN JSON STRING that `float()` accepts. Stored as
        `inf`, it makes the ENTIRE `/social/feed` response invalid JSON —
        `web.json_response` emits a bare `Infinity` token and `JSON.parse`
        fails. Not one row: the whole document, for every strict client
        (`web/social.html`, the MTRX Swift `JSONDecoder`). Unauthenticated,
        persistent, and it survives until the row is deleted.

      * The value drives `ranked_score`, which is computed at INGEST and stored,
        so the row keeps its position without ever being re-derived.

    APPLIED AT BOTH ENDS, deliberately. At ingest it stops new poison; at
    hydration it neutralises rows ALREADY stored, so the feed recovers without
    a migration. Sanitising only the writer would leave the feed permanently
    broken by anything written before the fix — and a fix that requires the
    attack not to have happened yet is not a fix.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None          # inf/-inf/nan are not values; they are not "zero" either
    if v < 0:
        return None
    return min(v, _MAX_EVENT_VALUE_USD)


def sanitize_value_usd_report(raw: Any) -> tuple[Optional[float], bool]:
    """:func:`sanitize_value_usd`, plus whether the ceiling actually bit.

    The comment above the ceiling says values over it are "flagged, never
    silently truncated", and `min()` truncates silently. A caller that wants to
    honour that sentence needs to know the difference between a row worth
    exactly a billion dollars and a row that claimed ten and was cut down to
    one, and the single return value could not tell it.
    """
    value = sanitize_value_usd(raw)
    if value is None:
        return None, False
    try:
        clamped = float(raw) > _MAX_EVENT_VALUE_USD
    except (TypeError, ValueError):
        clamped = False
    return value, clamped


class FeedRankingEngine:
    """Score events across four dimensions for feed ordering.

    Dimensions
    ----------
    1. **Recency** — exponential decay with a 1-hour half-life.
    2. **Rarity** — inverse frequency of the action type.
    3. **Value** — log-scaled USD amount (zero if no value).
    4. **Novelty** — bonus for first-time actors or actions.
    """

    def __init__(self) -> None:
        self._action_counts: Dict[str, int] = defaultdict(int)
        self._total_events: int = 0
        self._known_actors: set[str] = set()
        self._actor_actions: Dict[str, set[str]] = defaultdict(set)

    def observe(self, event_type: str, actor: str) -> None:
        """Record an event for frequency tracking without scoring."""
        self._action_counts[event_type] += 1
        self._total_events += 1
        self._known_actors.add(actor)
        self._actor_actions[actor].add(event_type)

    def score(self, event: FeedEvent) -> float:
        """Compute composite score in [0, 1]."""
        r = self._recency_score(event.timestamp)
        a = self._rarity_score(event.event_type)
        v = self._value_score(event.value_usd)
        n = self._novelty_score(event.event_type, event.actor)
        return (
            RECENCY_WEIGHT * r
            + RARITY_WEIGHT * a
            + VALUE_WEIGHT * v
            + NOVELTY_WEIGHT * n
        )

    # ── Dimension helpers ─────────────────────────────────────────

    @staticmethod
    def _recency_score(ts: float) -> float:
        """Exponential decay — 1.0 for now, 0.5 after one half-life."""
        age = max(0.0, time.time() - ts)
        return math.pow(0.5, age / RECENCY_HALF_LIFE)

    def _rarity_score(self, event_type: str) -> float:
        """Inverse frequency — rare actions score higher."""
        count = self._action_counts.get(event_type, 0)
        if self._total_events == 0 or count == 0:
            return 1.0  # never-seen actions are maximally rare
        frequency = count / self._total_events
        # Inverse log scale: rare = high, common = low
        return max(0.0, min(1.0, 1.0 - math.log1p(frequency * 10) / math.log(11)))

    @staticmethod
    def _value_score(value_usd: Optional[float]) -> float:
        """Log-scaled USD value, capped at 1.0 for ≥$100k."""
        if not value_usd or value_usd <= 0:
            return 0.0
        # log10(1) = 0 → 0.0;  log10(100_000) = 5 → 1.0
        return min(1.0, math.log10(max(1.0, value_usd)) / 5.0)

    def _novelty_score(self, event_type: str, actor: str) -> float:
        """Bonus for new actors and first-time action combinations."""
        score = 0.0
        if actor and actor not in self._known_actors:
            score += 0.6  # new actor
        if actor and event_type not in self._actor_actions.get(actor, set()):
            score += 0.4  # first time this actor does this action
        return min(1.0, score)


# ── Persistence & query engine ───────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS social_feed_events (
    id           TEXT PRIMARY KEY,
    event_type   TEXT NOT NULL,
    actor        TEXT NOT NULL DEFAULT '',
    summary      TEXT NOT NULL DEFAULT '',
    detail       TEXT NOT NULL DEFAULT '{}',
    component    INTEGER,
    tx_hash      TEXT,
    value_usd    REAL,
    rarity_score REAL NOT NULL DEFAULT 0,
    timestamp    REAL NOT NULL,
    ranked_score REAL NOT NULL DEFAULT 0
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_feed_ts ON social_feed_events (timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_feed_score ON social_feed_events (ranked_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_feed_actor ON social_feed_events (actor)",
    "CREATE INDEX IF NOT EXISTS idx_feed_type ON social_feed_events (event_type)",
]


class SocialFeedEngine:
    """SQLite-backed social activity feed.

    Parameters
    ----------
    db : runtime.db.database.Database
        Shared database handle (WAL mode, async write lock).
    """

    def __init__(self, db: Any) -> None:
        self._db = db
        self._ranker = FeedRankingEngine()
        self._table_ready = False
        self._init_lock: asyncio.Lock | None = None

    # ── Table bootstrap ───────────────────────────────────────────

    async def _ensure_table(self) -> None:
        if self._table_ready:
            return
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._table_ready:
                return
            await self._db.execute(_CREATE_TABLE)
            for idx_sql in _CREATE_INDEXES:
                await self._db.execute(idx_sql)
            # Seed the ranking engine from existing rows
            rows = await self._db.fetchall(
                "SELECT event_type, actor FROM social_feed_events"
            )
            for row in rows:
                self._ranker.observe(row["event_type"], row["actor"])
            self._table_ready = True

    # ── Ingest (fire-and-forget) ──────────────────────────────────

    async def ingest(
        self,
        action: str,
        actor: str = "",
        detail: Optional[Dict[str, Any]] = None,
        component: Optional[int] = None,
        tx_hash: Optional[str] = None,
        value_usd: Optional[float] = None,
    ) -> FeedEvent:
        """Persist and rank a new feed event.

        This method is designed to be called via
        ``asyncio.create_task(engine.ingest(...))``. It must never
        raise — all errors are logged and swallowed.
        """
        try:
            await self._ensure_table()

            summary = ACTION_LABELS.get(action, f"performed {action}")
            if actor:
                short_addr = f"{actor[:6]}…{actor[-4:]}" if len(actor) > 10 else actor
                summary = f"{short_addr} {summary}"

            # "Recorded AT the ceiling and FLAGGED, never silently truncated"
            # is what the ceiling's own comment promises. The flag rides in
            # `detail`, which is persisted with the row and travels with it to
            # every reader, so a number that was cut down says so instead of
            # looking like an ordinary billion. The caller's dict is copied —
            # ingest is fire-and-forget and must not mutate what it was handed.
            clean_value, clamped = sanitize_value_usd_report(value_usd)
            event_detail = dict(detail or {})
            if clamped:
                event_detail[VALUE_CLAMPED_KEY] = True
                logger.info(
                    "feed value for %s exceeded the ceiling and was recorded "
                    "at it", action)

            event = FeedEvent(
                event_type=action,
                actor=actor,
                summary=summary,
                detail=event_detail,
                component=component,
                tx_hash=tx_hash,
                value_usd=clean_value,
            )

            # Score before persisting
            event.rarity_score = self._ranker._rarity_score(action)
            event.ranked_score = self._ranker.score(event)

            # Observe after scoring so novelty works correctly
            self._ranker.observe(action, actor)

            await self._db.execute(
                """
                INSERT INTO social_feed_events
                    (id, event_type, actor, summary, detail, component,
                     tx_hash, value_usd, rarity_score, timestamp, ranked_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.event_type,
                    event.actor,
                    event.summary,
                    json.dumps(event.detail),
                    event.component,
                    event.tx_hash,
                    event.value_usd,
                    event.rarity_score,
                    event.timestamp,
                    event.ranked_score,
                ),
            )

            # Prune if we've grown past the cap
            count_row = await self._db.fetchone(
                "SELECT COUNT(*) AS cnt FROM social_feed_events"
            )
            if count_row and count_row["cnt"] > MAX_FEED_EVENTS:
                await self._prune()

            logger.info(
                "Feed event ingested: %s (score=%.3f)", action, event.ranked_score
            )
            return event

        except Exception:
            logger.exception("Failed to ingest feed event for action=%s", action)
            # Return a bare event so callers that await never crash
            return FeedEvent(event_type=action, actor=actor)

    # ── Queries ───────────────────────────────────────────────────

    async def get_feed(
        self,
        limit: int = 50,
        offset: int = 0,
        event_type: Optional[str] = None,
        component: Optional[int] = None,
        actor: Optional[str] = None,
        min_score: float = 0.0,
    ) -> List[FeedEvent]:
        """Return ranked feed events with optional filters."""
        await self._ensure_table()

        clauses: list[str] = []
        params: list[Any] = []

        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if component is not None:
            clauses.append("component = ?")
            params.append(component)
        if actor:
            clauses.append("actor = ?")
            params.append(actor)
        if min_score > 0:
            clauses.append("ranked_score >= ?")
            params.append(min_score)

        # Not injectable: `clauses` holds only the literal strings appended above,
        # each carrying a `?` placeholder, and every caller-supplied value goes to
        # `params`. The f-string interpolates the fixed clause text, never a value.
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""  # nosec B608
        params.extend([limit, offset])

        # Assembled on one line so the scanner has somewhere to read the reason:
        # the only interpolation is `where`, built above from literal clause text,
        # and every caller-supplied value travels in `params` as a `?` parameter.
        sql = (
            "SELECT * FROM social_feed_events "  # nosec B608 — `where` is literal clause text; values are `?` params
            + where
            + " ORDER BY ranked_score DESC, timestamp DESC LIMIT ? OFFSET ?"
        )  # nosec B608
        rows = await self._db.fetchall(sql, tuple(params))
        return [FeedEvent.from_row(dict(r)) for r in rows]

    async def get_trending(self, window_hours: int = 24) -> List[Dict[str, Any]]:
        """Aggregate trending actions over the given time window.

        `MAX(value_usd)` reads the stored column in SQL, so it passed through
        neither the ingest sanitiser nor the hydration one. A row written
        before those landed — or any row at all, if a future writer forgets —
        was still the maximum, which made this statistic the one place the
        ceiling did not reach and the one the ceiling was written to protect.
        The bound is applied in the query, so the answer is bounded whatever
        the table holds.
        """
        await self._ensure_table()

        cutoff = time.time() - (window_hours * 3600)
        rows = await self._db.fetchall(
            """
            SELECT event_type,
                   COUNT(*)            AS count,
                   AVG(ranked_score)   AS avg_score,
                   MIN(MAX(value_usd), ?) AS max_value,
                   COUNT(DISTINCT actor) AS unique_actors
            FROM social_feed_events
            WHERE timestamp >= ?
            GROUP BY event_type
            ORDER BY count DESC
            LIMIT 20
            """,
            (_MAX_EVENT_VALUE_USD, cutoff),
        )
        return [
            {
                "event_type": r["event_type"],
                "label": ACTION_LABELS.get(r["event_type"], r["event_type"]),
                "count": r["count"],
                "avg_score": round(r["avg_score"], 3),
                "max_value_usd": r["max_value"],
                "unique_actors": r["unique_actors"],
            }
            for r in rows
        ]

    async def get_actor_feed(
        self, wallet: str, limit: int = 50
    ) -> List[FeedEvent]:
        """Return recent events for a specific wallet address."""
        return await self.get_feed(limit=limit, actor=wallet)

    async def get_stats(self) -> Dict[str, Any]:
        """Global feed statistics."""
        await self._ensure_table()

        total = await self._db.fetchone(
            "SELECT COUNT(*) AS cnt FROM social_feed_events"
        )
        unique_actors = await self._db.fetchone(
            "SELECT COUNT(DISTINCT actor) AS cnt FROM social_feed_events"
        )
        unique_types = await self._db.fetchone(
            "SELECT COUNT(DISTINCT event_type) AS cnt FROM social_feed_events"
        )
        last_24h = await self._db.fetchone(
            "SELECT COUNT(*) AS cnt FROM social_feed_events WHERE timestamp >= ?",
            (time.time() - 86400,),
        )
        avg_score = await self._db.fetchone(
            "SELECT AVG(ranked_score) AS avg FROM social_feed_events"
        )
        top_actor = await self._db.fetchone(
            """
            SELECT actor, COUNT(*) AS cnt
            FROM social_feed_events
            WHERE actor != ''
            GROUP BY actor
            ORDER BY cnt DESC
            LIMIT 1
            """
        )

        return {
            "total_events": total["cnt"] if total else 0,
            "unique_actors": unique_actors["cnt"] if unique_actors else 0,
            "unique_action_types": unique_types["cnt"] if unique_types else 0,
            "events_last_24h": last_24h["cnt"] if last_24h else 0,
            "avg_score": round((avg_score["avg"] or 0.0), 3) if avg_score else 0.0,
            "most_active_actor": (
                {"address": top_actor["actor"], "event_count": top_actor["cnt"]}
                if top_actor and top_actor["actor"]
                else None
            ),
        }

    # ── Maintenance ───────────────────────────────────────────────

    async def _prune(self) -> None:
        """Delete oldest events beyond the cap."""
        await self._db.execute(
            """
            DELETE FROM social_feed_events
            WHERE id NOT IN (
                SELECT id FROM social_feed_events
                ORDER BY timestamp DESC
                LIMIT ?
            )
            """,
            (MAX_FEED_EVENTS,),
        )
        logger.info("Pruned social feed to %d events", MAX_FEED_EVENTS)
