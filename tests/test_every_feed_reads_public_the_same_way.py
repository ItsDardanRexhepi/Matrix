"""Every surface that decides whether an item is public decides it the same way.

`SocialService._is_public_item` says: "Only publicly-visible items may enter
ANY feed ... Anything not explicitly 'public' is treated as private and never
surfaced". The platform's public feed (`SocialFeedEngine`, served from
/social/feed with no session) stored whatever the service dispatcher handed
it, and the HTTP ripple announced whatever it was given, so a share
SocialService's own feed hid was published and rippled.

All three now call one function, `social.visibility.is_public`. These tests
hold the three surfaces against each other on a table of inputs a caller
writes, rather than against a list of words, so a fourth reading added later
fails here too. The public feed is the real engine on a scratch database,
read back after the dispatcher's ingest.
"""

from __future__ import annotations

import asyncio

import pytest

from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
from runtime.blockchain.services.social.service import SocialService
from runtime.db.database import Database
from runtime.social.feed_engine import SocialFeedEngine

_OWNER = "0x" + "1" * 40

#: (label, top-level fields, proof_data). Each is an item a caller can make:
#: the dispatcher copies `proof_data` from the request, and a stand-in service
#: echoes the rest, so every row reaches the gate.
_TABLE = [
    ("public", {}, {"visibility": "public"}),
    ("PUBLIC", {}, {"visibility": "PUBLIC"}),
    ("no visibility at all", {}, {"description": "x"}),
    ("no proof_data", {}, None),
    ("explicit null", {}, {"visibility": None}),
    ("leading space", {}, {"visibility": " public"}),
    ("trailing space", {}, {"visibility": "public "}),
    ("empty string", {}, {"visibility": ""}),
    ("followers", {}, {"visibility": "followers"}),
    ("a number", {}, {"visibility": 0}),
    ("a list holding the word", {}, {"visibility": ["public"]}),
    ("top says public, proof_data says followers",
     {"visibility": "public"}, {"visibility": "followers"}),
    ("top-level explicit null", {"visibility": None}, {"visibility": "public"}),
    ("private flag", {}, {"visibility": "public", "private": True}),
    ("is_private written as a word", {"is_private": "yes"}, {"visibility": "public"}),
    ("proof_data that is not a mapping", {}, "public"),
]


def _item(top: dict, proof_data) -> dict:
    item = {"feed_item_id": "feed_x", "sharer": _OWNER, "proof_type": "achievement"}
    item.update(top)
    if proof_data is not None:
        item["proof_data"] = proof_data
    return item


class _Feed(SocialFeedEngine):
    """The public feed on a scratch database, counting what it is handed so a
    test can wait for the dispatcher's fire-and-forget ingest."""

    def __init__(self, db) -> None:
        super().__init__(db)
        self.handed = 0
        self.finished = 0

    async def ingest(self, **kwargs):
        self.handed += 1
        try:
            return await super().ingest(**kwargs)
        finally:
            self.finished += 1

    async def settle(self) -> None:
        for _ in range(200):
            await asyncio.sleep(0.005)
            if self.handed and self.finished == self.handed:
                return

    async def stored(self) -> list:
        return await self.get_feed(limit=100)


@pytest.fixture
async def feed(tmp_path):
    db = Database({"database": {"path": str(tmp_path / "feed.db")}})
    yield _Feed(db)
    await db.close()


async def _dispatcher_publishes(feed, top: dict, proof_data) -> bool:
    """Does the public feed hold this share after the dispatcher handed it
    over? Through a stand-in social service that accepts anything, so the
    feed's own door is the only thing between the item and the public feed."""
    d = ServiceDispatcher({})
    d._feed_engine = feed

    async def _quiet(*a, **k):
        return None

    d._attest_action = _quiet
    d._attest_refusal = _quiet

    class _Social:
        async def share_proof(self, sharer, proof_type, proof_data=None, **extra):
            return _item(top, proof_data)

    d._get_registry()._instances["social"] = _Social()
    params = {"sharer": _OWNER, "proof_type": "achievement", **top}
    if proof_data is not None:
        params["proof_data"] = proof_data
    await d.execute("send_message", params=params)
    await feed.settle()
    assert feed.handed == 1, "premise: the dispatcher handed the share to the feed"
    return len(await feed.stored()) == 1


