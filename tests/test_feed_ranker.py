"""Transparent feed ranker (runtime/social/feed_ranker.py) — unit + adversarial gates.

This locks the v1 guarantees the brief demands, as executable checks:
  • recency decays by half-life, engagement is CAPPED (one viral post can't dominate),
    affinity boosts followed authors, discovery is a distinct signal;
  • the discovery cap can't be bypassed by flooding high-scoring non-followed posts
    (overflow is pushed to the tail, never dropped);
  • cold-start (no follows) is an all-discovery, uncapped, recency/engagement feed;
  • `latest()` is deterministic chronological (the honest 'Latest' tab + fallback);
  • the ranker is structurally blind to any signal beyond the 5 public FeedCandidate
    fields — there is no code path to a visibility flag, DM, or private post.
"""

import math

import pytest

from runtime.social.feed_ranker import (
    FeedCandidate,
    FeedWeights,
    RankedItem,
    _assemble_page,
    _engagement_term,
    _recency_term,
    latest,
    rank_for_you,
    score_candidate,
)

NOW = 1_000_000.0
HOUR = 3600.0


def _c(cid, author, *, age_hours=0.0, likes=0, comments=0):
    return FeedCandidate(
        id=cid,
        author_id=author,
        created_at=NOW - age_hours * HOUR,
        likes=likes,
        comments=comments,
    )


# ── recency ────────────────────────────────────────────────────────────────

def test_recency_halves_every_halflife():
    assert _recency_term(0.0, 6.0) == 1.0
    assert _recency_term(6.0, 6.0) == pytest.approx(0.5)
    assert _recency_term(12.0, 6.0) == pytest.approx(0.25)


def test_recency_future_or_zero_age_is_full():
    # Clock skew / future timestamps must not produce >1 or negative terms.
    assert _recency_term(-5.0, 6.0) == 1.0


# ── engagement ceiling (one viral post can't dominate) ──────────────────────

def test_engagement_is_capped_at_ceiling():
    w = FeedWeights()
    raw = math.log1p(1_000_000)
    assert raw > w.engagement_ceiling
    assert _engagement_term(1_000_000, 0, w) == w.engagement_ceiling


def test_viral_post_cannot_run_away():
    # ADVERSARIAL: past the ceiling, more engagement adds ZERO score — so a single
    # viral post cannot dominate the ranking by racking up unbounded likes.
    w = FeedWeights()
    a = score_candidate(_c("a", "x", likes=1_000_000), followed=True, now=NOW, weights=w)
    b = score_candidate(_c("b", "x", likes=1_000_000_000), followed=True, now=NOW, weights=w)
    assert a.score == b.score


def test_comments_weigh_more_than_likes():
    w = FeedWeights()
    likes_only = _engagement_term(4, 0, w)
    with_comments = _engagement_term(0, 2, w)  # 2 comments * weight 2.0 == 4
    assert with_comments == likes_only


# ── affinity vs discovery ───────────────────────────────────────────────────

def test_followed_outranks_equal_stranger():
    w = FeedWeights()
    followed = score_candidate(_c("f", "friend"), followed=True, now=NOW, weights=w)
    stranger = score_candidate(_c("s", "rando"), followed=False, now=NOW, weights=w)
    assert followed.score > stranger.score


def test_breakdown_sums_to_score():
    w = FeedWeights()
    r = score_candidate(_c("f", "friend", likes=3, comments=1), followed=True, now=NOW, weights=w)
    assert pytest.approx(sum(r.breakdown.values()), abs=1e-3) == round(r.score, 3)
    # affinity present, discovery zero for a followed post
    assert r.breakdown["affinity"] > 0
    assert r.breakdown["discovery"] == 0


# ── discovery cap (cannot be bypassed) ──────────────────────────────────────

def test_discovery_cap_is_a_hard_ceiling_no_flood():
    # ADVERSARIAL (cap bypass): 4 non-followed posts engineered to OUTSCORE 3 followed
    # posts. With page_size 5 and cap 0.2 → at most 1 discovery item may appear on the
    # page. The flood must NOT be backfilled into the empty slots; the page is shorter.
    w = FeedWeights()
    followed = {"f1", "f2", "f3"}
    cands = (
        [_c(f"f{i}", f"f{i}", likes=0) for i in range(1, 4)]
        + [_c(f"d{i}", f"d{i}", likes=1_000_000) for i in range(1, 5)]
    )
    page = rank_for_you(
        cands, followed_author_ids=followed, now=NOW, weights=w, page_size=5,
    )
    max_discovery = int(w.discovery_cap_fraction * 5)  # == 1
    assert sum(not r.followed for r in page) == max_discovery  # exactly the cap, no flood
    assert sum(r.followed for r in page) == 3                  # all followed content kept
    assert len(page) == 4                                       # shorter page, NOT backfilled


