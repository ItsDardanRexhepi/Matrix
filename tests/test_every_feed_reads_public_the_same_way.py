"""Every surface that decides whether an item is public decides it the same way.

`SocialService._is_public_item` says: "Only publicly-visible items may enter
ANY feed ... Anything not explicitly 'public' is treated as private and never
surfaced", and that the dispatcher's feed path and the HTTP ripple apply "this
same reading". They applied a copy of it, `service_dispatcher.declares_non_public`,
which disagreed with the original on inputs a caller writes. Measured before
the change, through `ServiceDispatcher.execute("send_message", ...)`:

  * ``proof_data {"visibility": None}``      -> 1 row on the public feed,
    0 items in SocialService.get_feed
  * ``proof_data {"visibility": " public"}`` -> 1 row on the public feed,
    0 items in SocialService.get_feed

and the HTTP ripple, which uses the dispatcher's copy, announced both. The
content stayed out of the row; the share's existence and its actor did not.

Both now call one function, `social.visibility.is_public`. These tests hold
the three surfaces against each other on a table of inputs, rather than
against a list of words, so a fourth reading added later fails here too.
"""

from __future__ import annotations

import asyncio

import pytest

from runtime.blockchain.services.service_dispatcher import (
    ServiceDispatcher,
    declares_non_public,
)
from runtime.blockchain.services.social.service import SocialService

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


class _Feed:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def ingest(self, **kwargs):
        self.published.append(kwargs)


async def _dispatcher_publishes(top: dict, proof_data) -> bool:
    """Does the dispatcher's feed ingest publish this share? Through a stand-in
    social service that accepts anything, so the gate is the only thing
    between the item and the public feed."""
    d = ServiceDispatcher({})
    feed = _Feed()
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
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    return len(feed.published) == 1


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
async def test_the_feed_the_dispatcher_and_the_ripple_agree(label, top, proof_data):
    shown = SocialService._is_public_item(_item(top, proof_data))
    published = await _dispatcher_publishes(top, proof_data)
    announced = _ripple_announces(top, proof_data)
    assert shown == published == announced, (
        f"{label}: SocialService's feed {'shows' if shown else 'hides'} this "
        f"item, the dispatcher {'publishes' if published else 'does not publish'} "
        f"it to the public feed and the ripple "
        f"{'announces' if announced else 'does not announce'} it")


@pytest.mark.parametrize("label,top,proof_data", _TABLE, ids=[r[0] for r in _TABLE])
def test_the_dispatchers_predicate_is_the_feeds(label, top, proof_data):
    item = _item(top, proof_data)
    assert declares_non_public(item) is (not SocialService._is_public_item(item)), label


def test_only_the_plain_word_public_is_public():
    """SCOPE PIN, both directions: the strict reading must not hide what is
    public, and must hide everything that is not."""
    public = {label for label, top, pd in _TABLE
              if SocialService._is_public_item(_item(top, pd))}
    assert public == {"public", "PUBLIC", "no visibility at all", "no proof_data"}


@pytest.mark.parametrize("visibility", [None, " public"])
async def test_the_measured_shares_reach_no_feed(visibility):
    """THE REPRODUCTION, through the real SocialService: each was published
    as one public row while get_feed surfaced none."""
    d = ServiceDispatcher({})
    feed = _Feed()
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
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(social._feed_items) == 1, "premise: the share was stored"
    assert await social.get_feed(_OWNER) == []
    assert feed.published == [], (
        f"a share SocialService hides was published to the public feed: "
        f"{feed.published}")


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
