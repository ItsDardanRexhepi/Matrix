"""Transparent, config-tunable social-feed ranker (v1 — NO ML, NO per-user learning).

This is the "For You" scoring core. It is deliberately a pure function of a small,
explicitly-named set of signals, with every weight living in one dataclass
(`FeedWeights`) so the ranking is fully explainable and operator-tunable. There is
NO machine learning and NO per-user model anywhere in v1 — the only personalization
is the transparent, symmetric "do you follow this author" signal, which the viewer
already controls by following/unfollowing.

Design invariants (enforced + tested):
  • Privacy absolute — the ranker NEVER sees private/confidential content. Callers
    MUST filter the candidate set to publicly-visible posts before ranking; the
    ranker reads only the fields on `FeedCandidate` (id, author, created_at, likes,
    comments) and nothing else. There is no code path here that can reach a
    visibility flag, DM, or private post.
  • Deterministic — same inputs → same output. Ties break by post id.
  • Engagement ceiling — the engagement term is capped so one viral post cannot
    dominate the ranking; recency/affinity still decide order among high-engagement
    posts.
  • Discovery cap — a HARD per-page ceiling: at most `discovery_cap_fraction` of a
    page comes from authors the viewer does NOT follow (default 20%). When followed
    content can't fill the page, the page is SHORTER — it is never backfilled with
    strangers. This is what stops a flood of high-engagement non-followed posts from
    dominating (the "cap bypass" the ranker must resist); the excess isn't lost, it
    surfaces on a larger page / next page.
  • Author diversity — a HARD cap (every mode, incl. cold-start): no single author
    may occupy more than `max_posts_per_author` slots on a page. This stops one
    account (viral or spamming) from owning a page even when there is no follow
    signal to lean on. It bounds per-account dominance, NOT distinct-account (Sybil)
    collusion — that is an identity-layer concern a ranker cannot solve.
  • Cold-start — a viewer who follows no one has an all-discovery feed (the follow-
    based discovery cap is lifted, since "followed" is empty by definition) ranked by
    recency + engagement, still author-diversity-capped and bounded by page size.
  • Honest fallback — `latest()` is the chronological feed used both for the
    "Latest" tab AND whenever ranking cannot run; it is never dressed up as "For You".

See FEED_ALGORITHM.md (generated from this module) for the operator-facing spec.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class FeedWeights:
    """Every knob that shapes ranking, in one place. Operator-tunable via config;
    changing these changes the feed transparently — no retraining, no hidden state."""

    # Relative weights of the four signals (the linear score is their weighted sum).
    recency: float = 1.0
    engagement: float = 0.6
    affinity: float = 0.9
    discovery: float = 0.4

    # Recency: exponential time-decay. A post loses half its recency term every
    # `recency_halflife_hours`. 6h ≈ a lively feed that still surfaces the last day.
    recency_halflife_hours: float = 6.0

    # Engagement: log1p(likes + comment_weight*comments), then CAPPED at
    # `engagement_ceiling` so a runaway-viral post can't swamp everything else.
    comment_weight: float = 2.0
    engagement_ceiling: float = 4.0

    # Discovery: at most this fraction of a page may come from non-followed authors.
    discovery_cap_fraction: float = 0.20

    # Author diversity: no single author may occupy more than this many slots on a
    # page — in EVERY mode, including cold-start. This is what stops one account
    # (viral or spamming) from owning a page even when there is no follow signal to
    # lean on (a brand-new viewer). It limits per-account dominance; it cannot solve
    # distinct-account (Sybil) collusion, which is an identity-layer concern.
    max_posts_per_author: int = 3

    def validate(self) -> None:
        for name in ("recency", "engagement", "affinity", "discovery"):
            if getattr(self, name) < 0:
                raise ValueError(f"weight {name} must be >= 0")
        if not (0.0 <= self.discovery_cap_fraction <= 1.0):
            raise ValueError("discovery_cap_fraction must be in [0,1]")
        if self.recency_halflife_hours <= 0:
            raise ValueError("recency_halflife_hours must be > 0")
        if self.engagement_ceiling <= 0:
            raise ValueError("engagement_ceiling must be > 0")
        if self.max_posts_per_author < 1:
            raise ValueError("max_posts_per_author must be >= 1")


@dataclass(frozen=True)
class FeedCandidate:
    """A publicly-visible post, normalized to exactly the fields the ranker may read.
    The caller builds these AFTER privacy filtering — private content never becomes a
    FeedCandidate, so it structurally cannot enter any feed."""

    id: str
    author_id: str
    created_at: float           # epoch seconds
    likes: int = 0
    comments: int = 0


@dataclass(frozen=True)
class RankedItem:
    id: str
    author_id: str
    score: float
    # Per-signal contribution, for transparency/debugging (surfaced to no user secret).
    breakdown: dict = field(default_factory=dict)
    followed: bool = False


def _recency_term(age_hours: float, halflife_hours: float) -> float:
    if age_hours <= 0:
        return 1.0
    return 0.5 ** (age_hours / halflife_hours)


def _engagement_term(likes: int, comments: int, weights: FeedWeights) -> float:
    raw = math.log1p(max(0, likes) + weights.comment_weight * max(0, comments))
    return min(raw, weights.engagement_ceiling)


def score_candidate(
    c: FeedCandidate,
    *,
    followed: bool,
    now: float,
    weights: FeedWeights,
) -> RankedItem:
    """Pure per-post score. Exposed for tests + transparency; no side effects."""
    age_hours = max(0.0, (now - c.created_at) / 3600.0)
    recency = _recency_term(age_hours, weights.recency_halflife_hours)
    engagement = _engagement_term(c.likes, c.comments, weights)
    affinity = 1.0 if followed else 0.0
    discovery = 0.0 if followed else 1.0

    score = (
        weights.recency * recency
        + weights.engagement * engagement
        + weights.affinity * affinity
        + weights.discovery * discovery
    )
    return RankedItem(
        id=c.id,
        author_id=c.author_id,
        score=score,
        followed=followed,
        breakdown={
            "recency": round(weights.recency * recency, 4),
            "engagement": round(weights.engagement * engagement, 4),
            "affinity": round(weights.affinity * affinity, 4),
            "discovery": round(weights.discovery * discovery, 4),
        },
    )


def latest(candidates: Iterable[FeedCandidate]) -> list[FeedCandidate]:
    """Chronological feed (newest first). This is the 'Latest' tab AND the honest
    fallback whenever ranking can't run. Deterministic: ties break by id."""
    return sorted(candidates, key=lambda c: (-c.created_at, c.id))