def _ripple_announces(top: dict, proof_data) -> bool:
    from gateway.service_routes import ServiceRoutes

    routes = ServiceRoutes({})
    sent: list = []
    routes._broadcaster.publish_dict = lambda kind, payload: sent.append((kind, payload))
    kwargs = {"sharer": _OWNER, "proof_type": "achievement", **top}
    if proof_data is not None:
        kwargs["proof_data"] = proof_data
    routes._maybe_ripple("social", "share_proof", kwargs, _item(top, proof_data))
    return len(sent) == 1


@pytest.mark.parametrize("label,top,proof_data", _TABLE, ids=[r[0] for r in _TABLE])
async def test_the_feed_the_dispatcher_and_the_ripple_agree(feed, label, top, proof_data):
    shown = SocialService._is_public_item(_item(top, proof_data))
    published = await _dispatcher_publishes(feed, top, proof_data)
    announced = _ripple_announces(top, proof_data)
    assert shown == published == announced, (
        f"{label}: SocialService's feed {'shows' if shown else 'hides'} this "
        f"item, the dispatcher {'publishes' if published else 'does not publish'} "
        f"it to the public feed and the ripple "
        f"{'announces' if announced else 'does not announce'} it")


@pytest.mark.parametrize("label,top,proof_data", _TABLE, ids=[r[0] for r in _TABLE])
async def test_the_public_feeds_door_reads_as_the_feed_does(feed, label, top, proof_data):
    """The feed engine's ingest, handed the item directly as the dispatcher's
    params, keeps exactly what SocialService's feed shows."""
    item = _item(top, proof_data)
    await feed.ingest(action="send_message", actor=_OWNER,
                      detail={"service": "social", "params": item})
    kept = len(await feed.stored()) == 1
    assert kept is SocialService._is_public_item(item), label


def test_only_the_plain_word_public_is_public():
    """SCOPE PIN, both directions: the strict reading must not hide what is
    public, and must hide everything that is not."""
    public = {label for label, top, pd in _TABLE
              if SocialService._is_public_item(_item(top, pd))}
    assert public == {"public", "PUBLIC", "no visibility at all", "no proof_data"}


@pytest.mark.parametrize("visibility", [None, " public"])
async def test_the_measured_shares_reach_no_feed(feed, visibility):
    """THE REPRODUCTION, through the real SocialService: each was published
    as one public row while get_feed surfaced none."""
    d = ServiceDispatcher({})
    d._feed_engine = feed

    async def _quiet(*a, **k):
        return None

    d._attest_action = _quiet
    d._attest_refusal = _quiet
    social = d._get_registry().get("social")
    await social.create_profile(_OWNER, "Owner", "")
    await d.execute("send_message", params={
        "sharer": _OWNER, "proof_type": "achievement",
        "proof_data": {"visibility": visibility, "description": "finished"},
    })
    await feed.settle()
    assert len(social._feed_items) == 1, "premise: the share was stored"
    assert await social.get_feed(_OWNER) == []
    assert feed.handed == 1, "premise: the dispatcher handed the share to the feed"
    stored = await feed.stored()
    assert stored == [], (
        f"a share SocialService hides was published to the public feed: {stored}")


async def test_a_share_the_service_refuses_leaves_nothing_in_the_feed():
    """`create_share` refuses a visibility outside its three words. It ran
    after the feed item was stored, so a share the caller was told had failed
    stayed in the feed; "PUBLIC" was then shown there, too."""
    svc = SocialService({})
    await svc.create_profile(_OWNER, "Owner", "")
    for visibility in ("PUBLIC", "specific_addresses"):
        with pytest.raises(ValueError):
            await svc.share_proof(_OWNER, "achievement", {
                "attestation_uid": "0xUID", "visibility": visibility})
    assert svc._feed_items == [], svc._feed_items
    assert await svc.get_feed(_OWNER) == []
