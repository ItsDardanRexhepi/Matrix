"""The platform's own royalty write is not always to a fresh key.

`create_collection` said: "These two sites each write a FRESH key so the 22-A
authority check cannot refuse them", and `RoyaltyEnforcement.configure_royalty`
said its two in-package writers each create a fresh key, "so neither is
refused". `configure_nft_royalty` accepts any collection and token id from a
caller, so an entry can exist before the collection or token does. For `mint`
this was found and caught earlier. For `create_collection` the comment stayed,
and so did the bare call: a collection default registered in advance made the
platform's own write raise PermissionError after the factory had deployed the
contract, and the caller was told the call failed.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.nft_services.service import NFTService

_CREATOR = "0x" + "1" * 40
_STRANGER = "0x" + "9" * 40
_COLLECTION = "0x" + "c" * 40


class _Factory:
    def __init__(self) -> None:
        self.deployed: list[str] = []
        self.minted: list[int] = []

    async def deploy_erc721(self, **_kw):
        self.deployed.append(_COLLECTION)
        return {"collection_address": _COLLECTION, "status": "deployed"}

    async def mint_token(self, **_kw):
        self.minted.append(1)
        return {"token_id": 1, "status": "minted"}


def _svc() -> tuple[NFTService, _Factory]:
    svc = NFTService({})
    factory = _Factory()
    svc._factory = factory
    return svc, factory


async def test_a_collection_default_registered_in_advance_does_not_fail_the_deploy():
    """THE REPRODUCTION."""
    svc, factory = _svc()
    await svc._royalty.configure_royalty(
        collection=_COLLECTION, token_id=-1, recipient=_STRANGER, bps=1000)
    out = await svc.create_collection(
        creator=_CREATOR, name="Drop", symbol="DRP", collection_type="erc721")
    assert factory.deployed == [_COLLECTION], "premise: the collection was deployed"
    assert out["collection_address"] == _COLLECTION
    assert out["royalty_configured"] is False, out
    assert "NOT configured" in out["disclosure"], out


async def test_a_token_registered_in_advance_does_not_fail_the_mint():
    """The same site in `mint`, which already caught it: held here too."""
    svc, factory = _svc()
    await svc._royalty.configure_royalty(
        collection=_COLLECTION, token_id=1, recipient=_STRANGER, bps=1000)
    out = await svc.mint(collection=_COLLECTION, creator=_CREATOR, metadata={"name": "x"})
    assert factory.minted == [1]
    assert out["royalty_configured"] is False, out


async def test_a_fresh_collection_still_gets_its_royalty():
    """SCOPE PIN."""
    svc, _factory = _svc()
    out = await svc.create_collection(
        creator=_CREATOR, name="Drop", symbol="DRP", collection_type="erc721")
    assert out["royalty_configured"] is True, out
    info = svc._royalty._collection_defaults[_COLLECTION]
    assert info["recipient"] == _CREATOR


@pytest.mark.parametrize("sentence", [
    "These two sites each write a FRESH key so the 22-A authority check cannot refuse them",
    "Neither overwrites an existing entry, so neither is refused",
])
def test_the_fresh_key_sentences_are_gone(sentence):
    import inspect

    from runtime.blockchain.services.nft_services import royalty_enforcement, service

    text = " ".join((inspect.getsource(service) + inspect.getsource(royalty_enforcement))
                    .replace("#", " ").split())
    assert sentence not in text
