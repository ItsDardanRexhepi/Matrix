"""No non-public item enters ANY feed — the platform's other feed included.

`SocialService._is_public_item` says: "Only publicly-visible items may enter
ANY feed ... Anything not explicitly 'public' is treated as private and never
surfaced". Inside SocialService it held. The platform has a second feed: the
ServiceDispatcher publishes every settled state-modifying action to the
public, unauthenticated /social/feed, and `send_message` is
`social.share_proof`. The feed engine stored the whole params dict it was
handed — a `proof_data` whose visibility is "followers" included — and served
it to anyone. And `ProofSharing.get_shared_proofs` returned a followers-only
share to any caller who named a viewer (`if viewer:`), beside a comment saying
the follower list would be checked "in production".

Three surfaces, one reading:
  * the public feed's own door, `SocialFeedEngine.ingest`, stores no item that
    declares itself non-public, never stores the privacy service, and stores
    no caller params at all;
  * the HTTP ripple announces no item that declares itself non-public;
  * a followers-only share is shown to the owner and the owner's followers.

Every feed check here runs the REAL feed engine on a scratch database and
reads back what it stored, which is what /social/feed serves.
"""

from __future__ import annotations

import asyncio

import pytest

from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
from runtime.blockchain.services.social.proof_sharing import ProofSharing
from runtime.blockchain.services.social.service import SocialService
from runtime.db.database import Database
from runtime.social.feed_engine import SocialFeedEngine


class _Feed(SocialFeedEngine):
    """The platform's public feed on a scratch database, counting the items it
    is handed so a test can wait for the dispatcher's fire-and-forget ingest."""

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

    async def stored(self) -> list[dict]:
        return [e.to_dict() for e in await self.get_feed(limit=100)]


@pytest.fixture
async def feed(tmp_path):
    db = Database({"database": {"path": str(tmp_path / "feed.db")}})
    yield _Feed(db)
    await db.close()


async def _dispatcher_with_profile(feed):
    d = ServiceDispatcher({})
    d._feed_engine = feed

    async def _quiet(*a, **k):
        return None

    d._attest_action = _quiet
    d._attest_refusal = _quiet
    social = d._get_registry().get("social")
    await social.create_profile("0xOWNER", "Owner", "")
    return d


async def _share(d, feed, visibility: str) -> None:
    await d.execute("send_message", params={
        "sharer": "0xOWNER",
        "proof_type": "achievement",
        "proof_data": {"attestation_uid": "0xUID", "visibility": visibility,
                       "description": "finished the course"},
    })
    await feed.settle()


async def test_a_followers_only_share_is_not_published_to_the_public_feed(feed):
    d = await _dispatcher_with_profile(feed)
    await _share(d, feed, "followers")
    assert feed.handed == 1, "premise: the dispatcher handed the share to the feed"
    stored = await feed.stored()
    assert stored == [], (
        "a followers-only proof share was published to the unauthenticated "
        f"public feed: {stored}")


@pytest.mark.parametrize("visibility", ["specific_addresses", "private", "FOLLOWERS"])
async def test_no_non_public_visibility_is_published(feed, visibility):
    """Through a stand-in social service that accepts any visibility, so the
    share SUCCEEDS and the only thing between it and the public feed is the
    feed's own door — the real service refuses these values before publishing
    is reached, which would make this pass for the wrong reason."""
    d = await _dispatcher_with_profile(feed)

    class _Social:
        async def share_proof(self, sharer, proof_type, proof_data):
            return {"feed_item_id": "feed_x", "sharer": sharer,
                    "proof_type": proof_type, "proof_data": proof_data}

    d._get_registry()._instances["social"] = _Social()
    await _share(d, feed, visibility)
    assert feed.handed == 1, "premise: the dispatcher handed the share to the feed"
    assert await feed.stored() == []


async def test_a_public_share_still_publishes_without_the_callers_params(feed):
    """SCOPE PIN, both halves: public content still reaches the feed, and the
    row it makes carries no request body — none of it is explicitly public."""
    d = await _dispatcher_with_profile(feed)
    await _share(d, feed, "public")
    stored = await feed.stored()
    assert len(stored) == 1, "a public share stopped being published"
    assert "params" not in stored[0]["detail"], (
        f"the caller's params were written into the public row: {stored[0]['detail']}")
    assert "finished the course" not in repr(stored[0])


async def test_the_privacy_service_never_publishes_to_the_public_feed(feed):
    """The HTTP ripple has always excluded the privacy service; the public
    feed did not."""
    d = ServiceDispatcher({})
    d._feed_engine = feed

    async def _quiet(*a, **k):
        return None

    d._attest_action = _quiet
    d._attest_refusal = _quiet

    class _Privacy:
        async def pin_to_ipfs(self, **kwargs):
            return {"cid": "bafy-test", "pinned": True}

    d._get_registry()._instances["privacy"] = _Privacy()
    await d.execute("ipfs_pin", params={"content": "my medical record"})
    await feed.settle()
    assert feed.handed == 1, "premise: the dispatcher handed the action to the feed"
    stored = await feed.stored()
    assert stored == [], f"a privacy action was announced: {stored}"


