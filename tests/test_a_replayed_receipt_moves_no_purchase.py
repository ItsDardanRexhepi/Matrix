"""An App Store purchase belongs to the first account that verified it.

A transaction StoreKit signs is a bearer object: anyone holding its bytes can
post them to ``POST /api/v1/iap/verify`` again, and the signature still
verifies. The route recorded the transaction and then wrote the subscription
under the presenting session's account whatever the replay ledger answered, so
a second account posting the first account's transaction took the
subscription: the first account's tier went to none and the second's to pro.
The entitlement store did the same for any write that named another account.

The rule now: a purchase, by its ``originalTransactionId``, belongs to the
first account that verified it. Another account's session presenting it (the
same bytes, or another transaction of the same subscription) is answered
``409 bound_to_another_account``, and nothing of it is written: not the replay
ledger, not the subscription. The check and the writes are one database
transaction, so two accounts presenting the same new purchase at once cannot
both be told it is theirs. The account that holds a purchase presents it as
often as it likes, from any session of the sign-in it holds it under (an Apple
sign-in and the wallet linked to it are two accounts here:
tests/test_the_purchase_rule_is_described_as_it_answers.py). A purchase
recorded with no account (Apple's notification, or a post with no session)
goes to the first account that presents it, and a post with no session never
moves a purchase from an account. An older transaction moving a subscription
back is tests/test_an_older_transaction_takes_nothing_back.py's.

Refusing, rather than moving the subscription, is the cautious answer: an
Apple ID that signs in to a second account keeps its subscription on the
first, and nothing here transfers one.

The JWS fixture chain and the route configuration are tests/test_iap_verify.py's.
"""

from __future__ import annotations

import asyncio
import time

import pytest

pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from runtime.db.database import Database  # noqa: E402
from runtime.monetization.entitlement_store import EntitlementStore  # noqa: E402
from tests.test_iap_verify import (  # noqa: E402
    PRO, REDOS, Chain, _asn, _route_config, _tx_payload,
)

LINEAGE = "1000000000000001"
FIRST_TX = "2000000000000001"
ACCOUNT_A = "0x" + "a" * 40
ACCOUNT_B = "0x" + "b" * 40
MEMBER_C = "apple:member-c"
TOKENS = {
    "tok-a": {"address": ACCOUNT_A},
    "tok-a-second-device": {"address": ACCOUNT_A},
    "tok-b": {"address": ACCOUNT_B},
    "tok-c": {"address": MEMBER_C},
}
DAY_MS = 86400 * 1000


@pytest.fixture(scope="module")
def chain():
    return Chain()


async def _client(aiohttp_client, tmp_path, chain):
    from tests.test_gateway import _build_mock_server
    cfg = _route_config(tmp_path, chain)
    # Harness ceiling, not a product default: one client makes many calls.
    cfg["gateway"] = {**cfg["gateway"], "rate_limit_rpm": 100_000,
                      "rate_limit_burst": 100_000}
    server = _build_mock_server(cfg)
    server.wallet_sessions.get = lambda token, default=None: TOKENS.get(token, default)
    server._entitlements = EntitlementStore(
        Database({"database": {"path": str(tmp_path / "bind.db")}}))
    client = await aiohttp_client(server.create_app())
    client._store = server._entitlements
    return client


