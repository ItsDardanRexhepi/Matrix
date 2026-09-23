"""An IAP replay records nothing new, and an early refund is not lost.

`runtime/monetization/entitlement_store.py` makes two promises:

  * "replaying the same signed transaction ... records NOTHING new". The
    ledger row was not duplicated, but /iap/verify upserted the entitlement on
    every call, replay or not — so posting someone's signed transaction again
    under your own session rebound the lineage to your user key, and a replay
    wrote `active` over an EXPIRED row;
  * "fail-closed means toward less entitlement, never more". A REFUND (or
    REVOKE) notification that arrived before the lineage had a row found
    nothing to flip, was answered 200 — so Apple never resent it — and the
    next /verify of that lineage created the row `active`.

And the SDK says "any verification failure -> 401": a JWS whose header
segment is JSON but not an object reached `header.get` and answered 500.
"""

from __future__ import annotations

import base64

import pytest

pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from runtime.db.database import Database  # noqa: E402
from runtime.monetization.entitlement_store import EntitlementStore  # noqa: E402
from tests.test_iap_verify import (  # noqa: E402
    Chain,
    _asn,
    _route_config,
    _tx_payload,
)


@pytest.fixture(scope="module")
def chain():
    return Chain()


@pytest.fixture
async def gateway(aiohttp_client, tmp_path, chain):
    from tests.test_gateway import _build_mock_server

    server = _build_mock_server(_route_config(tmp_path, chain))
    server._entitlements = EntitlementStore(
        Database({"database": {"path": str(tmp_path / "iap.db")}}))
    session = {"address": ""}
    server._wallet_session_from_request = (
        lambda request: {"address": session["address"]} if session["address"] else None)
    client = await aiohttp_client(server.create_app())
    return client, server._entitlements, session


async def test_a_replay_under_another_session_does_not_rebind_the_lineage(gateway, chain):
    client, store, session = gateway
    jws = chain.sign(_tx_payload())

    session["address"] = "0xBUYER"
    assert (await client.post("/api/v1/iap/verify",
                              json={"signedTransaction": jws})).status == 200
    session["address"] = "0xREPLAYER"
    r = await client.post("/api/v1/iap/verify", json={"signedTransaction": jws})
    assert (await r.json())["replay"] is True

    ent = await store.entitlement("1000000000000001")
    assert ent["user_key"] == "0xBUYER", (
        "replaying the buyer's signed transaction moved their subscription "
        f"to the replayer's session: {ent['user_key']}")


async def test_a_replay_does_not_lift_an_expired_row(gateway, chain):
    client, store, _ = gateway
    jws = chain.sign(_tx_payload())
    await client.post("/api/v1/iap/verify", json={"signedTransaction": jws})
    await store.set_status("1000000000000001", "expired")

    await client.post("/api/v1/iap/verify", json={"signedTransaction": jws})
    assert (await store.entitlement("1000000000000001"))["status"] == "expired"


async def test_a_replay_still_writes_an_entitlement_that_is_missing(gateway, chain):
    """SCOPE PIN: the first attempt recorded the transaction and failed before
    the entitlement row; the retry must not strand the purchase."""
    client, store, _ = gateway
    tx = _tx_payload()
    await store.record_transaction(
        transaction_id=tx["transactionId"],
        original_transaction_id=tx["originalTransactionId"],
        product_id=tx["productId"], product_type="subscription")
    assert await store.entitlement(tx["originalTransactionId"]) is None

    r = await client.post("/api/v1/iap/verify",
                          json={"signedTransaction": chain.sign(tx)})
    assert (await r.json())["replay"] is True
    assert (await store.entitlement(tx["originalTransactionId"]))["status"] == "active"


@pytest.mark.parametrize("kind,terminal", [("REFUND", "refunded"), ("REVOKE", "revoked")])
async def test_a_refund_that_arrives_first_is_not_lost(gateway, chain, kind, terminal):
    client, store, _ = gateway
    tx = _tx_payload(transactionId=f"t-{kind}", originalTransactionId=f"o-{kind}")
    r = await client.post("/api/v1/iap/asn", json=_asn(chain, kind, tx))
    assert r.status == 200

    await client.post("/api/v1/iap/verify", json={"signedTransaction": chain.sign(tx)})
    ent = await store.entitlement(f"o-{kind}")
    assert ent is not None and ent["status"] == terminal, (
        f"a {kind} that arrived before the lineage's row was dropped, and the "
        f"next verify entitled: {ent}")


async def test_a_header_that_is_not_an_object_is_a_401_not_a_500(gateway):
    client, _, _ = gateway

    def seg(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    jws = ".".join([seg(b"[1, 2, 3]"), seg(b"{}"), seg(b"sig")])
    r = await client.post("/api/v1/iap/verify", json={"signedTransaction": jws})
    assert r.status == 401, f"a malformed header answered {r.status}"
