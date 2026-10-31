"""What the docs say about the App Store's notifications is what the gateway does.

Three statements were wider than the code:

* That a renewal notice about an older transaction "changes nothing". Every
  notification's transaction is kept on the transaction ledger: a renewal
  notice about an older transaction the gateway had not recorded adds it, and
  the app posting that transaction afterwards is answered as a replay. What
  the notice leaves alone is the subscription.
* That a subscription's plan, product and expiry come from the transaction
  with the latest purchase date "the gateway has seen". They came from the
  transactions posted to /api/v1/iap/verify and the ones a renewal notice
  names; an expiry, refund or revoke notice about a newer period changed the
  status alone (tests/test_an_expiry_notice_ends_the_period_it_names.py, and
  the last test here). Now the period such a notice names is written too.
  Every other notification (an upgrade's renewal-preference change, a
  renewal-date extension) is kept on the ledger and changes nothing on the
  subscription, and a refund reversal is logged for an operator while the
  subscription stays ended.
* That a refund or revoke notice ends the subscription "even when it reaches
  the gateway before the purchase does", which held only for a product the
  gateway was already configured with; it now holds for any
  (tests/test_a_refund_kept_on_the_ledger_ends_the_subscription.py), and the
  docs say so.

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

ENTERPRISE = "com.opnmatrx.mtrx.enterprise.monthly"
LINEAGE = "1000000000000001"
ACCOUNT_A = "0x" + "a" * 40
DAY_MS = 86400 * 1000
NOW_MS = int(time.time() * 1000)

REPO = pathlib.Path(__file__).resolve().parent.parent


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


def _asn_section() -> str:
    return _between((REPO / "docs" / "api-reference.md").read_text(),
                    "### `POST /api/v1/iap/asn`", "\n## ")


def _docstring(name: str) -> str:
    from gateway.server import GatewayServer
    return _flat(getattr(GatewayServer, name).__doc__ or "")


def _store_docstring() -> str:
    import runtime.monetization.entitlement_store as store
    return _flat(store.__doc__ or "")


def test_no_doc_says_a_notice_about_an_older_transaction_changes_nothing():
    for name, text in (("docs/api-reference.md", _asn_section()),
                       ("handle_iap_asn", _docstring("handle_iap_asn"))):
        assert "older transaction changes nothing" not in text, (
            f"{name} says a notice about an older transaction changes nothing; "
            "its transaction is kept on the ledger")
        assert "kept on the ledger" in text, (
            f"{name} does not say that every notification's transaction is "
            "kept on the ledger")


def test_the_docs_name_the_transactions_a_subscription_follows():
    for name, text in (("README.md", _readme_bullet()),
                       ("docs/api-reference.md", _verify_section()),
                       ("entitlement_store", _store_docstring())):
        assert "the gateway has seen" not in text and "latest purchase date seen" not in text, (
            f"{name} says the subscription follows every transaction the gateway "
            "has seen; it follows the ones written to it")
    assert "renewal, expiry, refund or revoke notice" in _readme_bullet()
    assert "renewal, expiry, refund or revoke notice" in _store_docstring()
    assert "`SUBSCRIBED`, `DID_RENEW`, `EXPIRED`, `REFUND` or `REVOKE`" in _verify_section()
    for name, text in (("docs/api-reference.md", _asn_section()),
                       ("handle_iap_asn", _docstring("handle_iap_asn"))):
        assert "REFUND_REVERSED" in text, (
            f"{name} does not say what a refund reversal does to an ended subscription")


def test_the_docs_say_a_refund_ends_it_before_the_product_is_configured():
    assert "before the gateway knows the product" in _readme_bullet()
    for name, text in (("docs/api-reference.md", _asn_section()),
                       ("handle_iap_asn", _docstring("handle_iap_asn")),
                       ("entitlement_store", _store_docstring())):
        assert "does not know yet" in text, (
            f"{name} does not say what a refund notice about a product the "
            "gateway does not know yet does")


@pytest.fixture(scope="module")
def chain():
    return Chain()


@pytest.mark.parametrize("kind, ended", [("REFUND", "refunded"), ("REVOKE", "revoked")])
@pytest.mark.asyncio
async def test_a_refund_notice_about_a_newer_period_gives_the_record_that_period(
        aiohttp_client, tmp_path, chain, kind, ended):
    from tests.test_gateway import _build_mock_server
    server = _build_mock_server(_route_config(tmp_path, chain))
    server.wallet_sessions.get = (
        lambda token, default=None: {"address": ACCOUNT_A} if token == "tok-a" else default)
    server._entitlements = EntitlementStore(
        Database({"database": {"path": str(tmp_path / "notices.db")}}))
    client = await aiohttp_client(server.create_app())
    first = _tx_payload(transactionId="t-1", productId=PRO,
                        purchaseDate=NOW_MS - 20 * DAY_MS, expiresDate=NOW_MS + 10 * DAY_MS)
    upgrade = _tx_payload(transactionId="t-2", productId=ENTERPRISE,
                          purchaseDate=NOW_MS - DAY_MS, expiresDate=NOW_MS + 29 * DAY_MS,
                          revocationDate=NOW_MS - 1000, revocationReason=0)
    resp = await client.post("/api/v1/iap/verify", headers={"Authorization": "Bearer tok-a"},
                             json={"signedTransaction": chain.sign(first)})
    assert resp.status == 200, await resp.text()
    resp = await client.post("/api/v1/iap/asn", json=_asn(chain, kind, upgrade))
    assert resp.status == 200, await resp.text()
    row = await server._entitlements.entitlement(LINEAGE)
    assert (row["status"], row["product_id"], row["tier"]) == (ended, ENTERPRISE, "enterprise"), row
    assert row["expires_date"] == upgrade["expiresDate"] / 1000
    assert await server._entitlements.active_tier_for(ACCOUNT_A) is None
