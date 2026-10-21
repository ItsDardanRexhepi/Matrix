"""A subscription follows the newest transaction the gateway has seen.

The subscription record took the product, the plan, the expiry and the status
of whichever transaction reached it last. A transaction the App Store signed
still verifies after its subscription renews, so anyone holding an older
one's bytes could post it with no session and move the subscription back: a
renewed subscription to its lapsed expiry (the plan went to none), an upgraded
one to the plan it had before. The holder's own restore did the same when it
posted an older transaction after a newer one, and so did the App Store's
notifications, which arrive in no guaranteed order: a late renewal notice
about an older transaction, or an expiry notice about the transaction before
a resubscription. Posting the latest transaction again after the App Store
said it expired set the record back to active.

The rule now: the product, the plan, the expiry and the environment come from
the transaction with the latest purchase date the gateway has seen, and an
older one changes none of them. Only a newer transaction takes an expired
subscription back to active, and an expiry notice about a transaction older
than the newest one changes nothing. A refund or a revocation still ends the
subscription whatever the date of the transaction it names
(tests/test_a_refund_ends_the_subscription_whichever_arrives_first.py).

The JWS fixture chain and the route configuration are tests/test_iap_verify.py's.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from runtime.db.database import Database  # noqa: E402
from runtime.monetization.entitlement_store import EntitlementStore  # noqa: E402
from tests.test_iap_verify import PRO, Chain, _asn, _route_config, _tx_payload  # noqa: E402

ENTERPRISE = "com.opnmatrx.mtrx.enterprise.monthly"
LINEAGE = "1000000000000001"
ACCOUNT_A = "0x" + "a" * 40
TOKENS = {"tok-a": {"address": ACCOUNT_A}}
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
        Database({"database": {"path": str(tmp_path / "order.db")}}))
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


def _lapsed_and_renewed():
    """t-1 lapsed ten days ago; its renewal t-2 runs twenty more days."""
    now = int(time.time() * 1000)
    return (_tx_payload(transactionId="t-1", purchaseDate=now - 40 * DAY_MS,
                        expiresDate=now - 10 * DAY_MS),
            _tx_payload(transactionId="t-2", purchaseDate=now - 10 * DAY_MS,
                        expiresDate=now + 20 * DAY_MS))


class TestAnOlderTransactionPosted:
    @pytest.mark.asyncio
    async def test_with_no_session_leaves_the_holders_plan(self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        lapsed, renewed = _lapsed_and_renewed()
        await _verify(client, chain, "tok-a", lapsed)
        await _verify(client, chain, "tok-a", renewed)
        await _verify(client, chain, None, lapsed)
        row = await client._store.entitlement(LINEAGE)
        assert row["expires_date"] > time.time() + 19 * 86400, row
        assert await client._store.active_tier_for(ACCOUNT_A) == "pro"

    @pytest.mark.asyncio
    async def test_from_the_holders_own_restore_leaves_its_plan(self, aiohttp_client, tmp_path, chain):
        """A restore hands over transactions in no promised order."""
        client = await _client(aiohttp_client, tmp_path, chain)
        lapsed, renewed = _lapsed_and_renewed()
        await _verify(client, chain, "tok-a", renewed)
        await _verify(client, chain, "tok-a", lapsed)
        assert await client._store.active_tier_for(ACCOUNT_A) == "pro"

    @pytest.mark.asyncio
    async def test_from_before_an_upgrade_does_not_undo_it(self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        now = int(time.time() * 1000)
        pro = _tx_payload(transactionId="t-pro", productId=PRO,
                          purchaseDate=now - 5 * DAY_MS, expiresDate=now + 25 * DAY_MS)
        upgraded = _tx_payload(transactionId="t-ent", productId=ENTERPRISE,
                               purchaseDate=now - DAY_MS, expiresDate=now + 29 * DAY_MS)
        await _verify(client, chain, "tok-a", pro)
        await _verify(client, chain, "tok-a", upgraded)
        await _verify(client, chain, None, pro)
        row = await client._store.entitlement(LINEAGE)
        assert (row["product_id"], row["tier"]) == (ENTERPRISE, "enterprise"), row
        assert await client._store.active_tier_for(ACCOUNT_A) == "enterprise"

    @pytest.mark.asyncio
    async def test_the_latest_one_again_after_it_expired_leaves_it_expired(
            self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        latest = _tx_payload(transactionId="t-1")
        await _verify(client, chain, "tok-a", latest)
        await _notify(client, chain, "EXPIRED", latest)
        resp = await _verify(client, chain, "tok-a", latest)
        assert (await resp.json())["replay"] is True
        assert (await client._store.entitlement(LINEAGE))["status"] == "expired"
        assert await client._store.active_tier_for(ACCOUNT_A) is None


class TestTheAppStoresNoticesOutOfOrder:
    @pytest.mark.asyncio
    async def test_a_late_renewal_notice_about_an_older_transaction_changes_nothing(
            self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        lapsed, renewed = _lapsed_and_renewed()
        await _verify(client, chain, "tok-a", lapsed)
        await _notify(client, chain, "DID_RENEW", renewed)
        await _notify(client, chain, "DID_RENEW", lapsed)
        row = await client._store.entitlement(LINEAGE)
        assert (row["status"], row["user_key"]) == ("active", ACCOUNT_A), row
        assert await client._store.active_tier_for(ACCOUNT_A) == "pro"

    @pytest.mark.asyncio
    async def test_a_late_expiry_notice_about_the_transaction_before_a_resubscription_changes_nothing(
            self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        lapsed, resubscribed = _lapsed_and_renewed()
        await _verify(client, chain, "tok-a", lapsed)
        await _notify(client, chain, "SUBSCRIBED", resubscribed)
        await _notify(client, chain, "EXPIRED", lapsed)
        assert (await client._store.entitlement(LINEAGE))["status"] == "active"
        assert await client._store.active_tier_for(ACCOUNT_A) == "pro"


class TestANewerTransactionStillMovesIt:
    """Boundary guards: each held before the rule and holds after it."""

    @pytest.mark.asyncio
    async def test_a_renewal_after_an_expiry_takes_it_back_to_active(
            self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        lapsed, renewed = _lapsed_and_renewed()
        await _verify(client, chain, "tok-a", lapsed)
        await _notify(client, chain, "EXPIRED", lapsed)
        assert await client._store.active_tier_for(ACCOUNT_A) is None
        await _verify(client, chain, "tok-a", renewed)
        row = await client._store.entitlement(LINEAGE)
        assert row["status"] == "active", row
        assert row["expires_date"] > time.time() + 19 * 86400
        assert await client._store.active_tier_for(ACCOUNT_A) == "pro"

    @pytest.mark.asyncio
    async def test_an_upgrade_and_a_later_downgrade_each_take_effect(
            self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        now = int(time.time() * 1000)
        steps = ((PRO, 20, "pro"), (ENTERPRISE, 10, "enterprise"), (PRO, 1, "pro"))
        for n, (product, days_ago, tier) in enumerate(steps):
            await _notify(client, chain, "DID_RENEW", _tx_payload(
                transactionId=f"t-{n}", productId=product,
                purchaseDate=now - days_ago * DAY_MS,
                expiresDate=now + (30 - days_ago) * DAY_MS))
            row = await client._store.entitlement(LINEAGE)
            assert row["tier"] == tier, (n, row)

    @pytest.mark.asyncio
    async def test_an_expiry_notice_with_no_purchase_date_still_expires_it(
            self, aiohttp_client, tmp_path, chain):
        """A notice that names no purchase date cannot be shown to be about
        an older transaction, so it is applied."""
        client = await _client(aiohttp_client, tmp_path, chain)
        await _verify(client, chain, "tok-a", _tx_payload())
        await _notify(client, chain, "EXPIRED", _tx_payload(purchaseDate=None))
        assert (await client._store.entitlement(LINEAGE))["status"] == "expired"
