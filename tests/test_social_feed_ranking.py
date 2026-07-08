"""Server-side feed ranking through SocialService.get_feed (the seam-crossing path
the iOS client calls: GET /api/v1/social/feed/{wallet}).

Proves the ranker is wired correctly AND privacy is absolute in both modes:
  • latest  → chronological (honest fallback shape unchanged);
  • for_you → transparent ranking, annotated with an explainable score;
  • private/confidential items NEVER enter either feed;
  • the ranker sees only already-stored signals (author, time, like/comment counts);
  • config weights are operator-tunable and actually change the order;
  • a bad ranker config falls back to Latest — it never fabricates or crashes;
  • both stored record shapes (posts + proof-shares) are handled without KeyError.
"""

import pytest

from runtime.blockchain.services.social.service import SocialService


async def _svc_with(viewer, authors, follows):
    svc = SocialService()
    await svc.create_profile(viewer, "Viewer", "")
    for a in authors:
        await svc.create_profile(a, a.upper(), "")
    for a in follows:
        await svc.follow_wallet(viewer, a)
    return svc


# ── latest mode (default, chronological) ────────────────────────────────────

@pytest.mark.asyncio
async def test_latest_is_chronological_followed_plus_self():
    svc = await _svc_with("0xme", ["0xa", "0xb", "0xc"], follows=["0xa", "0xb"])
    p1 = await svc.publish_post("0xa", "first")
    p2 = await svc.publish_post("0xme", "mine")
    p3 = await svc.publish_post("0xb", "third")
    stranger = await svc.publish_post("0xc", "not followed")  # noqa: F841
    # force a strict recency order
    p1["published_at"], p2["published_at"], p3["published_at"] = 100.0, 200.0, 300.0

    feed = await svc.get_feed("0xme", mode="latest")
    ids = [svc._item_id(it) for it in feed]
    assert ids == [p3["id"], p2["id"], p1["id"]]  # newest first, self included
    assert stranger["id"] not in ids  # non-followed excluded from Latest


@pytest.mark.asyncio
async def test_default_mode_is_latest():
    svc = await _svc_with("0xme", ["0xa"], follows=["0xa"])
    await svc.publish_post("0xa", "hello")
    default_feed = await svc.get_feed("0xme")
    latest_feed = await svc.get_feed("0xme", mode="latest")
    assert [svc._item_id(i) for i in default_feed] == [svc._item_id(i) for i in latest_feed]


# ── for_you mode (ranked + explainable) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_for_you_annotates_transparent_score():
    svc = await _svc_with("0xme", ["0xa"], follows=["0xa"])
    await svc.publish_post("0xa", "hi")
    feed = await svc.get_feed("0xme", mode="for_you")
    assert feed, "for_you must return the followed author's post"
    item = feed[0]
    assert "_rank_score" in item and isinstance(item["_rank_score"], (int, float))
    assert "_rank_breakdown" in item
    assert set(item["_rank_breakdown"]) == {"recency", "engagement", "affinity", "discovery"}


@pytest.mark.asyncio
async def test_for_you_surfaces_discovery_but_capped():
    # Followed author posts nothing engaging; many strangers post viral content.
    # For You must still include SOME discovery (strangers) — but capped, never the
    # whole page — and it must include followed content too.
    svc = await _svc_with("0xme", ["0xf"] + [f"0xs{i}" for i in range(10)], follows=["0xf"])
    await svc.publish_post("0xf", "quiet followed post")
    for i in range(10):
        rec = await svc.publish_post(f"0xs{i}", f"viral {i}")
        rec["reactions"] = {f"u{j}": "like" for j in range(1000)}  # huge (capped) engagement

    feed = await svc.get_feed("0xme", mode="for_you", limit=5)
    authors = [svc._item_actor(it) for it in feed[:5]]
    strangers = [a for a in authors if a.startswith("0xs")]
    assert "0xf" in authors                      # followed content present
    assert 0 < len(strangers) <= 1               # discovery present but capped (0.2 * 5 == 1)


