"""A refund or a revocation ends a subscription whichever reaches the gateway first.

The App Store's refund and revoke notices ended the subscription record only
when the record already existed. A notice that arrived before any account had
verified the purchase (Apple sends it when it decides, and the app posts the
transaction when it next runs) was kept only on the transaction ledger, and
the verify that came after it wrote the subscription active. A transaction
carrying the date the App Store revoked it was written active too: the date
was read from the payload and never used.

The rule now: a refund or revoke notice about a subscription no record holds
yet writes the subscription already ended, so a later verify keeps it ended;
and a transaction that carries a revocation date ends its subscription, and is
marked revoked on the ledger, whoever posts it and in whatever order. Ended is
terminal, as it was: nothing a later post or notice says takes it back to
active.

The JWS fixture chain and the route configuration are tests/test_iap_verify.py's.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from runtime.db.database import Database  # noqa: E402
from runtime.monetization.entitlement_store import EntitlementStore  # noqa: E402
from tests.test_iap_verify import REDOS, Chain, _asn, _route_config, _tx_payload  # noqa: E402

LINEAGE = "1000000000000001"
FIRST_TX = "2000000000000001"
ACCOUNT_A = "0x" + "a" * 40
TOKENS = {"tok-a": {"address": ACCOUNT_A}}


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
        Database({"database": {"path": str(tmp_path / "refund.db")}}))
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


def _revoked(payload):
    return dict(payload, revocationDate=int(time.time() * 1000) - 1000,
                revocationReason=0)


class TestANoticeBeforeAnyVerify:
    @pytest.mark.parametrize("kind, ended", [("REFUND", "refunded"), ("REVOKE", "revoked")])
    @pytest.mark.asyncio
    async def test_the_verify_after_it_keeps_the_subscription_ended(
            self, aiohttp_client, tmp_path, chain, kind, ended):
        client = await _client(aiohttp_client, tmp_path, chain)
        purchase = _tx_payload()
        await _notify(client, chain, kind, _revoked(purchase))
        await _verify(client, chain, "tok-a", purchase)
        row = await client._store.entitlement(LINEAGE)
        assert (row["status"], row["user_key"]) == (ended, ACCOUNT_A), row
        assert await client._store.active_tier_for(ACCOUNT_A) is None

    @pytest.mark.asyncio
    async def test_a_consumables_refund_writes_no_subscription(self, aiohttp_client, tmp_path, chain):
        """Boundary guard (it held before the rule too): a consumable has no
        subscription to end; its ledger row says refunded."""
        client = await _client(aiohttp_client, tmp_path, chain)
        redo = _tx_payload(productId=REDOS, transactionId="t-redo",
                           originalTransactionId="t-redo", expiresDate=None,
                           type="Consumable")
        await _notify(client, chain, "REFUND", redo)
        await _verify(client, chain, "tok-a", redo)
        assert await client._store.entitlement("t-redo") is None
        assert (await client._store.transaction("t-redo"))["status"] == "refunded"


class TestATransactionCarryingItsRevocation:
    @pytest.mark.asyncio
    async def test_posted_first_is_recorded_ended(self, aiohttp_client, tmp_path, chain):
        client = await _client(aiohttp_client, tmp_path, chain)
        await _verify(client, chain, "tok-a", _revoked(_tx_payload()))
        assert (await client._store.entitlement(LINEAGE))["status"] == "revoked"
        assert (await client._store.transaction(FIRST_TX))["status"] == "revoked"
        assert await client._store.active_tier_for(ACCOUNT_A) is None

    @pytest.mark.asyncio
    async def test_posted_after_the_purchase_ends_it(self, aiohttp_client, tmp_path, chain):
        """With no notice configured, the app's own report of the revoked
        transaction is how the gateway learns of it."""
        client = await _client(aiohttp_client, tmp_path, chain)
        purchase = _tx_payload()
        await _verify(client, chain, "tok-a", purchase)
        assert await client._store.active_tier_for(ACCOUNT_A) == "pro"
        await _verify(client, chain, None, _revoked(purchase))
        row = await client._store.entitlement(LINEAGE)
        assert (row["status"], row["user_key"]) == ("revoked", ACCOUNT_A), row
        assert (await client._store.transaction(FIRST_TX))["status"] == "revoked"
        assert await client._store.active_tier_for(ACCOUNT_A) is None

    @pytest.mark.asyncio
    async def test_a_newer_transaction_does_not_lift_it(self, aiohttp_client, tmp_path, chain):
        """Ended stays ended (tests/test_iap_verify.py holds the same for a
        refund notice)."""
        client = await _client(aiohttp_client, tmp_path, chain)
        await _verify(client, chain, "tok-a", _revoked(_tx_payload()))
        later = int(time.time() * 1000) + 1000
        await _verify(client, chain, "tok-a", _tx_payload(
            transactionId="t-next", purchaseDate=later,
            expiresDate=later + 30 * 86400 * 1000))
        assert (await client._store.entitlement(LINEAGE))["status"] == "revoked"
        assert await client._store.active_tier_for(ACCOUNT_A) is None
