"""What the docs say about who holds an App Store purchase is what the route answers.

Three statements in the docs of the purchase rule were wider than the gateway:

* That the account holding a purchase presents it again "from any of its
  sessions". A purchase is held by the subject of the session that verified
  it: an Apple sign-in (``apple:<sub>``) or a wallet. Elsewhere the gateway
  treats an Apple sign-in and the wallet linked to it as one caller, yet a
  purchase verified under one of them is answered ``409`` from the other, in
  either order. The docs now say that an Apple sign-in and its linked wallet
  are two accounts here, and the first test holds the route to it. Whether
  they should hold a purchase together is a decision of its own; when the
  route changes, these words change with it.
* That replaying a transaction "records nothing new". A replay from another
  account is refused, and one from the holder rewrote the subscription from
  the replayed transaction (tests/test_an_older_transaction_takes_nothing_back.py).
  The docs now say a replay adds no ledger row and moves nothing back.
* That a purchase belongs to the first account that verified it, with no word
  about records an earlier version of the gateway wrote. That version moved a
  subscription to whichever account presented it last, and nothing here moves
  a bound subscription, so a database it wrote can hold one with that
  account. The docs now say so.

The JWS fixture chain and the route configuration are tests/test_iap_verify.py's.
"""

from __future__ import annotations

import pathlib

import pytest

pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from runtime.db.database import Database  # noqa: E402
from runtime.monetization.entitlement_store import EntitlementStore  # noqa: E402
from tests.test_iap_verify import Chain, _route_config, _tx_payload  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
WALLET = "0x" + "c" * 40
TOKENS = {"tok-apple": {"address": "apple:sub-1"}, "tok-wallet": {"address": WALLET}}


def _flat(text: str) -> str:
    return " ".join(text.split())


def _between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return _flat(text[i:text.index(end, i + len(start))])


def _readme_bullet() -> str:
    return _between((REPO / "README.md").read_text(),
                    "**An App Store purchase belongs to the account", "\n- **")


def _api_reference_section() -> str:
    return _between((REPO / "docs" / "api-reference.md").read_text(),
                    "### `POST /api/v1/iap/verify`", "### `POST /api/v1/iap/asn`")


def _verify_docstring() -> str:
    from gateway.server import GatewayServer
    return _flat(GatewayServer.handle_iap_verify.__doc__ or "")


def _store_docstring() -> str:
    import runtime.monetization.entitlement_store as store
    return _flat(store.__doc__ or "")


@pytest.fixture(scope="module")
def chain():
    return Chain()


async def _client(aiohttp_client, tmp_path, chain):
    from tests.test_gateway import _build_mock_server
    cfg = _route_config(tmp_path, chain)
    server = _build_mock_server(cfg)
    server.wallet_sessions.get = lambda token, default=None: TOKENS.get(token, default)
    # The Apple user sub-1 linked WALLET (POST /auth/verify while holding the
    # Apple session): the gateway's caller identity of both sessions is WALLET.
    server.apple_users.wallet_for = lambda sub: WALLET if sub == "sub-1" else ""
    server._entitlements = EntitlementStore(
        Database({"database": {"path": str(tmp_path / "rule.db")}}))
    return await aiohttp_client(server.create_app())


async def _post(client, chain, token, payload):
    return await client.post("/api/v1/iap/verify",
                             headers={"Authorization": f"Bearer {token}"},
                             json={"signedTransaction": chain.sign(payload)})


@pytest.mark.parametrize("first, second", [("tok-apple", "tok-wallet"),
                                           ("tok-wallet", "tok-apple")])
@pytest.mark.asyncio
async def test_an_apple_sign_in_and_its_linked_wallet_are_answered_as_two_accounts(
        aiohttp_client, tmp_path, chain, first, second):
    """The route as the docs below describe it (it answered this way before
    the docs said so)."""
    client = await _client(aiohttp_client, tmp_path, chain)
    assert (await _post(client, chain, first, _tx_payload())).status == 200
    other = await _post(client, chain, second, _tx_payload())
    assert other.status == 409, await other.text()
    assert (await other.json())["error"] == "bound_to_another_account"


def test_the_docs_say_an_apple_sign_in_and_its_linked_wallet_are_two_accounts():
    for name, text in (("README.md", _readme_bullet()),
                       ("docs/api-reference.md", _api_reference_section()),
                       ("handle_iap_verify", _verify_docstring()),
                       ("entitlement_store", _store_docstring())):
        assert "any of its sessions" not in text, (
            f"{name} says the holder presents a purchase from any of its sessions; "
            "the wallet linked to an Apple sign-in is answered 409")
        assert "the wallet linked to it are two" in text, (
            f"{name} does not say that an Apple sign-in and the wallet linked to "
            "it are two accounts here")


def test_no_doc_says_a_replay_records_nothing_new():
    for name, text in (("docs/api-reference.md", _api_reference_section()),
                       ("handle_iap_verify", _verify_docstring()),
                       ("entitlement_store", _store_docstring())):
        assert "records nothing new" not in text.lower(), (
            f"{name} says a replay records nothing new")
    for name, text in (("docs/api-reference.md", _api_reference_section()),
                       ("handle_iap_verify", _verify_docstring())):
        assert "adds no ledger row" in text, (
            f"{name} does not say what a replay leaves unwritten")


def test_the_docs_say_what_an_earlier_version_left():
    for name, text in (("README.md", _readme_bullet()),
                       ("docs/api-reference.md", _api_reference_section()),
                       ("entitlement_store", _store_docstring())):
        assert "earlier version" in text and "presented it last" in text, (
            f"{name} states the first-verifier rule with no word on a "
            "subscription an earlier version moved to the account that "
            "presented it last")
