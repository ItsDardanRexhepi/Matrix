"""`feed_ranker.latest()` is named as the Latest tab AND the ranking fallback.

The module's own invariant list says so — "`latest()` is the chronological feed
used both for the 'Latest' tab AND whenever ranking cannot run". Nothing called
it. `SocialService.get_feed` sorted its own list on the way out, and the
ranking fallback fell into that same private sort, so the function that carries
the guarantee was a public definition with no production caller: the guarantee
was a sentence about code nothing ran.

The two orders were also not the same order. `latest()` breaks ties by post id,
which is what makes the feed reproducible; the service's sort had no tie-break
at all, so two posts sharing a timestamp came back in whatever order they
happened to sit in the store. That difference is observable, and these checks
are what observe it.
"""

import pytest

from runtime.blockchain.services.social.service import SocialService
from runtime.social import feed_ranker


async def _svc(viewer="0xme", authors=("0xa",), follows=("0xa",)):
    svc = SocialService()
    await svc.create_profile(viewer, "Viewer", "")
    for a in authors:
        await svc.create_profile(a, a.upper(), "")
    for a in follows:
        await svc.follow_wallet(viewer, a)
    return svc


async def _tied_pair(svc):
    """Two posts on the SAME timestamp, stored newest-id-first.

    Insertion order and id order disagree, so a sort with no tie-break returns
    insertion order and a sort that breaks ties by id returns id order. That is
    the whole difference, made visible.
    """
    later = await svc.publish_post("0xa", "z")
    earlier = await svc.publish_post("0xa", "a")
    later["id"], earlier["id"] = "zzz_post", "aaa_post"
    later["published_at"] = earlier["published_at"] = 500.0
    return earlier, later


@pytest.mark.asyncio
async def test_latest_tab_breaks_ties_by_id():
    svc = await _svc()
    earlier, later = await _tied_pair(svc)
    ids = [svc._item_id(i) for i in await svc.get_feed("0xme", mode="latest")]
    assert ids == ["aaa_post", "zzz_post"], (
        "Latest must be the deterministic order latest() defines, not the "
        f"order the store happens to hold: {ids}")


@pytest.mark.asyncio
async def test_ranking_fallback_breaks_ties_by_id_too():
    # A ranker that cannot run is the documented fallback path. It must land on
    # the SAME chronological order the Latest tab serves — one implementation,
    # not two that drift.
    svc = await _svc()
    earlier, later = await _tied_pair(svc)
    svc.config["feed_ranker"] = {"max_posts_per_author": 0}  # validate() raises
    ids = [svc._item_id(i) for i in await svc.get_feed("0xme", mode="for_you")]
    assert ids == ["aaa_post", "zzz_post"], (
        f"the for_you fallback did not serve the Latest order: {ids}")


@pytest.mark.asyncio
async def test_the_fallback_is_not_dressed_up_as_for_you():
    # A ranked item carries its score and its per-signal breakdown. The
    # fallback is chronological and carries neither, so a caller can tell which
    # one it got from the item itself rather than from a label.
    svc = await _svc()
    await _tied_pair(svc)
    svc.config["feed_ranker"] = {"max_posts_per_author": 0}
    fallback = await svc.get_feed("0xme", mode="for_you")
    assert fallback and all("_rank_score" not in it for it in fallback)

    svc.config["feed_ranker"] = {}
    ranked = await svc.get_feed("0xme", mode="for_you")
    assert ranked and all("_rank_score" in it for it in ranked)


@pytest.mark.asyncio
async def test_latest_has_a_production_caller():
    # CONNECTED, NOT MERELY PRESENT. The guarantee lives in latest(); if the
    # service stops calling it, the guarantee goes back to being prose.
    calls = []
    real = feed_ranker.latest

    def spy(candidates):
        out = real(candidates)
        calls.append(len(out))
        return out

    feed_ranker.latest = spy
    try:
        svc = await _svc()
        await _tied_pair(svc)
        await svc.get_feed("0xme", mode="latest")
    finally:
        feed_ranker.latest = real
    assert calls, "get_feed(mode='latest') did not reach feed_ranker.latest()"
