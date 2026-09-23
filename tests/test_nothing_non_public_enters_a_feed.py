"""No non-public item enters ANY feed — the platform's other feed included.

`SocialService._is_public_item` says: "Only publicly-visible items may enter
ANY feed ... Anything not explicitly 'public' is treated as private and never
surfaced". Inside SocialService it held. The platform has a second feed: the
ServiceDispatcher publishes every settled state-modifying action to the
public, unauthenticated /social/feed, and `send_message` is
`social.share_proof`. Its whole params dict — a `proof_data` whose visibility
is "followers" included — was copied into the public row. And
`ProofSharing.get_shared_proofs` returned a followers-only share to any caller
who named a viewer (`if viewer:`), beside a comment saying the follower list
would be checked "in production".

Three surfaces, one reading:
  * the dispatcher's feed ingest skips an item that declares itself
    non-public, skips the privacy service (the HTTP ripple always did), and
    carries no caller params into the public row at all;
  * the HTTP ripple skips an item that declares itself non-public;
  * a followers-only share is shown to the owner and the owner's followers.
"""

from __future__ import annotations

import asyncio

import pytest

from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
from runtime.blockchain.services.social.proof_sharing import ProofSharing
from runtime.blockchain.services.social.service import SocialService


class _Feed:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def ingest(self, **kwargs):
        self.published.append(kwargs)


async def _dispatcher_with_profile():
    d = ServiceDispatcher({})
    feed = _Feed()
    d._feed_engine = feed

    async def _quiet(*a, **k):
        return None

    d._attest_action = _quiet
    d._attest_refusal = _quiet
    social = d._get_registry().get("social")
    await social.create_profile("0xOWNER", "Owner", "")
    return d, feed


async def _share(d, visibility: str) -> None:
    await d.execute("send_message", params={
        "sharer": "0xOWNER",
        "proof_type": "achievement",
        "proof_data": {"attestation_uid": "0xUID", "visibility": visibility,
                       "description": "finished the course"},
    })
    await asyncio.sleep(0)
    await asyncio.sleep(0)


async def test_a_followers_only_share_is_not_published_to_the_public_feed():
    d, feed = await _dispatcher_with_profile()
    await _share(d, "followers")
    assert feed.published == [], (
        "a followers-only proof share was published to the unauthenticated "
        f"public feed: {feed.published}")


@pytest.mark.parametrize("visibility", ["specific_addresses", "private", "FOLLOWERS"])
async def test_no_non_public_visibility_is_published(visibility):
    """Through a stand-in social service that accepts any visibility, so the
    share SUCCEEDS and the only thing between it and the public feed is the
    gate — the real service refuses these values before publishing is
    reached, which would make this pass for the wrong reason."""
    d, feed = await _dispatcher_with_profile()

    class _Social:
        async def share_proof(self, sharer, proof_type, proof_data):
            return {"feed_item_id": "feed_x", "sharer": sharer,
                    "proof_type": proof_type, "proof_data": proof_data}

    d._get_registry()._instances["social"] = _Social()
    await _share(d, visibility)
    assert feed.published == [], feed.published


async def test_a_public_share_still_publishes_without_the_callers_params():
    """SCOPE PIN, both halves: public content still reaches the feed, and the
    row it makes carries no request body — none of it is explicitly public."""
    d, feed = await _dispatcher_with_profile()
    await _share(d, "public")
    assert len(feed.published) == 1, "a public share stopped being published"
    detail = feed.published[0]["detail"]
    assert "params" not in detail, (
        f"the caller's params were written into the public row: {detail}")
    assert "finished the course" not in repr(feed.published[0])


async def test_the_privacy_service_never_publishes_to_the_public_feed():
    """The HTTP ripple has always excluded the privacy service; the
    dispatcher's feed did not."""
    d = ServiceDispatcher({})
    feed = _Feed()
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
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert feed.published == [], f"a privacy action was announced: {feed.published}"


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
