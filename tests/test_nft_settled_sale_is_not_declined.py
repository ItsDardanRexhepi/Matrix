"""22-D — a settled NFT sale carried the ROYALTY leg's "not settled" flags.

`RoyaltyEnforcement.process_sale` sets `settled: False, value_moved: False` to
say "the split was COMPUTED, not PAID" (NEW-91). True of the royalty leg.
`NFTService.process_sale` passed them through UNCHANGED when the NFT transfer
succeeded — so `_outcome_is_real` read a REAL TRANSFER as "this did not
happen", and a settled sale was recorded and published as a declined action.

ARMED-ONLY: under the shipped config `transferred` is False and the existing
branch is correct. This is the defect that arms the moment the domain starts
working.

=====================================================================
THE TRAP THIS TEST ALSO GUARDS: do NOT "fix" AC::2/AH::4 by writing
settled/value_moved=False onto the seven armed methods.
=====================================================================
That is the obvious reading — those methods omit the two fields the honesty
predicate reads — and it reproduces THIS defect sevenfold. `value_moved: False`
is the strongest "this did not happen" signal in `_outcome_is_real` and
outranks every other clause. Domain 21 made exactly this error in 21-C and
erased the attestation of posts that really existed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.blockchain.services.nft_services.service import NFTService
from runtime.blockchain.services.service_dispatcher import _outcome_is_real


def _shipped():
    return json.loads(Path("openmatrix.config.json.example").read_text())


async def _svc(armed: bool):
    """Arms ONLY the factory transport; every decision in process_sale runs."""
    svc = NFTService(_shipped())
    await svc.set_rights("0xC", 1, {"display": {"granted": True, "holder": "0xS"}})
    if armed:
        async def _ok(**_):
            return {"status": "transferred", "tx_hash": "0xT"}
        svc._factory.transfer_token = _ok
    return svc


@pytest.mark.asyncio
async def test_a_settled_sale_is_not_recorded_as_declined():
    """THE REPRODUCTION, on the branch that arms with the domain."""
    svc = await _svc(armed=True)
    out = await svc.process_sale("0xC", 1, 10.0, "0xS", "0xB")
    assert out.get("settled") is True
    assert _outcome_is_real(out) is True, (
        "a real NFT transfer is being recorded as an action that did not happen"
    )


@pytest.mark.asyncio
async def test_the_settled_sale_does_not_claim_the_royalty_was_paid():
    """The other direction: settling the TRANSFER must not silently upgrade the
    royalty leg, which really was only computed."""
    svc = await _svc(armed=True)
    out = await svc.process_sale("0xC", 1, 10.0, "0xS", "0xB")
    assert out["royalty_paid"] is False
    assert "royalty_disclosure" in out
    assert "not paid" in out["royalty_disclosure"].lower()


@pytest.mark.asyncio
async def test_value_moved_is_omitted_rather_than_asserted_false():
    """`value_moved: False` is a CLAIM that no value moved, and it outranks
    every other clause. An action that happens without moving value takes
    `settled: True` and OMITS the field — a claim not made is not a claim of
    False."""
    svc = await _svc(armed=True)
    out = await svc.process_sale("0xC", 1, 10.0, "0xS", "0xB")
    assert "value_moved" not in out


@pytest.mark.asyncio
async def test_the_unsettled_branch_is_unchanged():
    """§AQ class 3 — the branch that was already correct must stay correct.
    Under the SHIPPED config the transfer refuses and nothing settled."""
    svc = await _svc(armed=False)
    out = await svc.process_sale("0xC", 1, 10.0, "0xS", "0xB")
    assert out["status"] == "recorded_unsettled"
    assert out["settled"] is False
    assert out["value_moved"] is False
    assert _outcome_is_real(out) is False


def test_the_trap_is_documented_where_the_next_reader_meets_it():
    """A comment saying "do not write value_moved=False onto the seven armed
    methods" is worth more at the call site than in a register nobody reads
    while editing."""
    src = Path("runtime/blockchain/services/nft_services/service.py").read_text()
    assert "DO NOT" in src and "SEVEN ARMED METHODS" in src
    assert "reproduces this defect sevenfold" in src.lower()
