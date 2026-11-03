"""A weight that is not a number must be refused, not carried into the ranking.

`FeedWeights.validate()` is the only gate between operator config and the
scoring core, and every one of its guards was a comparison: `< 0`, `<= 0`,
`< 1`. NaN answers False to all of them, so a `NaN` literal in
`feed_ranker.*` — which Python's own json parser accepts — passed validation
and reached the scorer. What it did there is not a crash:

  • a NaN signal weight makes every score NaN, and the score sort
    (`feed_ranker.rank_for_you`) then orders by nothing at all;
  • a NaN `engagement_ceiling` makes `min(raw, ceiling)` return `raw`, which
    silently REMOVES the ceiling the module names as an invariant;
  • a NaN `max_posts_per_author` makes `max_per_author >= 1` False, which
    silently DISABLES the author-diversity cap inside For You — the one
    control the module calls HARD.

So the failure mode is a guarantee quietly switching off, not an error anyone
would see. These are the checks that say so.
"""

import math

import pytest

from runtime.social.feed_ranker import (
    FeedCandidate,
    FeedWeights,
    rank_for_you,
)

NOW = 1_000_000.0
NAN = float("nan")


def _c(cid, author, *, likes=0):
    return FeedCandidate(id=cid, author_id=author, created_at=NOW, likes=likes)


@pytest.mark.parametrize("field", ["recency", "engagement", "affinity", "discovery"])
def test_nan_signal_weight_is_refused(field):
    with pytest.raises(ValueError):
        FeedWeights(**{field: NAN}).validate()


@pytest.mark.parametrize(
    "field",
    ["recency_halflife_hours", "engagement_ceiling", "discovery_cap_fraction",
     "max_posts_per_author"],
)
def test_nan_bound_is_refused(field):
    with pytest.raises(ValueError):
        FeedWeights(**{field: NAN}).validate()


@pytest.mark.parametrize("field", ["recency", "engagement", "affinity", "discovery",
                                   "recency_halflife_hours", "engagement_ceiling",
                                   "discovery_cap_fraction"])
def test_infinite_weight_is_refused(field):
    # inf passes `< 0` / `<= 0` too, and an infinite weight makes every score
    # equal (inf), which is the same loss of ordering by another route.
    with pytest.raises(ValueError):
        FeedWeights(**{field: math.inf}).validate()


def test_nan_author_cap_does_not_silently_disable_author_diversity():
    # The concrete harm, stated as behaviour: one author floods a page and the
    # HARD per-author cap is the thing that is supposed to stop it. With a NaN
    # cap the comparison at the skip site is False and every post gets through.
    flood = [_c(f"p{i}", "0xspam", likes=100) for i in range(10)]
    with pytest.raises(ValueError):
        rank_for_you(
            flood,
            followed_author_ids=set(),
            now=NOW,
            weights=FeedWeights(max_posts_per_author=NAN),
            page_size=10,
        )


def test_nan_ceiling_does_not_silently_remove_the_engagement_ceiling():
    # `min(raw, nan)` returns raw, so the ceiling the module names as an
    # invariant stops existing. Refusing the config is what keeps it real.
    with pytest.raises(ValueError):
        rank_for_you(
            [_c("p1", "0xa", likes=10**6)],
            followed_author_ids=set(),
            now=NOW,
            weights=FeedWeights(engagement_ceiling=NAN),
            page_size=5,
        )


def test_finite_defaults_still_validate():
    # The gate must not become so strict that the shipped defaults fail it.
    FeedWeights().validate()
    FeedWeights(recency=0.0, discovery_cap_fraction=0.0).validate()
    FeedWeights(discovery_cap_fraction=1.0).validate()
