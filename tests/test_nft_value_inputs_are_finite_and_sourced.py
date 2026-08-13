"""DOMAIN 17-A / 17-B — nft_services: the payer's number, and the guards that
could not see it.

17-B. THE DOMAIN HAD ZERO `isfinite` GUARDS. 49 methods, 26 ordered comparisons,
8 of them value-bearing, and not one non-finite check — measured by AST before
any fix. This domain never received 16-A's pass.

`royalty_enforcement.process_sale` guarded itself with a FLOOR:
`if sale_price < _MIN_SALE_PRICE (0.0001): raise`. `nan < 0.0001` is False, so
the guard was skipped. That is the FIFTH shape the non-finite class has walked —
sign (15-D), ratio (16-A), sufficiency (16-I), eligibility (16-P), floor (here) —
and the point each time is the same: THE FINDING IS NOT THAT SIGN CHECKS ARE
WEAK, IT IS THAT EVERY COMPARISON IS WEAK. `configure_royalty`'s cap is the
sharpest instance: `bps < 0 or bps > cap` is a DISJUNCTION, and a NaN makes BOTH
disjuncts False, so the whole test is False and the cap admitted an uncapped
royalty. That is the shape a careful author writes SPECIFICALLY to be thorough —
two bounds, both directions covered — which is exactly why it is the strongest
evidence for the rule: adding the second comparison widened the gap.

17-A. §U, THE FIFTH SELF-ATTESTATION INSTANCE, AND IT NEEDS NO MALFORMED INPUT.
`process_sale` computes the creator's royalty as `sale_price * bps / 10000`, and
`sale_price` is supplied by the party who OWES it. Measured with a 10% royalty:

    sale_price=10.0   -> creator royalty 1.0
    sale_price=1.0    -> creator royalty 0.1

There is no price oracle for an arbitrary NFT sale, so the price CANNOT be
independently established here — which is why the fix is 16-G's idiom,
PROVENANCE PRESERVED rather than a verification invented. Inventing a check
against a source that does not exist would fabricate a control, which is the one
thing this audit cannot do.
"""

from __future__ import annotations

import math

import pytest

from runtime.blockchain.services.nft_services.royalty_enforcement import (
    RoyaltyEnforcement,
)
from runtime.blockchain.services.nft_services.valuation import ValuationEngine

CONFIG = {"blockchain": {"platform_wallet": "0xPLAT"}}


@pytest.fixture
def royalty() -> RoyaltyEnforcement:
    return RoyaltyEnforcement(CONFIG)


# ── 17-B: the fifth guard shape ──────────────────────────────────────────


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
async def test_a_non_finite_sale_price_is_refused_by_the_floor_guard(royalty, bad):
    """DEFECT-PROVER. Pre-fix `nan < 0.0001` was False and the sale was priced
    at NaN throughout: royalty=nan, fee=nan, seller_proceeds=nan, persisted."""
    with pytest.raises(ValueError, match="finite"):
        await royalty.process_sale(collection="0xC", token_id=1, sale_price=bad,
                                   seller="0xS", buyer="0xB")


async def test_the_floor_guard_still_rejects_a_dust_price(royalty):
    """SCOPE PIN. The finite check is added BEFORE the floor check, not instead
    of it — a fix that swallowed the original guard would be a regression."""
    with pytest.raises(ValueError, match="below minimum"):
        await royalty.process_sale(collection="0xC", token_id=1,
                                   sale_price=0.00001, seller="0xS", buyer="0xB")


