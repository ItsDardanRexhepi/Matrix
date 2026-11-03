"""A refund or a revocation ends a subscription whichever of its periods it names.

The gateway ends a subscription on the App Store's refund or revoke notice, and
on a transaction that carries the date the App Store revoked it, whatever the
date of the period the refund names, and an ended subscription stays ended
(tests/test_a_refund_ends_the_subscription_whichever_arrives_first.py). Two
statements in the docs were short of that or wider than it:

* The README and the API reference said a refund ends the subscription and that
  an ended subscription stays ended. Neither said that a refund of an earlier
  period ends a later one already paid for, or that a later period bought or
  renewed after the refund does not make the subscription active again. Both
  hold, and the checks below hold them.
* The README said an expiry notice about a transaction older than the newest
  one "changes nothing". It does not expire the subscription, and its
  transaction is kept on the ledger, so the app posting that transaction
  afterwards is answered as a replay.

The JWS fixture chain and the route configuration are tests/test_iap_verify.py's.
"""

from __future__ import annotations

import pathlib
import time

import pytest

pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from runtime.db.database import Database  # noqa: E402
from runtime.monetization.entitlement_store import EntitlementStore  # noqa: E402
from tests.test_iap_verify import PRO, Chain, _asn, _route_config, _tx_payload  # noqa: E402

LINEAGE = "1000000000000001"
ACCOUNT_A = "0x" + "a" * 40
TOKENS = {"tok-a": {"address": ACCOUNT_A}}
DAY_MS = 86400 * 1000
NOW_MS = int(time.time() * 1000)

REPO = pathlib.Path(__file__).resolve().parent.parent


def _period(transaction_id, started_days_ago, ends_days_from_now):
    return _tx_payload(transactionId=transaction_id, productId=PRO,
                       purchaseDate=NOW_MS - started_days_ago * DAY_MS,
                       expiresDate=NOW_MS + ends_days_from_now * DAY_MS)


# t-1 and t-2 are months that ended; t-3 is the month paid for now; t-5 is a
# month bought after it, today.
T1 = _period("t-1", 70, -40)
T2 = _period("t-2", 40, -10)
T3 = _period("t-3", 10, 20)
T5 = _period("t-5", 0, 30)


def _revoked(payload):
    return dict(payload, revocationDate=NOW_MS - 1000, revocationReason=0)


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
        Database({"database": {"path": str(tmp_path / "any-period.db")}}))
    client = await aiohttp_client(server.create_app())
    client._store = server._entitlements
    return client


async def _verify(client, chain, token, payload):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = await client.post("/api/v1/iap/verify", headers=headers,
                             json={"signedTransaction": chain.sign(payload)})
    assert resp.status == 200, await resp.text()
    return await resp.json()


async def _notify(client, chain, kind, payload):
    resp = await client.post("/api/v1/iap/asn", json=_asn(chain, kind, payload))
    assert resp.status == 200, await resp.text()


async def _status_and_plan(client):
    row = await client._store.entitlement(LINEAGE)
    return row["status"], await client._store.active_tier_for(ACCOUNT_A)


class TestARefundOfAnEarlierPeriod:
    """Each held before the docs said it, and holds after."""

    @pytest.mark.asyncio
    async def test_the_notice_ends_the_period_paid_for_now(self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        await _verify(client, chain, "tok-a", T1)
        await _verify(client, chain, "tok-a", T3)
        assert await _status_and_plan(client) == ("active", "pro")
        await _notify(client, chain, "REFUND", _revoked(T1))
        assert await _status_and_plan(client) == ("refunded", None)
        await _verify(client, chain, "tok-a", T3)
        assert await _status_and_plan(client) == ("refunded", None)

    @pytest.mark.asyncio
    async def test_its_revoked_transaction_posted_by_the_holder_ends_it(
            self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        await _verify(client, chain, "tok-a", T3)
        await _verify(client, chain, "tok-a", _revoked(T1))
        assert await _status_and_plan(client) == ("revoked", None)


class TestALaterPeriodAfterARefund:
    """Held before the docs said it, and holds after."""

    @pytest.mark.parametrize("kind", ["SUBSCRIBED", "DID_RENEW"])
    @pytest.mark.asyncio
    async def test_bought_or_renewed_it_leaves_the_subscription_ended(
            self, aiohttp_client, tmp_path, chain, kind):
        client = await _client(aiohttp_client, tmp_path, chain)
        await _verify(client, chain, "tok-a", T3)
        await _notify(client, chain, "REFUND", _revoked(T3))
        await _notify(client, chain, kind, T5)
        await _verify(client, chain, "tok-a", T5)
        row = await client._store.entitlement(LINEAGE)
        assert (row["status"], row["expires_date"]) == ("refunded", T5["expiresDate"] / 1000), row
        assert await client._store.active_tier_for(ACCOUNT_A) is None


class TestAnExpiryNoticeAboutAnOlderTransaction:
    """Held before the docs said it, and holds after."""

    @pytest.mark.asyncio
    async def test_it_does_not_expire_the_subscription_and_is_kept_on_the_ledger(
            self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        await _verify(client, chain, "tok-a", T3)
        await _notify(client, chain, "EXPIRED", T2)
        assert await _status_and_plan(client) == ("active", "pro")
        assert (await _verify(client, chain, "tok-a", T2))["replay"] is True
        assert await _status_and_plan(client) == ("active", "pro")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return _flat(text[i:text.index(end, i + len(start))])


def _readme_bullet() -> str:
    return _between((REPO / "README.md").read_text(),
                    "**A subscription follows its newest transaction.**", "\n- **")


def _verify_section() -> str:
    return _between((REPO / "docs" / "api-reference.md").read_text(),
                    "### `POST /api/v1/iap/verify`", "### `POST /api/v1/iap/asn`")


def test_the_readme_does_not_say_an_older_expiry_notice_changes_nothing():
    bullet = _readme_bullet()
    assert "older than the newest one changes nothing" not in bullet, (
        "README.md says an expiry notice about an older transaction changes "
        "nothing; its transaction is kept on the ledger")
    assert "older than the newest one does not expire the subscription" in bullet, (
        "README.md does not say what an expiry notice about an older transaction "
        "leaves alone")


def test_the_docs_say_a_refund_of_an_earlier_period_ends_the_one_paid_for_now():
    for name, text in (("README.md", _readme_bullet()),
                       ("docs/api-reference.md", _verify_section())):
        assert "a refund of an earlier period ends a later one already paid for" in text, (
            f"{name} does not say that a refund of an earlier period ends the "
            "period paid for now")


def test_the_docs_say_a_later_period_leaves_an_ended_subscription_ended():
    assert "also when a later period of it is bought or renewed" in _readme_bullet(), (
        "README.md does not say that a later period bought or renewed leaves an "
        "ended subscription ended")
    assert ("also when a later period is posted or named in a `SUBSCRIBED` or "
            "`DID_RENEW` notification") in _verify_section(), (
        "docs/api-reference.md does not say that a later period leaves an ended "
        "subscription ended")
