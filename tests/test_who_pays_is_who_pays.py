"""Who pays, as the documents say it, is who pays in the code.

docs/blockchain.md used to answer "Fees" with "There are none ... Users never
pay gas on The Matrix. No exceptions. No conditions. Ever." Two kinds of
exception exist, and the page, the capability map and the README's Web3
section now name them:

* a transaction prepared for the user's own wallet is paid by that wallet.
  A bid on an auction is one: the auction service returns it PREPARED and
  UNSIGNED, with no gas, gas price or sender in it, and signs nothing;
* fees that are not gas. The marketplace records a platform fee on a sale
  (owed to the platform wallet; the sale moves nothing, so nothing collects
  it), and a DEX pool deducts its liquidity-provider fee from a swap's input.

The page said the marketplace "takes" its fee, which a sale that moves
nothing cannot do; it now says the fee is recorded. And the page ends "The
README's section on the Web3 capability surface says the same", which was
not so: the README's gas section named neither exception. It names both now,
and that sentence is held here too.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GAS_DOCS = ("docs/blockchain.md", "docs/COMPLETE_CAPABILITY_MAP.md", "README.md")
_WALLET_PAYS = re.compile(
    r"prepare[sd]? an unsigned transaction for your own wallet[^.]*your wallet pays"
    r"|prepared for your own wallet to sign[^.]*paid by your wallet",
    re.IGNORECASE)


def _flat(rel: str) -> str:
    return " ".join((REPO / rel).read_text(encoding="utf-8").split())


def _web3_section() -> str:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    start = readme.index("## Web3 Capability Surface")
    end = readme.index("\n## ", start + 1)
    return " ".join(readme[start:end].split())


class _Built:
    def __init__(self, data):
        self._data = data

    def build_transaction(self, _overrides):
        return {"data": self._data}


class _Functions:
    def createBid(self, auction_id, amount):  # noqa: N802 - the contract's name
        return _Built("0xb1d0")


class _Contract:
    functions = _Functions()


async def test_a_bid_is_prepared_for_the_bidders_wallet_and_signed_by_nothing(monkeypatch):
    from runtime.blockchain.services.auctions.service import AuctionService

    svc = AuctionService({"services": {"auctions": {"auction_address": "0x" + "11" * 20}}})
    monkeypatch.setattr(svc, "_gate_auction", lambda _method: None)
    monkeypatch.setattr(svc._web3, "load_contract", lambda *_a, **_k: _Contract())

    def _no_signing(*_a, **_k):
        raise AssertionError("a bid was signed or sent by the platform")

    monkeypatch.setattr(svc._web3, "send_transaction", _no_signing, raising=False)
    monkeypatch.setattr(svc, "_sponsor", _no_signing)

    answer = await svc.place_bid(auction_id=1, amount=10)
    assert answer["status"] == "prepared", answer
    assert answer["signing"] == "user_wallet_required"
    tx = answer["transaction"]
    assert {"gas", "gasPrice", "maxFeePerGas", "from", "nonce"}.isdisjoint(tx), (
        f"the prepared bid carries gas or a sender, so it is not the wallet's to pay: {tx}")


@pytest.mark.parametrize("rel", GAS_DOCS)
def test_each_gas_document_says_a_prepared_transaction_is_the_wallets_to_pay(rel):
    text = _web3_section() if rel == "README.md" else _flat(rel)
    assert _WALLET_PAYS.search(text), (
        f"{rel} does not say that a transaction prepared for the user's own "
        "wallet is paid by that wallet, and the auction service prepares one")


async def test_a_marketplace_fee_is_recorded_not_taken():
    from runtime.blockchain.services.marketplace.service import MarketplaceService

    svc = MarketplaceService({})
    listing = await svc.list_item("0xSELLER", "digital", {"title": "t"}, 1.0)
    sale = await svc.buy_item(listing["listing_id"], "0xBUYER")
    assert sale["platform_fee"] > 0, "precondition: the sale carries a platform fee"
    assert sale["value_moved"] is False, "precondition: the sale moves nothing"
    for rel in ("docs/blockchain.md", "README.md"):
        text = _flat(rel)
        assert not re.search(r"marketplace (takes|collects|deducts) (a|its) (platform )?fee",
                             text, re.IGNORECASE), (
            f"{rel} says the marketplace takes its fee, and a sale moves nothing")
    assert re.search(r"marketplace records a platform fee on a sale", _flat("docs/blockchain.md"))


def test_the_readme_says_what_the_fees_page_says_it_says():
    page = _flat("docs/blockchain.md")
    assert "The README's section on the Web3 capability surface says the same." in page, (
        "precondition: the fees page points at the README")
    section = _web3_section()
    for fact in ("liquidity-provider fee", "marketplace records a platform fee"):
        assert fact in page, f"precondition: the fees page states {fact!r}"
        assert fact in section, (
            f"docs/blockchain.md says the README's Web3 section says the same, "
            f"and that section does not mention the {fact}")