# ── privacy absolute (both modes) ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_private_item_never_enters_either_feed():
    svc = await _svc_with("0xme", ["0xa"], follows=["0xa"])
    public = await svc.publish_post("0xa", "public post")
    # a private proof-share by a followed author — must NEVER surface
    svc._feed_items.append({
        "feed_item_id": "feed_private1",
        "sharer": "0xa",
        "timestamp": 999999.0,
        "reactions": {}, "comments": [],
        "proof_data": {"visibility": "private"},
    })
    for mode in ("latest", "for_you"):
        feed = await svc.get_feed("0xme", mode=mode)
        ids = [svc._item_id(it) for it in feed]
        assert "feed_private1" not in ids, f"private item leaked in {mode}"
        assert public["id"] in ids


@pytest.mark.asyncio
async def test_confidential_visibility_also_excluded():
    svc = await _svc_with("0xme", ["0xa"], follows=["0xa"])
    svc._feed_items.append({
        "feed_item_id": "feed_conf",
        "sharer": "0xa", "timestamp": 1.0, "reactions": {}, "comments": [],
        "proof_data": {"visibility": "confidential"},
    })
    feed = await svc.get_feed("0xme", mode="for_you")
    assert "feed_conf" not in [svc._item_id(it) for it in feed]


# ── config-tunable (operator changes weights → feed changes) ────────────────

@pytest.mark.asyncio
async def test_weights_are_operator_tunable():
    # Hold recency + engagement equal (same timestamp, no reactions) so AFFINITY is
    # the only thing separating the two posts. By default affinity (0.9) beats
    # discovery (0.4) → the followed author leads. Zero the affinity weight and the
    # discovery signal now decides → the stranger leads. Same data, different knob.
    import time
    ts = time.time()

    async def build(cfg):
        svc = SocialService(cfg)
        await svc.create_profile("0xme", "Me", "")
        await svc.create_profile("0xf", "F", "")
        await svc.create_profile("0xs", "S", "")
        await svc.follow_wallet("0xme", "0xf")
        followed = await svc.publish_post("0xf", "followed")
        stranger = await svc.publish_post("0xs", "stranger")
        followed["published_at"] = stranger["published_at"] = ts  # equal recency
        return svc

    default_svc = await build(None)
    top_default = (await default_svc.get_feed("0xme", mode="for_you", limit=5))[0]

    no_affinity = await build({"feed_ranker": {"affinity": 0.0}})
    top_tuned = (await no_affinity.get_feed("0xme", mode="for_you", limit=5))[0]

    assert default_svc._item_actor(top_default) == "0xf"   # affinity wins by default
    assert no_affinity._item_actor(top_tuned) == "0xs"     # discovery wins with affinity off


# ── honest fallback (never fabricate, never crash) ──────────────────────────

@pytest.mark.asyncio
async def test_bad_ranker_config_falls_back_to_latest():
    # An invalid weight (negative) makes the ranker raise; get_feed must fall back to
    # the honest chronological feed rather than 500 or fabricate an order.
    svc = SocialService({"feed_ranker": {"recency": -1.0}})
    await svc.create_profile("0xme", "Me", "")
    await svc.create_profile("0xa", "A", "")
    await svc.follow_wallet("0xme", "0xa")
    a = await svc.publish_post("0xa", "one")
    b = await svc.publish_post("0xa", "two")
    a["published_at"], b["published_at"] = 1.0, 2.0
    feed = await svc.get_feed("0xme", mode="for_you")
    ids = [svc._item_id(it) for it in feed]
    assert ids == [b["id"], a["id"]]  # chronological fallback, no _rank_score fabricated
    assert all("_rank_score" not in it for it in feed)


# ── robustness across the two stored record shapes ──────────────────────────