async def test_the_feeds_door_holds_whoever_hands_it_an_item(feed):
    """The rule is the feed's, not its caller's: an item handed straight to
    ingest is held to it too, and the event returned for a refused item says
    it was not published."""
    refused = await feed.ingest(action="send_message", actor="0xOWNER", detail={
        "service": "social",
        "params": {"proof_data": {"visibility": "followers"}}})
    pin = await feed.ingest(action="ipfs_pin", actor="0xOWNER",
                            detail={"service": "privacy", "params": {}})
    kept = await feed.ingest(action="swap_tokens", actor="0xOWNER", detail={
        "service": "dex", "params": {"amount_in": 5, "memo": "rent money"}})
    stored = await feed.stored()
    assert [e["event_type"] for e in stored] == ["swap_tokens"], stored
    assert stored[0]["detail"] == {"service": "dex"}, stored[0]["detail"]
    from runtime.social.feed_engine import NOT_PUBLISHED_SUMMARY
    assert refused.summary == pin.summary == NOT_PUBLISHED_SUMMARY
    assert kept.summary != NOT_PUBLISHED_SUMMARY


async def test_a_declined_entry_is_recorded_as_declined_by_the_outbox(feed):
    """The durable outbox delivers the dispatcher's feed entries through the
    same door; one the feed declines is recorded as such, not as ingested."""
    from runtime.durable import outbox
    from runtime.durable.wiring import DurableEngine

    deliver = DurableEngine(feed._db, mode="on").feed_deliverer(feed)
    declined = await deliver({"action": "send_message", "actor": "0xOWNER", "detail": {
        "service": "social", "params": {"proof_data": {"visibility": "followers"}}}})
    delivered = await deliver({"action": "swap_tokens", "actor": "0xOWNER",
                               "detail": {"service": "dex", "params": {}}})
    assert declined == outbox.Delivery(outbox.DELIVERED, "not_public")
    assert delivered == outbox.Delivery(outbox.DELIVERED, "ingested")


def test_the_outbox_and_the_feed_spell_a_declined_entry_alike():
    """runtime/durable imports nothing of the feed, so the word is written out
    on both sides; they must stay one word."""
    from runtime.durable.wiring import FEED_DECLINED_SUMMARY
    from runtime.social.feed_engine import NOT_PUBLISHED_SUMMARY
    assert FEED_DECLINED_SUMMARY == NOT_PUBLISHED_SUMMARY


def test_a_followers_share_is_not_shown_to_a_stranger():
    shares = ProofSharing({}, is_follower=lambda owner, viewer: viewer == "0xFAN")

    async def run():
        await shares.create_share("0xOWNER", "badge", "0xUID", "followers")
        stranger = await shares.get_shared_proofs("0xOWNER", viewer="0xSTRANGER")
        fan = await shares.get_shared_proofs("0xOWNER", viewer="0xFAN")
        owner = await shares.get_shared_proofs("0xOWNER", viewer="0xOWNER")
        anonymous = await shares.get_shared_proofs("0xOWNER")
        return stranger, fan, owner, anonymous

    stranger, fan, owner, anonymous = asyncio.run(run())
    assert stranger == [], "a followers-only share was shown to a non-follower"
    assert len(fan) == 1 and len(owner) == 1
    assert anonymous == []


def test_with_no_follow_graph_a_followers_share_stays_with_its_owner():
    shares = ProofSharing({})

    async def run():
        await shares.create_share("0xOWNER", "badge", "0xUID", "followers")
        return (await shares.get_shared_proofs("0xOWNER", viewer="0xANYONE"),
                await shares.get_shared_proofs("0xOWNER", viewer="0xOWNER"))

    anyone, owner = asyncio.run(run())
    assert anyone == [] and len(owner) == 1


async def test_social_service_answers_followership_from_its_own_graph():
    svc = SocialService({})
    await svc.create_profile("0xOWNER", "Owner", "")
    await svc.create_profile("0xFAN", "Fan", "")
    await svc.create_profile("0xSTRANGER", "Stranger", "")
    await svc.follow_wallet("0xFAN", "0xOWNER")
    await svc.proof_sharing.create_share("0xOWNER", "badge", "0xUID", "followers")
    assert len(await svc.proof_sharing.get_shared_proofs("0xOWNER", viewer="0xFAN")) == 1
    assert await svc.proof_sharing.get_shared_proofs("0xOWNER", viewer="0xSTRANGER") == []


async def test_the_http_ripple_does_not_announce_a_non_public_share():
    from gateway.service_routes import ServiceRoutes

    routes = ServiceRoutes({})
    sent: list = []
    routes._broadcaster.publish_dict = lambda kind, payload: sent.append((kind, payload))
    routes._maybe_ripple("social", "share_proof",
                         {"sharer": "0xOWNER", "proof_type": "badge",
                          "proof_data": {"visibility": "followers"}},
                         {"feed_item_id": "feed_1", "sharer": "0xOWNER",
                          "proof_data": {"visibility": "followers"}})
    assert sent == [], f"a followers-only share was rippled to every subscriber: {sent}"
    routes._maybe_ripple("social", "share_proof",
                         {"sharer": "0xOWNER", "proof_type": "badge",
                          "proof_data": {"visibility": "public"}},
                         {"feed_item_id": "feed_2", "sharer": "0xOWNER",
                          "proof_data": {"visibility": "public"}})
    assert len(sent) == 1, "a public share stopped rippling"


def test_a_well_formed_share_record_is_not_called_verified_on_chain():
    shares = ProofSharing({})

    async def run():
        share = await shares.create_share("0xOWNER", "badge", "0xUID", "public")
        return await shares.verify_shared_proof(share["share_id"])

    out = asyncio.run(run())
    assert "on-chain record" not in out["note"] or "not checked" in out["note"]
    assert out["attestation_checked_on_chain"] is False
