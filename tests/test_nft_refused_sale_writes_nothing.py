"""DOMAIN 17-G / 17-H — a refused sale must write NOTHING.

`NFTService.process_sale` calls `transfer_token`, which refuses on BOTH branches
while the NFT contract is undeployed, and then correctly returns
`recorded_unsettled / settled: False / value_moved: False`. Two writes sat ABOVE
that computation and were not gated on it.

17-G — THE AUTHORITY SURFACE. `transfer_rights(new_holder=buyer)` moved the
display right to the buyer of a sale that did not happen. In the SAME return,
NEW-90/91's disclosure says ownership is unchanged and "this platform holds no
ownership record of its own" — **accurate about VALUE and false about AUTHORITY,
in one response, from one method.** Every half-fix this engagement has caught was
within one surface; this is the first between two, and it is why §AI added a
second axis: not only *check every field on this surface* but **check every KIND
of thing this method writes.**

17-H — THE EVIDENCE SURFACE, and the sharpest §AG/§AH instance in the engagement.
`record_sale` is the ONLY production writer of the valuation evidence store, and
it was fed the caller's asking price for a sale the platform refused.
`estimate_value` then reported that price as `measured_factors: {recent_sales:
True}` behind NEW-92's disclosure *"30% of the declared weight is backed by
observed data"*, and six repeats crossed `_min_sales` to lift the confidence
label to "medium".

Upheld at HIGH by independent verification, whose arming clause is the finding in
one line: armed **"precisely BECAUSE the NFT contract is undeployed"**.

**THE HONEST REFUSAL WAS THE ATTACK PATH.** NEW-90/91's refusal produced the
unsettled sale; this line recorded it as evidence; NEW-92's disclosure vouched
for it. Three correct fixes composing into a defect none of them contains — §AG
(fixes composing) and §AH (a fix lending credibility) in one object.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.nft_services.service import NFTService

CONFIG: dict = {}


@pytest.fixture
def svc() -> NFTService:
    return NFTService(CONFIG)


async def _grant_display_to_seller(svc, *, token_id=7):
    """The seller holds the display right BEFORE the sale.

    INSTRUMENT NOTE, and it nearly cost three tests. `transfer_rights` MOVES an
    existing right and raises KeyError when none was set — which `process_sale`
    swallows. So a rights test that never grants the right first passes pre-fix
    for the wrong reason: nothing moved because nothing was there to move.
    Instrument failure #11 — an assertion that cannot fail is not an assertion.
    The census's own repro granted the right first; mine did not, until this.
    """
    await svc._rights.set_rights(
        collection="0xC", token_id=token_id,
        rights={"display": {"granted": True, "holder": "0xSELLER"}})


async def _refused_sale(svc, *, token_id=7, price=1000.0):
    """Drive a real sale under shipped config, where the factory refuses."""
    return await svc.process_sale(
        collection="0xC", token_id=token_id, sale_price=price,
        seller="0xSELLER", buyer="0xBUYER",
    )


async def test_the_premise_the_sale_really_is_refused(svc):
    """PREMISE. If this fails the other tests prove nothing — they would be
    asserting about a path that no longer refuses."""
    out = await _refused_sale(svc)
    assert out["nft_transferred"] is False
    assert out["status"] == "recorded_unsettled"


# ── 17-H: the evidence surface ───────────────────────────────────────────


async def test_a_refused_sale_writes_no_valuation_evidence(svc):
    """DEFECT-PROVER. The price of a sale that did not happen must not become
    the platform's evidence about what the token is worth."""
    await _refused_sale(svc)

    assert svc._valuation._sales_history.get("0xC:7") in (None, [])
    assert svc._valuation._collection_volumes.get("0xC", 0) == 0


async def test_a_refused_sale_does_not_move_the_appraisal(svc):
    """DEFECT-PROVER, on the RENDERED output rather than the store — this is the
    number a user acts on. Pre-fix: 0.0 -> 850.0 from one refused buy."""
    before = await svc.estimate_value(collection="0xC", token_id=7)
    await _refused_sale(svc)
    after = await svc.estimate_value(collection="0xC", token_id=7)

    assert after["estimated_value_eth"] == before["estimated_value_eth"]


async def test_repeated_refused_sales_do_not_manufacture_confidence(svc):
    """DEFECT-PROVER. Six repeats crossed `_min_sales` and lifted the label to
    "medium" — the disclosure vouching for evidence the refusal created."""
    for i in range(6):
        await _refused_sale(svc, price=1000.0 + i)

    est = await svc.estimate_value(collection="0xC", token_id=7)
    assert est.get("measured_factors", {}).get("recent_sales") is not True, (
        "a refused sale is being reported as observed data"
    )


# ── 17-G: the authority surface ──────────────────────────────────────────


async def test_a_refused_sale_does_not_move_the_display_right(svc):
    """DEFECT-PROVER. The rights ledger named the buyer after a refused sale."""
    await _grant_display_to_seller(svc)
    await _refused_sale(svc)

    holder = svc._rights._rights["0xC:7"]["rights"]["display"]["holder"]
    assert holder == "0xSELLER", (
        f"a refused sale moved the display right to {holder}"
    )


async def test_a_refused_sale_leaves_no_rights_transfer_history(svc):
    """§AI's second axis: the ledger AND its audit trail are both authority-kind
    state, and a fix that stopped one while leaving the other would be the
    half-fix this engagement keeps catching."""
    await _grant_display_to_seller(svc)
    await _refused_sale(svc)
    assert svc._rights._transfer_history.get("0xC:7", []) == []


async def test_the_disclosure_is_now_true_about_both_surfaces(svc):
    """THE POINT OF §AI, ASSERTED. NEW-90/91's disclosure says ownership is
    unchanged. That sentence is only true if NOTHING of an ownership-ish kind
    moved — value or authority. Now it is."""
    await _grant_display_to_seller(svc)
    out = await _refused_sale(svc)

    assert out["nft_transferred"] is False
    assert svc._rights._rights["0xC:7"]["rights"]["display"]["holder"] == "0xSELLER"
    assert svc._valuation._sales_history.get("0xC:7") in (None, [])


# ── scope pins: a SETTLED sale must still write both ──────────────────────


async def test_a_settled_sale_still_records_valuation_and_rights(svc, monkeypatch):
    """SCOPE PIN, and the one that matters most. Gating on `transferred` must not
    disable the writes altogether — that would trade a false record for no
    record, which is the same defect facing the other way."""
    async def _ok_transfer(**kwargs):
        return {"status": "submitted", "tx_hash": "0xabc"}

    monkeypatch.setattr(svc._factory, "transfer_token", _ok_transfer)

    # `transfer_rights` MOVES an existing right; it raises KeyError when none
    # was ever set, and `process_sale` swallows that. So the seller must hold
    # the right for this pin to be testing anything — a pin that passed because
    # the call KeyError'd would assert nothing at all.
    await svc._rights.set_rights(collection="0xD", token_id=9,
                                 rights={"display": {"granted": True,
                                                     "holder": "0xS"}})

    out = await svc.process_sale(collection="0xD", token_id=9, sale_price=5.0,
                                 seller="0xS", buyer="0xB")

    assert out["nft_transferred"] is True
    assert svc._valuation._sales_history.get("0xD:9"), "a settled sale wrote no evidence"
    holder = svc._rights._rights["0xD:9"]["rights"]["display"]["holder"]
    assert holder == "0xB", "a settled sale did not move the display right"