def rank_for_you(
    candidates: Iterable[FeedCandidate],
    *,
    followed_author_ids: set[str],
    now: float,
    weights: FeedWeights | None = None,
    page_size: int | None = None,
) -> list[RankedItem]:
    """Rank publicly-visible candidates for the 'For You' feed.

    `followed_author_ids`: the viewer's follow set (the ONLY personalization input).
    `page_size`: if given, the discovery cap is enforced against it; otherwise the
    cap is applied against the full result length.
    Cold-start (empty follow set) → all-discovery, recency+engagement ranked. The
    follow-based discovery cap is meaningless there (everything is discovery), but
    the author-diversity cap STILL applies, so no single account can own the page.
    """
    weights = weights or FeedWeights()
    weights.validate()

    cand = list(candidates)
    scored = [
        score_candidate(c, followed=(c.author_id in followed_author_ids), now=now, weights=weights)
        for c in cand
    ]
    # Deterministic order: score desc, then newest, then id. (created_at looked up
    # via a stable map so equal scores still resolve identically every run.)
    created = {c.id: c.created_at for c in cand}
    scored.sort(key=lambda r: (-r.score, -created[r.id], r.id))

    n = page_size if page_size else len(scored)
    # Cold-start (viewer follows no one): all-discovery, so the follow-based discovery
    # cap is meaningless — disable it (max_discovery=None). The author-diversity cap
    # STILL applies, so no single account can own even a brand-new viewer's page.
    if not followed_author_ids:
        return _assemble_page(scored, page_size=n, max_discovery=None,
                              max_per_author=weights.max_posts_per_author)

    max_discovery = int(weights.discovery_cap_fraction * n)
    return _assemble_page(scored, page_size=n, max_discovery=max_discovery,
                          max_per_author=weights.max_posts_per_author)


def _assemble_page(
    ranked: list[RankedItem],
    *,
    page_size: int,
    max_discovery: int | None,
    max_per_author: int,
) -> list[RankedItem]:
    """Greedily assemble ONE page from score-sorted `ranked`, enforcing HARD per-page
    caps by SKIPPING (never backfilling) any item that would exceed a cap:

      • at most `max_discovery` non-followed ('discovery') items — `None` disables this
        cap (cold-start, where everything is discovery);
      • at most `max_per_author` items from any single author — in EVERY mode.

    Because over-cap items are skipped rather than pushed into empty slots, neither a
    flood of stranger posts NOR a flood from one account can dominate: the page is
    simply shorter when there isn't enough diverse/eligible content. Skipped items are
    not destroyed — a larger `page_size` surfaces more of them."""
    if page_size <= 0:
        return []
    page: list[RankedItem] = []
    discovery_used = 0
    author_counts: dict[str, int] = {}
    for item in ranked:
        if len(page) >= page_size:
            break
        if max_per_author >= 1 and author_counts.get(item.author_id, 0) >= max_per_author:
            continue  # one author can't stack the page
        if (not item.followed) and (max_discovery is not None) and discovery_used >= max_discovery:
            continue  # discovery cap reached — skip, do NOT backfill
        page.append(item)
        author_counts[item.author_id] = author_counts.get(item.author_id, 0) + 1
        if not item.followed:
            discovery_used += 1
    return page
