"""A refund the ledger already holds ends the subscription written after it.

An App Store refund or revoke notice ends the subscription record when the
gateway can write one: the record exists, or the notice names a subscription
product the gateway is configured with. A notice about a product the gateway
did not know yet (an App Store product put on sale before the gateway's
configuration named it) could write no record, so the refund was kept only on
the transaction ledger. Once the product was configured, the app posting the
transaction as it was signed before the refund, or a later period of the same
subscription, or the App Store's next renewal notice, wrote the subscription
active and gave it the plan, while the ledger said the purchase was refunded.

The rule now: a subscription record the gateway writes for the first time
takes the refund or revocation the ledger holds for any transaction of that
subscription, so it is written already ended. Only the first write reads the
ledger: a record that exists keeps the status its own notices gave it, so a
subscription an operator reinstated by hand after the App Store reversed a
refund is not ended again by the next post.

The JWS fixture chain and the route configuration are tests/test_iap_verify.py's.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from runtime.db.database import Database  # noqa: E402
from runtime.monetization.entitlement_store import EntitlementStore  # noqa: E402
from tests.test_iap_verify import Chain, _asn, _route_config, _tx_payload  # noqa: E402

# A product id the gateway's configuration names only partway through a test.
ADDED_LATER = "com.opnmatrx.mtrx.pro.added_later"
LINEAGE = "1000000000000001"
ACCOUNT_A = "0x" + "a" * 40
TOKENS = {"tok-a": {"address": ACCOUNT_A}}
DAY_MS = 86400 * 1000
NOW_MS = int(time.time() * 1000)
CONFIGURED = {ADDED_LATER: {"type": "subscription", "tier": "pro"}}


@pytest.fixture(scope="module")
def chain():
    return Chain()


async def _client(aiohttp_client, tmp_path, chain, **iap_over):
    """A gateway over the one database file of *tmp_path*, configured with
    *iap_over*: two of them stand for one gateway before and after its
    configuration named the product."""
    from tests.test_gateway import _build_mock_server
    cfg = _route_config(tmp_path, chain, **iap_over)
    # Harness ceiling, not a product default: one client makes many calls.
    cfg["gateway"] = {**cfg["gateway"], "rate_limit_rpm": 100_000,
                      "rate_limit_burst": 100_000}
    server = _build_mock_server(cfg)
    server.wallet_sessions.get = lambda token, default=None: TOKENS.get(token, default)
    server._entitlements = EntitlementStore(
        Database({"database": {"path": str(tmp_path / "ledger.db")}}))
    client = await aiohttp_client(server.create_app())
    client._store = server._entitlements
    return client


async def _verify(client, chain, token, payload):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = await client.post("/api/v1/iap/verify", headers=headers,
                             json={"signedTransaction": chain.sign(payload)})
    assert resp.status == 200, await resp.text()
    return resp


async def _notify(client, chain, kind, payload):
    resp = await client.post("/api/v1/iap/asn", json=_asn(chain, kind, payload))
    assert resp.status == 200, await resp.text()


def _period(transaction_id, days_ago, days_left):
    return _tx_payload(transactionId=transaction_id, productId=ADDED_LATER,
                       purchaseDate=NOW_MS - days_ago * DAY_MS,
                       expiresDate=NOW_MS + days_left * DAY_MS)


def _revoked(payload):
    return dict(payload, revocationDate=NOW_MS - 1000, revocationReason=0)


async def _refund_before_the_product_was_configured(aiohttp_client, tmp_path, chain, kind):
    """The notice reaches a gateway that does not know the product: the
    ledger keeps it, and no subscription record can be written."""
    before = await _client(aiohttp_client, tmp_path, chain)
    await _notify(before, chain, kind, _revoked(_period("t-1", 5, 360)))
    ended = "refunded" if kind == "REFUND" else "revoked"
    assert (await before._store.transaction("t-1"))["status"] == ended
    assert await before._store.entitlement(LINEAGE) is None
    return await _client(aiohttp_client, tmp_path, chain, products=CONFIGURED), ended


class TestARefundTheLedgerHolds:
    @pytest.mark.parametrize("kind", ["REFUND", "REVOKE"])
    @pytest.mark.asyncio
    async def test_the_signing_from_before_the_refund_writes_it_ended(
            self, aiohttp_client, tmp_path, chain, kind):
        client, ended = await _refund_before_the_product_was_configured(
            aiohttp_client, tmp_path, chain, kind)
        await _verify(client, chain, "tok-a", _period("t-1", 5, 360))
        row = await client._store.entitlement(LINEAGE)
        assert (row["status"], row["user_key"]) == (ended, ACCOUNT_A), row
        assert await client._store.active_tier_for(ACCOUNT_A) is None

    @pytest.mark.asyncio
    async def test_a_later_period_posted_after_it_stays_ended(self, aiohttp_client, tmp_path, chain):
        """As a refund the record already held: an ended subscription stays
        ended (tests/test_a_refund_ends_the_subscription_whichever_arrives_first.py)."""
        client, ended = await _refund_before_the_product_was_configured(
            aiohttp_client, tmp_path, chain, "REFUND")
        await _verify(client, chain, "tok-a", _period("t-2", 1, 364))
        assert (await client._store.entitlement(LINEAGE))["status"] == ended
        assert await client._store.active_tier_for(ACCOUNT_A) is None

    @pytest.mark.asyncio
    async def test_the_next_renewal_notice_writes_it_ended(self, aiohttp_client, tmp_path, chain):
        client, ended = await _refund_before_the_product_was_configured(
            aiohttp_client, tmp_path, chain, "REFUND")
        await _notify(client, chain, "DID_RENEW", _period("t-2", 1, 364))
        assert (await client._store.entitlement(LINEAGE))["status"] == ended
        await _verify(client, chain, "tok-a", _period("t-2", 1, 364))
        assert await client._store.active_tier_for(ACCOUNT_A) is None


class TestWhatTheLedgerDoesNotEnd:
    """Boundary guards: each held before the rule and holds after it."""

    @pytest.mark.asyncio
    async def test_a_purchase_nobody_refunded_is_written_active_once_configured(
            self, aiohttp_client, tmp_path, chain):
        before = await _client(aiohttp_client, tmp_path, chain)
        await _verify(before, chain, "tok-a", _period("t-1", 5, 360))
        assert await before._store.entitlement(LINEAGE) is None
        client = await _client(aiohttp_client, tmp_path, chain, products=CONFIGURED)
        await _verify(client, chain, "tok-a", _period("t-1", 5, 360))
        assert (await client._store.entitlement(LINEAGE))["status"] == "active"
        assert await client._store.active_tier_for(ACCOUNT_A) == "pro"

    @pytest.mark.parametrize("kind, ended", [("REFUND", "refunded"), ("REVOKE", "revoked")])
    @pytest.mark.asyncio
    async def test_a_refund_of_a_product_it_does_not_know_ends_a_record_that_exists(
            self, aiohttp_client, tmp_path, chain, kind, ended):
        """The subscription moved to a product the gateway does not know
        (a crossgrade within the group); the refund of that period still
        ends the record its known product wrote."""
        client = await _client(aiohttp_client, tmp_path, chain)
        known = _tx_payload(transactionId="t-1", purchaseDate=NOW_MS - 40 * DAY_MS,
                            expiresDate=NOW_MS + 20 * DAY_MS)
        await _verify(client, chain, "tok-a", known)
        await _notify(client, chain, kind, _revoked(_period("t-2", 5, 360)))
        assert (await client._store.entitlement(LINEAGE))["status"] == ended
        assert await client._store.active_tier_for(ACCOUNT_A) is None

    @pytest.mark.asyncio
    async def test_the_notice_that_arrives_last_says_how_it_ended(
            self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain, products=CONFIGURED)
        await _verify(client, chain, "tok-a", _period("t-1", 5, 360))
        await _notify(client, chain, "REFUND", _revoked(_period("t-1", 5, 360)))
        await _notify(client, chain, "REVOKE", _revoked(_period("t-1", 5, 360)))
        assert (await client._store.entitlement(LINEAGE))["status"] == "revoked"

    @pytest.mark.asyncio
    async def test_a_subscription_reinstated_by_hand_is_not_ended_again(
            self, aiohttp_client, tmp_path, chain):
        """After the App Store reverses a refund, an operator reinstates the
        subscription with set_status(allow_terminal_override=True); the
        refund still on the ledger does not end it again."""
        client = await _client(aiohttp_client, tmp_path, chain, products=CONFIGURED)
        await _verify(client, chain, "tok-a", _period("t-1", 5, 360))
        await _notify(client, chain, "REFUND", _revoked(_period("t-1", 5, 360)))
        assert (await client._store.entitlement(LINEAGE))["status"] == "refunded"
        assert await client._store.set_status(LINEAGE, "active", allow_terminal_override=True)
        await _verify(client, chain, "tok-a", _period("t-1", 5, 360))
        await _notify(client, chain, "DID_RENEW", _period("t-2", 1, 364))
        assert (await client._store.entitlement(LINEAGE))["status"] == "active"
        assert await client._store.active_tier_for(ACCOUNT_A) == "pro"