def test_capped_discovery_is_not_lost_on_a_larger_page():
    # The excess isn't destroyed: request a big page and every discovery item returns.
    w = FeedWeights()
    followed = {"f1"}
    cands = [_c("f1", "f1")] + [_c(f"d{i}", f"d{i}", likes=100) for i in range(1, 5)]
    big = rank_for_you(cands, followed_author_ids=followed, now=NOW, weights=w, page_size=100)
    assert {r.id for r in big} == {c.id for c in cands}  # nothing permanently dropped


def test_assemble_page_zero_page_is_empty():
    items = [RankedItem(id="a", author_id="x", score=1.0, followed=False)]
    assert _assemble_page(items, page_size=0, max_discovery=1, max_per_author=3) == []


# ── author diversity (no single account can own a page — every mode) ─────────

def test_author_diversity_caps_a_single_flooding_account_coldstart():
    # ADVERSARIAL: brand-new viewer (follows NO ONE). One attacker account floods 100
    # viral posts; 30 other authors post one modest post each. Even with the follow-
    # based discovery cap lifted (cold-start), the attacker must not own the page.
    w = FeedWeights()
    flood = [_c(f"atk{i}", "0xattacker", likes=1_000_000) for i in range(100)]
    others = [_c(f"o{i}", f"0xauthor{i}", likes=1) for i in range(30)]
    page = rank_for_you(
        flood + others, followed_author_ids=set(), now=NOW, weights=w, page_size=50,
    )
    attacker_slots = sum(1 for r in page if r.author_id == "0xattacker")
    assert attacker_slots <= w.max_posts_per_author  # capped at 3, NOT 50
    assert len({r.author_id for r in page}) >= 10     # a genuinely diverse page


def test_author_diversity_caps_a_single_account_with_follows():
    # Same cap applies when the viewer follows people: even a FOLLOWED author can't
    # monopolize the page by posting a hundred times.
    w = FeedWeights()
    flood = [_c(f"f{i}", "0xfriend", likes=10) for i in range(100)]
    page = rank_for_you(
        flood, followed_author_ids={"0xfriend"}, now=NOW, weights=w, page_size=50,
    )
    assert len(page) == w.max_posts_per_author  # 3 from the one author, page is short
    assert all(r.author_id == "0xfriend" for r in page)


# ── cold start ──────────────────────────────────────────────────────────────

def test_cold_start_is_all_discovery_uncapped():
    # A viewer who follows no one: the discovery cap is meaningless (everything is
    # discovery), so candidates are NOT suppressed — the full page comes back ranked
    # by recency + engagement (bounded only by page_size).
    w = FeedWeights()
    # equal engagement (0 likes) so recency alone decides the order
    cands = [_c(f"p{i}", f"a{i}", age_hours=i) for i in range(10)]
    ranked = rank_for_you(cands, followed_author_ids=set(), now=NOW, weights=w, page_size=10)
    assert len(ranked) == 10  # no discovery-cap suppression on cold start
    # newest post (age 0) leads on recency
    assert ranked[0].id == "p0"
    # and the page respects the requested size
    small = rank_for_you(cands, followed_author_ids=set(), now=NOW, weights=w, page_size=3)
    assert len(small) == 3


# ── latest (honest chronological) ───────────────────────────────────────────

def test_latest_is_chronological_newest_first():
    cands = [_c("old", "a", age_hours=10), _c("new", "b", age_hours=1), _c("mid", "c", age_hours=5)]
    order = [c.id for c in latest(cands)]
    assert order == ["new", "mid", "old"]


def test_latest_ties_break_by_id_deterministically():
    cands = [_c("b", "a"), _c("a", "a"), _c("c", "a")]  # identical timestamps
    order = [c.id for c in latest(cands)]
    assert order == ["a", "b", "c"]


# ── determinism ─────────────────────────────────────────────────────────────

def test_ranking_is_deterministic():
    w = FeedWeights()
    cands = [_c(f"p{i}", f"a{i % 3}", age_hours=i % 4, likes=i) for i in range(20)]
    followed = {"a0"}
    first = rank_for_you(cands, followed_author_ids=followed, now=NOW, weights=w, page_size=10)
    second = rank_for_you(cands, followed_author_ids=followed, now=NOW, weights=w, page_size=10)
    assert [r.id for r in first] == [r.id for r in second]


# ── weight validation ───────────────────────────────────────────────────────

def test_weight_validation_rejects_bad_config():
    with pytest.raises(ValueError):
        FeedWeights(recency=-1).validate()
    with pytest.raises(ValueError):
        FeedWeights(discovery_cap_fraction=1.5).validate()
    with pytest.raises(ValueError):
        FeedWeights(recency_halflife_hours=0).validate()
    with pytest.raises(ValueError):
        FeedWeights(engagement_ceiling=0).validate()


# ── structural privacy: the ranker cannot read a hidden signal ──────────────

def test_candidate_exposes_only_public_fields():
    # ADVERSARIAL (hidden-signal leakage): FeedCandidate is the ranker's ONLY input
    # surface. If a field beyond these five ever appears, ranking could depend on a
    # signal the privacy review never vetted — this test fails the moment that happens.
    fields = set(FeedCandidate.__dataclass_fields__)
    assert fields == {"id", "author_id", "created_at", "likes", "comments"}