async def test_an_ordinary_sale_is_unaffected(royalty):
    """SCOPE PIN."""
    out = await royalty.process_sale(collection="0xC", token_id=1, sale_price=10.0,
                                     seller="0xS", buyer="0xB")
    assert out["sale_price"] == 10.0
    assert math.isfinite(out["seller_proceeds"])


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
async def test_a_non_finite_bps_cannot_walk_through_the_royalty_cap(royalty, bad):
    """DEFECT-PROVER, AND THE SHARPEST FORM OF THE CLASS.

    `if bps < 0 or bps > self._max_royalty_bps` is a DISJUNCTION of two ordered
    comparisons. A NaN makes BOTH disjuncts False, so the disjunction is False
    and the raise is skipped — a guard whose entire job is bounding the value
    admitted an unbounded one.

    ADDING THE SECOND COMPARISON MADE IT WORSE, NOT BETTER. One bound leaves one
    way through; two bounds written as a disjunction leave a value that fails
    both, and NaN is exactly that value.
    """
    with pytest.raises(ValueError, match="finite"):
        await royalty.configure_royalty(collection="0xC", token_id=1,
                                        recipient="0xR", bps=bad)


async def test_the_royalty_cap_still_binds(royalty):
    """SCOPE PIN — the ordinary cap must still reject an over-cap value."""
    with pytest.raises(ValueError):
        await royalty.configure_royalty(collection="0xC", token_id=1,
                                        recipient="0xR", bps=9999)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_price_cannot_poison_the_valuation_store(bad):
    """DEFECT-PROVER. A NaN here is PERMANENT: it lands in `_sales_history` and
    is summed into `_collection_volumes`, so every later `estimate_value`
    averages it and one bad call poisons the collection for the process
    lifetime. Guarded at the writer, which is the only entry point."""
    v = ValuationEngine({})
    with pytest.raises(ValueError, match="finite"):
        v.record_sale("0xC", 1, bad)
    assert v._sales_history.get("0xC:1") in (None, [])
    assert v._collection_volumes.get("0xC", 0) == 0


# ── 17-A: §U — provenance preserved, not verification invented ────────────


async def test_the_sale_record_discloses_that_the_price_is_unverified(royalty):
    """DEFECT-PROVER (17-A). The royalty owed to the creator is computed from a
    number the payer supplies, and nothing in this method consults a chain
    receipt, escrow, or oracle. The record now says so."""
    out = await royalty.process_sale(collection="0xC", token_id=1, sale_price=10.0,
                                     seller="0xS", buyer="0xB")

    assert out["price_source"] == "caller_asserted"
    assert out["price_verified"] is False
    assert "has NOT been verified" in out["price_disclosure"]


async def test_the_disclosure_names_what_is_computed_from_the_unverified_figure(royalty):
    """§AI's second axis, applied at the point of writing rather than after.

    A disclosure that says only "the price is unverified" leaves a reader to
    work out what depends on it. This one names the royalty and the platform
    fee, because those are the amounts the unverified figure decides.
    """
    out = await royalty.process_sale(collection="0xC", token_id=1, sale_price=10.0,
                                     seller="0xS", buyer="0xB")
    d = " ".join(out["price_disclosure"].split())
    assert "royalty" in d and "platform fee" in d


async def test_the_understatement_is_arithmetic_and_undefended(royalty):
    """THE MEASUREMENT, PINNED — not as a defect to fix but as a fact to keep
    visible. There is no oracle for an arbitrary NFT sale price, so this cannot
    be defended here; if a future change claims to verify the price, this test
    should be REPLACED by one that proves the verification, not deleted.
    """
    await royalty.configure_royalty(collection="0xC", token_id=1,
                                    recipient="0xCREATOR", bps=1000)  # 10%
    honest = await royalty.process_sale(collection="0xC", token_id=1,
                                        sale_price=10.0, seller="0xS", buyer="0xB")
    understated = await royalty.process_sale(collection="0xC", token_id=1,
                                             sale_price=1.0, seller="0xS", buyer="0xB")

    assert honest["royalty"]["amount"] == 1.0
    assert understated["royalty"]["amount"] == 0.1
    # ...and both records carry the same honest provenance marker
    assert honest["price_verified"] is False
    assert understated["price_verified"] is False
