"""An operation that is private by what it is never reaches the public feed or
the live ripple, and neither does an item whose service answers that it is
not public.

The public feed's door held three rules: an item whose params say it is not
public is not stored, the privacy service is never stored, and no caller params
are stored. An encrypted direct message, a credential presentation and a
credential's issuance said nothing about visibility, so each was stored as
"0xaaaa…aaaa performed message_encrypt" under the caller's address and served
to anyone at /social/feed and /social/actor/{wallet}: the message's text was
gone and the private fact, who wrote to someone and when, was not. The door's
own docstring says of the privacy service that such an operation "under its
caller's address is itself the private fact", and README.md's feed bullet
promises "nothing that was shared with fewer people than everyone".

And the door read only the request. The ripple reads the request with the
service's answer (`is_public(kwargs, result)`); a share whose service stored it
as "followers" while the request named no visibility was hidden by SocialService
and by the ripple, and stored by the public feed.

`social/visibility.py` now lists the operations that are private by what they
are (`PRIVATE_OPERATIONS`); the feed's door refuses them under any action name
that runs them, the ripple refuses them by service and method, and the
dispatcher marks an entry whose answer is not public so the door declines it.
Every feed check here runs the REAL feed engine on a scratch database and reads
back what it stored, which is what /social/feed serves.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from runtime.blockchain.services.service_dispatcher import ACTION_MAP, ServiceDispatcher
from runtime.db.database import Database
from runtime.social.feed_engine import NOT_PUBLISHED_SUMMARY, SocialFeedEngine

USER = "0x" + "a" * 40
OTHER = "0x" + "b" * 40

#: What this file holds to be private by what it is, written out here rather
#: than read from the code, so a check below fails on what the feed does.
PRIVATE_OPERATIONS = frozenset({
    ("social", "send_encrypted_message"),
    ("did_identity", "create_did"),
    ("did_identity", "update_did"),
    ("did_identity", "deactivate_did"),
    ("did_identity", "issue_credential"),
    ("did_identity", "selective_disclose"),
    ("kyc", "start_kyc"),
    ("kyc", "issue_kyc_credential"),
})


def is_private_action(action):
    from runtime.blockchain.services.social import visibility

    return visibility.is_private_action(action)


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
        for _ in range(400):
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


def _dispatcher(feed) -> ServiceDispatcher:
    d = ServiceDispatcher({})
    d._feed_engine = feed

    async def _quiet(*a, **k):
        return None

    d._attest_action = _quiet
    d._attest_refusal = _quiet
    return d


async def test_an_encrypted_direct_message_is_not_announced(feed):
    d = _dispatcher(feed)
    out = json.loads(await d.execute("message_encrypt", params={
        "sender": USER, "recipient": OTHER, "content": "meet me at nine"},
        caller_identity=USER))
    await feed.settle()
    assert out["status"] == "ok" and feed.handed == 1, (
        f"premise: the message was sent and handed to the feed: {out}")
    assert await feed.stored() == [], (
        "an encrypted direct message was announced on the public feed under "
        f"its sender's address: {await feed.stored()}")


async def test_a_credential_issued_and_presented_is_not_announced(feed):
    d = _dispatcher(feed)
    issued = json.loads(await d.execute("credential_issue", params={
        "issuer_did": "did:matrix:issuer", "subject_did": "did:matrix:holder",
        "credential_type": "AgeCredential", "claims": {"over_18": True}},
        caller_identity=USER))
    await feed.settle()
    assert issued["status"] == "ok", f"premise: the credential was issued: {issued}"
    presented = json.loads(await d.execute("selective_disclose", params={
        "did": "did:matrix:holder", "credential_id": issued["result"]["id"],
        "fields": ["over_18"], "verifier_did": "did:matrix:verifier"},
        caller_identity=USER))
    await feed.settle()
    assert presented["status"] == "ok" and feed.handed == 2, (
        f"premise: the presentation was made and handed to the feed: {presented}")
    assert await feed.stored() == [], (
        f"a credential's issuance or presentation was announced: {await feed.stored()}")


async def test_a_decentralized_identifier_made_for_a_wallet_is_not_announced(feed):
    d = _dispatcher(feed)
    out = json.loads(await d.execute("create_did", params={"owner": USER},
                                     caller_identity=USER))
    await feed.settle()
    assert out["status"] == "ok" and feed.handed == 1, f"premise: {out}"
    assert await feed.stored() == [], await feed.stored()


@pytest.mark.parametrize("action", sorted(
    a for a, target in ACTION_MAP.items() if tuple(target[:2]) in PRIVATE_OPERATIONS))
async def test_the_door_refuses_every_name_that_runs_a_private_operation(feed, action):
    """Whoever hands the door an item, under any action name that runs one of
    these methods (an alias included), it is not stored and the event it
    answers says so."""
    event = await feed.ingest(action=action, actor=USER,
                              detail={"service": ACTION_MAP[action][0], "params": {}})
    assert event.summary == NOT_PUBLISHED_SUMMARY, (action, event.summary)
    assert await feed.stored() == []


def test_the_platform_reads_the_same_operations_as_private():
    from runtime.blockchain.services.social import visibility

    assert visibility.PRIVATE_OPERATIONS == PRIVATE_OPERATIONS


def test_each_private_operation_is_a_method_its_service_has():
    """[guard] The list names methods that exist, so a rename cannot leave an
    operation listed under a name nothing runs."""
    import importlib

    from runtime.blockchain.services import registry

    missing = []
    for service, method in sorted(PRIVATE_OPERATIONS):
        module_path, class_name = registry._SERVICE_MAP[service]
        cls = getattr(importlib.import_module(module_path, package=registry._PACKAGE),
                      class_name)
        if not callable(getattr(cls, method, None)):
            missing.append(f"{service}.{method}")
    assert missing == [], missing


def test_an_action_is_read_by_the_method_it_runs():
    assert is_private_action("message_encrypt")
    assert is_private_action("did_create") and is_private_action("create_did")
    assert not is_private_action("swap_tokens") and not is_private_action(None)
    assert not is_private_action("no_such_action")


async def test_a_share_its_service_answers_as_followers_only_is_not_stored(feed):
    """The request names no visibility; the service's answer says followers.
    SocialService and the ripple read the answer; so does the feed now."""
    d = _dispatcher(feed)

    class _Social:
        async def share_proof(self, sharer, proof_type, proof_data):
            return {"feed_item_id": "feed_x", "sharer": sharer, "proof_type": proof_type,
                    "proof_data": {**proof_data, "visibility": "followers"}}

    d._get_registry()._instances["social"] = _Social()
    await d.execute("send_message", params={
        "sharer": USER, "proof_type": "achievement",
        "proof_data": {"attestation_uid": "0xUID", "description": "finished"}})
    await feed.settle()
    assert feed.handed == 1, "premise: the share was handed to the feed"
    assert await feed.stored() == [], await feed.stored()


async def test_scope_pin_a_public_share_and_a_swap_are_still_announced(feed):
    """SCOPE PIN: the feed still carries what is public, and no stored row
    carries the mark a declined entry gets."""
    d = _dispatcher(feed)

    class _Social:
        async def share_proof(self, sharer, proof_type, proof_data):
            return {"feed_item_id": "feed_y", "sharer": sharer, "proof_type": proof_type,
                    "proof_data": proof_data}

    class _Dex:
        async def swap(self, **kw):
            return {"status": "submitted", "settled": True, "tx_hash": "0x" + "ab" * 32}

    d._get_registry()._instances["social"] = _Social()
    d._get_registry()._instances["dex"] = _Dex()
    await d.execute("send_message", params={
        "sharer": USER, "proof_type": "achievement",
        "proof_data": {"attestation_uid": "0xUID", "visibility": "public"}})
    await d.execute("swap_tokens", params={"token_in": "ETH", "token_out": "USDC",
                                           "amount_in": 1})
    await feed.settle()
    stored = await feed.stored()
    assert sorted(e["event_type"] for e in stored) == ["send_message", "swap_tokens"], stored
    assert all("private" not in e["detail"] for e in stored), stored


def _routes():
    from gateway.service_routes import ServiceRoutes

    routes = ServiceRoutes({})
    sent: list = []
    routes._broadcaster.publish_dict = lambda kind, payload: sent.append((kind, payload))
    return routes, sent


@pytest.mark.parametrize("service,method", sorted(PRIVATE_OPERATIONS))
def test_the_ripple_announces_no_private_operation(service, method):
    routes, sent = _routes()
    routes._maybe_ripple(service, method, {"owner": USER, "sender": USER},
                         {"id": "x-1", "status": "ok"})
    assert sent == [], f"{service}.{method} was rippled to every subscriber: {sent}"


def test_a_refused_private_operation_is_recorded_without_its_actor(caplog):
    """A decline is still recorded, and like a privacy action's it names nobody."""
    import logging

    routes, sent = _routes()
    with caplog.at_level(logging.INFO, logger="gateway.service_routes"):
        routes._maybe_ripple("did_identity", "issue_credential",
                             {"issuer_did": "did:matrix:issuer", "owner": USER},
                             {"status": "error", "error": "no vault"})
    declines = [r.getMessage() for r in caplog.records if "ACTION DECLINED" in r.getMessage()]
    assert sent == [] and len(declines) == 1, (sent, declines)
    assert USER not in declines[0] and "actor=<unknown>" in declines[0], declines[0]


def test_scope_pin_the_ripple_still_announces_a_public_action():
    routes, sent = _routes()
    routes._maybe_ripple("dao_management", "create_dao", {"creator": USER},
                         {"id": "dao_1", "status": "created"})
    assert len(sent) == 1, "an ordinary public action stopped rippling"


def test_no_capability_the_feed_refuses_names_a_feed_event():
    """The catalog serves a `feed_event` for each capability; one for an
    operation the feed never stores would say it is announced."""
    from runtime.capabilities.catalog import CAPABILITIES

    claimed = sorted(
        cap["id"] for cap in CAPABILITIES if cap.get("feed_event") and (
            cap["service"] == "privacy" or is_private_action(cap["action"])))
    assert claimed == [], claimed
