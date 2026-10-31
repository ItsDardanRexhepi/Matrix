"""An App Store expiry notice ends the period it names, posted or not.

The expiry notice changed only the subscription record's status. When it named
a period the app had not posted yet (the app had not run since the renewal,
and no renewal notice had reached the gateway), the record kept the plan and
the expiry of the period before it, and the app posting the period that had
expired, as a restore does, counted as a newer transaction and set the record
back to active: active, with an expiry already past.

The rule now: the notice's period is written to the record as any newer
transaction is, already expired, so posting that period afterwards, or the App
Store sending its renewal notice again, leaves it expired; only a later period
makes it active again. A notice about a period older than the one the record
holds changes nothing, as before
(tests/test_an_older_transaction_takes_nothing_back.py).

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
NOW_MS = int(time.time() * 1000)


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
        Database({"database": {"path": str(tmp_path / "expiry.db")}}))
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


def _period(transaction_id, started_days_ago, ends_ms_from_now, product=PRO):
    return _tx_payload(transactionId=transaction_id, productId=product,
                       purchaseDate=NOW_MS - started_days_ago * DAY_MS,
                       expiresDate=NOW_MS + ends_ms_from_now)


# t-1 ended thirty days ago; t-2, its renewal, ended a minute ago; t-3 is the
# period after that, bought today.
T1 = _period("t-1", 60, -30 * DAY_MS)
T2 = _period("t-2", 30, -60 * 1000)
T3 = _period("t-3", 0, 30 * DAY_MS)


class TestAnExpiryNoticeAboutAPeriodNotPostedYet:
    @pytest.mark.asyncio
    async def test_posting_that_period_afterwards_leaves_it_expired(
            self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        await _verify(client, chain, "tok-a", T1)
        await _notify(client, chain, "EXPIRED", T2)
        await _verify(client, chain, "tok-a", T2)
        row = await client._store.entitlement(LINEAGE)
        assert (row["status"], row["user_key"]) == ("expired", ACCOUNT_A), row
        await _notify(client, chain, "DID_RENEW", T2)
        assert (await client._store.entitlement(LINEAGE))["status"] == "expired"
        assert await client._store.active_tier_for(ACCOUNT_A) is None

    @pytest.mark.asyncio
    async def test_the_record_takes_that_periods_plan_and_expiry(
            self, aiohttp_client, tmp_path, chain):
        """The period that expired was an upgrade: the record says which plan
        ended and when."""
        client = await _client(aiohttp_client, tmp_path, chain)
        await _verify(client, chain, "tok-a", T1)
        upgraded = _period("t-2", 30, -60 * 1000, product=ENTERPRISE)
        await _notify(client, chain, "EXPIRED", upgraded)
        row = await client._store.entitlement(LINEAGE)
        assert (row["status"], row["product_id"], row["tier"]) == (
            "expired", ENTERPRISE, "enterprise"), row
        assert row["expires_date"] == upgraded["expiresDate"] / 1000

    @pytest.mark.asyncio
    async def test_a_notice_before_any_verify_writes_it_expired(
            self, aiohttp_client, tmp_path, chain):
        """No record yet: the notice writes one, expired and held by no
        account; the account that posts the period takes it, still expired."""
        client = await _client(aiohttp_client, tmp_path, chain)
        await _notify(client, chain, "EXPIRED", T2)
        row = await client._store.entitlement(LINEAGE)
        assert row is not None, "the expiry notice wrote no subscription record"
        assert (row["status"], row["user_key"]) == ("expired", ""), row
        await _verify(client, chain, "tok-a", T2)
        row = await client._store.entitlement(LINEAGE)
        assert (row["status"], row["user_key"]) == ("expired", ACCOUNT_A), row


class TestWhatAnExpiryNoticeLeavesAlone:
    """Boundary guards: each held before the rule and holds after it."""

    @pytest.mark.asyncio
    async def test_the_period_after_it_makes_it_active_again(self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        await _verify(client, chain, "tok-a", T1)
        await _notify(client, chain, "EXPIRED", T2)
        await _verify(client, chain, "tok-a", T3)
        assert (await client._store.entitlement(LINEAGE))["status"] == "active"
        assert await client._store.active_tier_for(ACCOUNT_A) == "pro"

    @pytest.mark.asyncio
    async def test_a_notice_about_an_older_period_changes_nothing(
            self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        await _verify(client, chain, "tok-a", T3)
        before = dict(await client._store.entitlement(LINEAGE))
        await _notify(client, chain, "EXPIRED", T2)
        after = dict(await client._store.entitlement(LINEAGE))
        assert {k: v for k, v in after.items() if k != "updated_at"} == \
            {k: v for k, v in before.items() if k != "updated_at"}
        assert await client._store.active_tier_for(ACCOUNT_A) == "pro"

    @pytest.mark.asyncio
    async def test_an_ended_subscription_stays_ended(self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        await _verify(client, chain, "tok-a", T1)
        await _notify(client, chain, "REFUND", dict(T1, revocationDate=NOW_MS - 1000))
        await _notify(client, chain, "EXPIRED", T2)
        assert (await client._store.entitlement(LINEAGE))["status"] == "refunded"
