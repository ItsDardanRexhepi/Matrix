"""A settlement is recorded only when its receipt proves THIS escrow settled.

`RealEstateService.confirm_settlement` says: "THE ANTI-FAKE CHECK: the
receipt must prove THIS escrow settled on OUR contract". The check read the
Settled event's emitting address and three of its topics: the event, the
escrow id and the buyer. A log with no seller topic passed, a seller topic
was never compared with anything, and the data word that carries the amount,
the deed token and the readiness attestation was never decoded.

PropertyEscrow binds a lock to the listing the deed's owner wrote, and the
escrow id it is keyed on is sha256 of the platform's escrow id, which the
seller can compute. A listing made under that id at 1 wei, or for another of
the seller's deeds, settles on our contract with this escrow's id and this
buyer, and the platform recorded the property as sold at its full price.

The receipt now has to carry, from our escrow contract, this escrow's Settled
event with all four topics (the escrow id, its buyer, the property's seller)
and a data word naming this escrow's amount, the property's deed token and
the digest of this escrow's readiness snapshot; and, from our deed contract,
the Transfer of that token from the seller to the buyer. Each case below
changes one of those and nothing else.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from eth_abi import encode as abi_encode
from web3 import Web3

from tests.test_real_estate_service import (
    BUYER,
    DEED,
    ESCROW,
    PRICE,
    SELLER,
    _listed_property,
    _make_ready,
    _service,
)

_SETTLED = bytes(Web3.keccak(
    text="Settled(bytes32,address,address,uint256,uint256,bytes32)"))
_TRANSFER = bytes(Web3.keccak(text="Transfer(address,address,uint256)"))
_TOKEN = 7
_OTHER = "0x" + "cc" * 20
_ROGUE = "0x" + "99" * 20


def _topic(address: str) -> bytes:
    return bytes(12) + Web3.to_bytes(hexstr=Web3.to_checksum_address(address))


def _digest(escrow: dict) -> bytes:
    return hashlib.sha256(
        json.dumps(escrow["readiness_snapshot"], sort_keys=True).encode()).digest()


def _receipt(escrow: dict, **change) -> dict:
    """The receipt a genuine lockAndSettle of *escrow* produces, with the
    fields named in *change* replaced."""
    f = {
        "escrow_contract": ESCROW, "escrow_id": escrow["id"], "buyer": BUYER,
        "seller": SELLER, "seller_topic": True, "amount": int(PRICE),
        "token": _TOKEN, "attestation": _digest(escrow), "data": None,
        "transfer": True, "deed_contract": DEED, "transfer_from": SELLER,
        "transfer_to": BUYER, "transfer_token": _TOKEN,
    }
    f.update(change)
    topics = [_SETTLED, hashlib.sha256(f["escrow_id"].encode()).digest(),
              _topic(f["buyer"])]
    if f["seller_topic"]:
        topics.append(_topic(f["seller"]))
    data = f["data"] if f["data"] is not None else abi_encode(
        ["uint256", "uint256", "bytes32"],
        [f["amount"], f["token"], f["attestation"]])
    logs = []
    if f["transfer"]:
        logs.append({
            "address": Web3.to_checksum_address(f["deed_contract"]),
            "topics": [_TRANSFER, _topic(f["transfer_from"]),
                       _topic(f["transfer_to"]),
                       f["transfer_token"].to_bytes(32, "big")],
            "data": b"",
        })
    logs.append({"address": Web3.to_checksum_address(f["escrow_contract"]),
                 "topics": topics, "data": data})
    return {"status": 1, "to": Web3.to_checksum_address(f["escrow_contract"]),
            "logs": logs}


async def _prepared(tmp_path):
    svc = _service(tmp_path, escrow_contract=ESCROW, deed_contract=DEED)
    prop = await _listed_property(svc)
    await svc._store.update_property(prop["id"], deed_token_id=str(_TOKEN))
    await _make_ready(svc, prop["id"])
    out = await svc.execute_purchase(BUYER, prop["id"])
    assert out["status"] == "prepared", out
    return svc, prop, out["escrow"]


_FORGERIES = [
    ("one wei for a one-ether property", {"amount": 1}),
    ("a seller who is not the property's", {"seller": _OTHER}),
    ("no seller topic at all", {"seller_topic": False}),
    ("another deed token", {"token": _TOKEN + 1, "transfer_token": _TOKEN + 1}),
    ("an event naming another deed token", {"token": _TOKEN + 1}),
    ("a readiness attestation that is not this escrow's",
     {"attestation": bytes(31) + b"\x01"}),
    ("no data word", {"data": b""}),
    ("no deed transfer in the receipt", {"transfer": False}),
    ("the deed transfer came from another contract", {"deed_contract": _ROGUE}),
    ("the deed went to someone else", {"transfer_to": _OTHER}),
    ("the deed came from someone else", {"transfer_from": _OTHER}),
]


@pytest.mark.parametrize("label,change", _FORGERIES, ids=[f[0] for f in _FORGERIES])
async def test_a_settlement_of_other_terms_is_not_this_escrows(tmp_path, label, change):
    svc, prop, escrow = await _prepared(tmp_path)
    svc._web3.w3.eth._receipt = _receipt(escrow, **change)

    result = await svc.confirm_settlement(escrow["id"], "0x" + "ee" * 32)

    assert result["status"] == "not_settlement", (
        f"{label}: recorded as {result['status']!r}")
    assert (await svc.get_escrow(escrow["id"]))["state"] == "initiated"
    assert (await svc.get_property(prop["id"]))["status"] == "under_escrow"


async def test_the_genuine_receipt_still_settles(tmp_path):
    """SCOPE PIN: the receipt a real lockAndSettle of this escrow produces is
    accepted, so the cases above fail on the field they change."""
    svc, prop, escrow = await _prepared(tmp_path)
    svc._web3.w3.eth._receipt = _receipt(escrow)

    result = await svc.confirm_settlement(escrow["id"], "0x" + "ee" * 32)

    assert result["status"] == "settled", result
    assert (await svc.get_property(prop["id"]))["status"] == "sold"


async def test_the_data_word_is_read_as_hex_text_too(tmp_path):
    """A node can hand the data word back as 0x-prefixed text rather than
    bytes; the same genuine settlement is accepted either way."""
    svc, prop, escrow = await _prepared(tmp_path)
    receipt = _receipt(escrow)
    for log in receipt["logs"]:
        log["data"] = "0x" + bytes(log["data"]).hex()
    svc._web3.w3.eth._receipt = receipt

    result = await svc.confirm_settlement(escrow["id"], "0x" + "ee" * 32)

    assert result["status"] == "settled", result