def _bearer(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _post(client, chain, token, payload):
    return await client.post("/api/v1/iap/verify", headers=_bearer(token),
                             json={"signedTransaction": chain.sign(payload)})


async def _tiers(client):
    return (await client._store.active_tier_for(ACCOUNT_A),
            await client._store.active_tier_for(ACCOUNT_B))


def _consumable(**over):
    return _tx_payload(productId=REDOS, transactionId="t-redo",
                       originalTransactionId="t-redo", expiresDate=None,
                       type="Consumable", **over)


class TestTheReplayProbe:
    @pytest.mark.asyncio
    async def test_the_store_never_moves_a_subscription_to_another_account(self, tmp_path):
        """The probe that found it, as it ran: each account records the same
        verified transaction and then writes the subscription under its own
        key. Before, the second write moved the subscription: A held none
        and B held pro."""
        store = EntitlementStore(Database({"database": {"path": str(tmp_path / "probe.db")}}))
        tx = dict(transaction_id="2000001", original_transaction_id="1000001",
                  product_id="pro.monthly", product_type="subscription", quantity=1,
                  purchase_date=time.time(), environment="Production")
        expires = time.time() + 86400 * 30
        for who in (ACCOUNT_A, ACCOUNT_B):
            await store.record_transaction(user_key=who, **tx)
            await store.upsert_entitlement(
                original_transaction_id="1000001", product_id="pro.monthly", tier="pro",
                user_key=who, status="active", purchase_date=tx["purchase_date"],
                expires_date=expires, environment="Production")
        assert (await store.entitlement("1000001"))["user_key"] == ACCOUNT_A
        assert (await store.active_tier_for(ACCOUNT_A),
                await store.active_tier_for(ACCOUNT_B)) == ("pro", None)


class TestAnotherAccountIsRefused:
    @pytest.mark.asyncio
    async def test_the_same_bytes_from_another_session_are_refused(
            self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        jws = chain.sign(_tx_payload())
        first = await client.post("/api/v1/iap/verify", headers=_bearer("tok-a"),
                                  json={"signedTransaction": jws})
        assert first.status == 200, await first.text()
        replayed = await client.post("/api/v1/iap/verify", headers=_bearer("tok-b"),
                                     json={"signedTransaction": jws})
        body = await replayed.json()
        assert replayed.status == 409, body
        assert body == {
            "error": "bound_to_another_account",
            "message": ("This App Store purchase belongs to another account; "
                        "it was not applied to this one."),
            "transactionId": FIRST_TX,
            "originalTransactionId": LINEAGE,
        }, body
        assert replayed.headers.get("X-Request-Id")
        assert (await client._store.entitlement(LINEAGE))["user_key"] == ACCOUNT_A
        assert (await client._store.transaction(FIRST_TX))["user_key"] == ACCOUNT_A
        assert await _tiers(client) == ("pro", None)

    @pytest.mark.asyncio
    async def test_a_newer_transaction_of_the_subscription_moves_nothing(
            self, aiohttp_client, tmp_path, chain):
        """Apple expired A's subscription. B posts a newer transaction of the
        same subscription: refused, and the subscription stays where A's own
        record and Apple's notification left it."""
        client = await _client(aiohttp_client, tmp_path, chain)
        now_ms = int(time.time() * 1000)
        old = _tx_payload(transactionId="t-1", purchaseDate=now_ms - 40 * DAY_MS,
                          expiresDate=now_ms - 10 * DAY_MS)
        assert (await _post(client, chain, "tok-a", old)).status == 200
        await client.post("/api/v1/iap/asn", json=_asn(chain, "EXPIRED", old))
        assert (await client._store.entitlement(LINEAGE))["status"] == "expired"
        newer = _tx_payload(transactionId="t-2", purchaseDate=now_ms - 1000,
                            expiresDate=now_ms + 30 * DAY_MS)
        replayed = await _post(client, chain, "tok-b", newer)
        assert replayed.status == 409, await replayed.text()
        row = await client._store.entitlement(LINEAGE)
        assert (row["status"], row["user_key"]) == ("expired", ACCOUNT_A)
        assert await client._store.transaction("t-2") is None
        assert await _tiers(client) == (None, None)

    @pytest.mark.asyncio
    async def test_another_accounts_consumable_is_refused(self, aiohttp_client, tmp_path, chain):
        """A consumable has no subscription; its transaction is what belongs
        to the account."""
        client = await _client(aiohttp_client, tmp_path, chain)
        assert (await _post(client, chain, "tok-a", _consumable())).status == 200
        replayed = await _post(client, chain, "tok-b", _consumable())
        assert replayed.status == 409, await replayed.text()
        assert (await replayed.json())["error"] == "bound_to_another_account"
        assert (await client._store.transaction("t-redo"))["user_key"] == ACCOUNT_A

    @pytest.mark.asyncio
    async def test_two_accounts_presenting_a_new_purchase_at_once_get_one_answer_each(
            self, aiohttp_client, tmp_path, chain):
        """The check and the writes are one transaction: of two sessions
        posting the same new purchase together, one holds it and the other is
        refused, and the refused one holds nothing."""
        client = await _client(aiohttp_client, tmp_path, chain)
        jws = chain.sign(_tx_payload())
        answers = await asyncio.gather(*(
            client.post("/api/v1/iap/verify", headers=_bearer(token),
                        json={"signedTransaction": jws})
            for token in ("tok-a", "tok-b")))
        statuses = [r.status for r in answers]
        assert sorted(statuses) == [200, 409], statuses
        holder = ACCOUNT_A if statuses[0] == 200 else ACCOUNT_B
        other = ACCOUNT_B if holder == ACCOUNT_A else ACCOUNT_A
        assert (await client._store.entitlement(LINEAGE))["user_key"] == holder
        assert (await client._store.transaction(FIRST_TX))["user_key"] == holder
        assert (await client._store.active_tier_for(holder),
                await client._store.active_tier_for(other)) == ("pro", None)


class TestTheAccountThatHoldsItKeepsUsingIt:
    @pytest.mark.asyncio
    async def test_the_holder_presents_it_again_from_any_of_its_sessions(
            self, aiohttp_client, tmp_path, chain):
        """Boundary guard (it held before the fix too): a second verify, a
        restore from another device, and the next renewal are answered 200
        and the subscription stays with A."""
        client = await _client(aiohttp_client, tmp_path, chain)
        jws = chain.sign(_tx_payload())
        for token, replay in (("tok-a", False), ("tok-a", True), ("tok-a-second-device", True)):
            resp = await client.post("/api/v1/iap/verify", headers=_bearer(token),
                                     json={"signedTransaction": jws})
            assert resp.status == 200, await resp.text()
            assert (await resp.json())["replay"] is replay
        renewal = _tx_payload(transactionId="t-renewal",
                              expiresDate=int(time.time() * 1000) + 60 * DAY_MS)
        assert (await _post(client, chain, "tok-a-second-device", renewal)).status == 200
        row = await client._store.entitlement(LINEAGE)
        assert (row["user_key"], row["status"]) == (ACCOUNT_A, "active")
        assert row["expires_date"] > time.time() + 50 * 86400
        assert await _tiers(client) == ("pro", None)

    @pytest.mark.asyncio
    async def test_another_spelling_of_the_holders_address_is_the_holder(
            self, aiohttp_client, tmp_path, chain):
        """A wallet is one caller in every spelling of its address
        (runtime/auth/identity.py): a session stored before the one-spelling
        rule is the holder, not another account, and the subscription stays
        under the spelling it was bound in."""
        client = await _client(aiohttp_client, tmp_path, chain)
        TOKENS["tok-a-old-spelling"] = {"address": ACCOUNT_A.upper().replace("0X", "0x")}
        try:
            assert (await _post(client, chain, "tok-a", _tx_payload())).status == 200
            again = await _post(client, chain, "tok-a-old-spelling", _tx_payload())
            assert again.status == 200, await again.text()
        finally:
            TOKENS.pop("tok-a-old-spelling")
        assert (await client._store.entitlement(LINEAGE))["user_key"] == ACCOUNT_A
        assert await _tiers(client) == ("pro", None)

    @pytest.mark.asyncio
    async def test_a_family_sharing_members_own_transaction_is_its_own_purchase(
            self, aiohttp_client, tmp_path, chain):
        """Boundary guard (it held before the fix too). StoreKit vendors'
        Family Sharing guides describe a member's access as a transaction of
        its own, with a new ``originalTransactionId`` and
        ``inAppOwnershipType`` ``FAMILY_SHARED``; held that way, it is the
        member's purchase and refuses nobody. This shape is the guides'; it
        has not been measured against Apple here. A member's transaction
        carrying the purchaser's ``originalTransactionId`` would be refused
        as another account's."""
        client = await _client(aiohttp_client, tmp_path, chain)
        assert (await _post(client, chain, "tok-a", _tx_payload(inAppOwnershipType="PURCHASED"))).status == 200
        shared = _tx_payload(transactionId="t-family", originalTransactionId="o-family",
                             inAppOwnershipType="FAMILY_SHARED")
        resp = await _post(client, chain, "tok-c", shared)
        assert resp.status == 200, await resp.text()
        assert (await client._store.entitlement("o-family"))["user_key"] == MEMBER_C
        assert await client._store.active_tier_for(MEMBER_C) == "pro"
        assert await _tiers(client) == ("pro", None)


class TestAPurchaseWithNoAccount:
    @pytest.mark.asyncio
    async def test_a_subscription_apples_notification_recorded_goes_to_the_first_account(
            self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        await client.post("/api/v1/iap/asn", json=_asn(chain, "SUBSCRIBED", _tx_payload()))
        assert (await client._store.entitlement(LINEAGE))["user_key"] == ""
        claimed = await _post(client, chain, "tok-b", _tx_payload())
        assert claimed.status == 200, await claimed.text()
        late = await _post(client, chain, "tok-a", _tx_payload())
        assert late.status == 409, await late.text()
        assert (await client._store.entitlement(LINEAGE))["user_key"] == ACCOUNT_B
        assert await _tiers(client) == (None, "pro")

    @pytest.mark.asyncio
    async def test_a_consumable_posted_with_no_session_goes_to_the_first_account(
            self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        assert (await _post(client, chain, None, _consumable())).status == 200
        assert (await client._store.transaction("t-redo"))["user_key"] == ""
        assert (await _post(client, chain, "tok-b", _consumable())).status == 200
        assert (await client._store.transaction("t-redo"))["user_key"] == ACCOUNT_B
        late = await _post(client, chain, "tok-a", _consumable())
        assert late.status == 409, await late.text()
        assert (await client._store.transaction("t-redo"))["user_key"] == ACCOUNT_B

    @pytest.mark.asyncio
    async def test_a_post_with_no_session_takes_nothing_away(self, aiohttp_client, tmp_path, chain):
        """Boundary guard (it held before the fix too)."""
        client = await _client(aiohttp_client, tmp_path, chain)
        assert (await _post(client, chain, "tok-a", _tx_payload())).status == 200
        anonymous = await _post(client, chain, None, _tx_payload())
        assert anonymous.status == 200, await anonymous.text()
        assert (await client._store.entitlement(LINEAGE))["user_key"] == ACCOUNT_A
        assert await _tiers(client) == ("pro", None)


class TestWhoHoldsItIsNeverGuessed:
    @pytest.mark.asyncio
    async def test_a_store_that_cannot_read_the_holder_writes_nothing(
            self, aiohttp_client, tmp_path, chain, monkeypatch):
        """Guard for the lookup itself: a read that fails is not "nobody
        holds it". The request answers 503 and nothing is written."""
        import sqlite3
        client = await _client(aiohttp_client, tmp_path, chain)

        def unreadable(*_args, **_kwargs):
            raise sqlite3.OperationalError("database is locked")
        monkeypatch.setattr(EntitlementStore, "_holder_in", staticmethod(unreadable))
        resp = await _post(client, chain, "tok-a", _tx_payload())
        assert resp.status == 503, await resp.text()
        assert await client._store.transaction(FIRST_TX) is None
        assert await client._store.entitlement(LINEAGE) is None