@pytest.mark.asyncio
async def test_mixed_record_shapes_do_not_keyerror():
    # _feed_items holds BOTH publish_post records (author/published_at) and
    # share_proof records (sharer/timestamp). Both modes must handle the mix.
    svc = await _svc_with("0xme", ["0xa"], follows=["0xa"])
    await svc.publish_post("0xa", "a post")            # author/published_at shape
    svc._feed_items.append({                            # sharer/timestamp shape
        "feed_item_id": "feed_pub", "sharer": "0xa", "timestamp": 5.0,
        "reactions": {"u": "x"}, "comments": [],
        "proof_data": {"visibility": "public"},
    })
    for mode in ("latest", "for_you"):
        feed = await svc.get_feed("0xme", mode=mode)
        assert len(feed) == 2, f"{mode} lost an item across record shapes"


@pytest.mark.asyncio
async def test_unknown_profile_raises():
    svc = SocialService()
    with pytest.raises(ValueError):
        await svc.get_feed("0xnobody", mode="for_you")


@pytest.mark.asyncio
async def test_nonpositive_limit_is_clamped_not_mis_sliced():
    # A non-positive limit must never silently mis-shape the feed (Latest would slice
    # feed[:-n]; for_you would page_size<=0). get_feed clamps to the default instead.
    svc = await _svc_with("0xme", ["0xa"], follows=["0xa"])
    for i in range(3):
        rec = await svc.publish_post("0xa", f"post {i}")
        rec["published_at"] = float(i)
    for bad in (0, -5):
        latest_feed = await svc.get_feed("0xme", limit=bad, mode="latest")
        for_you_feed = await svc.get_feed("0xme", limit=bad, mode="for_you")
        assert len(latest_feed) == 3, f"latest dropped items for limit={bad}"
        assert len(for_you_feed) == 3, f"for_you empty for limit={bad}"


@pytest.mark.asyncio
async def test_feed_view_matches_client_contract_and_stays_private():
    # get_feed_view must return {"posts":[...]} with the snake_case FeedPost keys the
    # iOS FeedResponse decodes — and never surface a private item.
    svc = await _svc_with("0xme", ["0xa"], follows=["0xa"])
    rec = await svc.publish_post("0xa", "hello world")
    rec["reactions"] = {"u1": "like", "u2": "like"}
    rec["comments"] = [{"t": "nice"}]
    svc._feed_items.append({
        "feed_item_id": "feed_secret", "sharer": "0xa", "timestamp": 9e9,
        "reactions": {}, "comments": [], "proof_data": {"visibility": "private"},
    })

    view = await svc.get_feed_view("0xme", mode="latest")
    assert set(view) == {"posts"}
    assert "feed_secret" not in [p["id"] for p in view["posts"]]

    post = next(p for p in view["posts"] if p["id"] == rec["id"])
    required = {
        "id", "display_name", "handle", "avatar_initials", "body", "timestamp",
        "is_verified", "proof_hash", "governance_tag", "like_count", "repost_count",
        "comment_count",
    }
    assert required <= set(post)
    assert post["body"] == "hello world"
    assert post["like_count"] == 2 and post["comment_count"] == 1
    # timestamp is a parseable ISO-8601 string (what the client's date decoder expects)
    from datetime import datetime
    datetime.strptime(post["timestamp"], "%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.asyncio
async def test_single_account_cannot_dominate_for_you():
    # End-to-end author-diversity: one account floods 40 viral posts; the viewer
    # follows a few other authors. The flooder cannot own the page.
    svc = await _svc_with("0xme", ["0xflood", "0xb", "0xc"], follows=["0xb", "0xc"])
    for i in range(40):
        rec = await svc.publish_post("0xflood", f"spam {i}")
        rec["reactions"] = {f"u{j}": "like" for j in range(500)}
    await svc.publish_post("0xb", "genuine b")
    await svc.publish_post("0xc", "genuine c")
    feed = await svc.get_feed("0xme", mode="for_you", limit=20)
    flooder = sum(1 for it in feed if svc._item_actor(it) == "0xflood")
    assert flooder <= 3, f"flooder took {flooder} slots (cap is 3)"
