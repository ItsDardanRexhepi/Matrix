"""Three defects on the lending path where the record outran the action.

DOMAIN 16-D / 16-E / 16-F. All three found by the domain-16 census and each
DRIVEN before it was fixed.

16-E is the most serious of the three and the shape is the one this audit exists
to catch: **the lender's only remedy reported success over an action it is
structurally unable to perform.** Driven, on a genuinely eligible loan (ETH
crashed 2000 -> 900, ratio 0.75 against a 1.20 threshold):

    liquidate() returned  collateral_seized 1.0, collateral_remaining 0.0,
                          debt_repaid 1200.0, status "liquidated"
    actual state          borrower's collateral ledger UNCHANGED at ETH 1.0
                          borrow ledger UNCHANGED at USDC 1200.0

and the loan record itself was mutated to LIQUIDATED with borrow_amount and
accrued_interest set to 0.0 — **erasing the debt while the borrower kept every
unit of collateral.** That half is worse than the return value: a lender reading
the record sees a closed, settled position.

The cause is the same structural fact domain 13 established for the securities
exchange: LoanManager holds no reference to the collateral ledger, so it cannot
move what it claims to seize. Disposition follows domain 13's `match_orders`
ruling — the eligibility determination is real work, so the method keeps it and
stops claiming execution.

16-D is an incompleteness in MY OWN 16-C fix, recorded rather than quietly
repaired. 16-C guarded `set_borrow_position` against NaN; that guard fires AFTER
`LoanManager.repay_loan` has already mutated the loan, so a refused NaN
repayment left `borrow_amount = nan` on the loan record. **Validate at the FIRST
writer of a transaction, not the last** — a guard downstream of a mutation turns
silent corruption into loud corruption, which is an improvement and not a fix.

16-F: `create_loan` credited collateral BEFORE validating the loan, and the
ratio rejection propagated with no compensating debit, so a REFUSED loan left
the collateral credited. Fixed by ordering, not by a rollback: the fallible step
runs first and the deposit is reached only once the loan is certain. Ordering is
preferable to compensation because a compensating write can itself fail.
"""

from __future__ import annotations

import time

import pytest

from runtime.blockchain.services.defi import DeFiService

CONFIG = {"defi": {"fallback_prices": {"ETH": 2000.0, "USDC": 1.0}}}


@pytest.fixture
def service(monkeypatch) -> DeFiService:
    svc = DeFiService(CONFIG)
    monkeypatch.setattr(svc._web3, "available", True)
    monkeypatch.setattr(svc._web3, "is_placeholder", lambda _a: False)
    return svc


# ── 16-E: liquidation claims only what it did ────────────────────────────


async def _eligible_loan(service: DeFiService) -> str:
    loan = await service.create_loan("0xB", "ETH", 1.0, "USDC", 1200.0)

    async def crashed(token):
        return 900.0 if token == "ETH" else 1.0

    service._get_token_price = crashed
    return loan["loan_id"]


async def test_liquidation_does_not_claim_to_have_seized_anything(service):
    """THE LOAD-BEARING ASSERTION."""
    loan_id = await _eligible_loan(service)

    result = await service.liquidate(loan_id)

    assert result["seized"] is False
    assert result["value_moved"] is False
    assert "collateral_seized" not in result, (
        "the key itself asserts a completed transfer"
    )
    assert "not executed" in result["disclosure"].lower() or (
        "no collateral has been seized" in result["disclosure"].lower()
    )


async def test_liquidation_does_not_erase_the_debt(service):
    """THE WORSE HALF. The method used to set borrow_amount and accrued_interest
    to 0.0 and mark the loan LIQUIDATED — closing the position on the books
    while the borrower kept the collateral."""
    loan_id = await _eligible_loan(service)

    await service.liquidate(loan_id)

    loan = service._loan_manager._loans[loan_id]
    assert loan["borrow_amount"] == 1200.0, "the debt was erased"
    assert loan["status"] != "liquidated"
    assert loan["liquidation_due"] is True


async def test_liquidation_leaves_the_collateral_where_it_actually_is(service):
    """The ledger is untouched, and the record must agree with the ledger."""
    loan_id = await _eligible_loan(service)

    await service.liquidate(loan_id)

    assert service._collateral_manager._balances["0xB"]["ETH"] == 1.0
    assert service._collateral_manager._borrows["0xB"]["USDC"] == 1200.0


async def test_the_eligibility_determination_still_works(service):
    """WHY THIS WAS CATEGORY 6 AND NOT REMOVAL. Strip the outcome claim and real
    work remains — the price fetch, the ratio, the threshold comparison. If this
    stops working the disposition was wrong and the method should have been
    refused outright, as domain 13 did with `buy()`."""
    loan_id = await _eligible_loan(service)

    result = await service.liquidate(loan_id)

    assert result["ratio_at_liquidation"] == pytest.approx(0.75, abs=0.01)
    assert result["collateral_seizable"] > 0
    assert result["debt_outstanding"] == pytest.approx(1200.0)


async def test_an_ineligible_loan_is_still_refused(service):
    """THE CONTROL, asserted intact. Making the report honest must not make the
    eligibility gate permissive."""
    loan = await service.create_loan("0xC", "ETH", 10.0, "USDC", 1000.0)

    with pytest.raises(ValueError, match="above liquidation threshold"):
        await service.liquidate(loan["loan_id"])


# ── 16-D: validate at the first writer ───────────────────────────────────


async def test_a_refused_nan_repayment_leaves_the_loan_untouched(service):
    """MY OWN 16-C WAS INCOMPLETE. The ledger guard fired after the loan had
    already been mutated, leaving borrow_amount = nan."""
    loan = await service.create_loan("0xA", "ETH", 10.0, "USDC", 1000.0)
    loan_id = loan["loan_id"]
    before = dict(service._loan_manager._loans[loan_id])

    with pytest.raises(ValueError, match="finite"):
        await service.repay_loan(loan_id, float("nan"))

    after = service._loan_manager._loans[loan_id]
    changed = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    assert not changed, f"a refused repayment mutated the loan: {changed}"


async def test_an_ordinary_repayment_still_works(service):
    """SCOPE PIN on 16-D."""
    loan = await service.create_loan("0xA", "ETH", 10.0, "USDC", 1000.0)

    result = await service.repay_loan(loan["loan_id"], 400.0)

    assert result["remaining_principal"] == pytest.approx(600.0)


# ── 16-F: a refused loan moves nothing ───────────────────────────────────


async def test_a_refused_loan_leaves_no_collateral_credited(service):
    """Pre-fix, `_balances["0xZ"]` was {"ETH": 0.1} after the refusal."""
    with pytest.raises(ValueError, match="below minimum"):
        await service.create_loan("0xZ", "ETH", 0.1, "USDC", 1000.0)

    assert not service._collateral_manager._balances.get("0xZ"), (
        "a refused loan credited collateral that no loan backs"
    )


async def test_an_accepted_loan_still_credits_its_collateral(service):
    """SCOPE PIN. Reordering must not stop the deposit from happening on the
    path where it should."""
    await service.create_loan("0xY", "ETH", 10.0, "USDC", 1000.0)

    assert service._collateral_manager._balances["0xY"]["ETH"] == 10.0
    assert service._collateral_manager._borrows["0xY"]["USDC"] == 1000.0


# ── 16-G: the constrained party supplied the number the check used ───────


async def test_the_borrower_cannot_declare_their_own_collateral_value(service):
    """16-G. SELF-ATTESTATION ON A LENDING DECISION. `accept_offer` computed the
    collateral ratio from `collateral["value_usd"]` — a field in the caller's own
    request body. Driven pre-fix: 0.001 ETH self-declared at $5,000,000 backed a
    1000 USDC loan and returned status "filled". `p2p_lending.py` contains
    neither "oracle" nor "balance"; nothing in the file could have disagreed.

    Same class as fundraising's self-approved milestone and insurance's
    self-attested trigger.
    """
    offer = await service.create_p2p_offer("0xL", "USDC", 1000.0, 0.05, 30)

    with pytest.raises(ValueError, match="below minimum"):
        await service.accept_p2p_offer(
            offer["offer_id"], "0xB",
            {"token": "ETH", "amount": 0.001, "value_usd": 5_000_000.0},
        )


async def test_a_genuinely_collateralised_p2p_offer_is_still_accepted(service):
    """SCOPE PIN. The independent valuation must not refuse honest borrowers —
    1.0 ETH at the real 2000.0 covers a 1000 USDC loan at 2x."""
    offer = await service.create_p2p_offer("0xL", "USDC", 1000.0, 0.05, 30)

    accepted = await service.accept_p2p_offer(
        offer["offer_id"], "0xB",
        {"token": "ETH", "amount": 1.0, "value_usd": 1.0},  # understated; ignored
    )

    assert accepted["status"] == "filled"
    assert accepted["collateral"]["value_usd"] == pytest.approx(2000.0)
    assert accepted["collateral"]["value_source"] == "service_oracle"


async def test_unpriceable_collateral_is_refused_not_self_valued(service):
    """An unknown value must stop the acceptance, not fall back to the
    borrower's figure — 16-A's ruling on unknown ratios, applied here."""
    offer = await service.create_p2p_offer("0xL", "USDC", 1000.0, 0.05, 30)

    with pytest.raises(ValueError, match="No price available"):
        await service.accept_p2p_offer(
            offer["offer_id"], "0xB",
            {"token": "OBSCURE", "amount": 1.0, "value_usd": 9_999_999.0},
        )


# ── 16-H: a read that wrote, while the catalog said it did not ───────────


async def test_get_loan_does_not_mutate_the_stored_record(service):
    """16-H. `get_loan` is catalogued `state_modifying=False`, and that flag is
    what decides whether the dispatcher attests and publishes. The body wrote
    `accrued_interest` and re-based `last_interest_update` on every call."""
    import asyncio
    import copy

    loan = await service.create_loan("0xA", "ETH", 10.0, "USDC", 1000.0)
    loan_id = loan["loan_id"]
    before = copy.deepcopy(service._loan_manager._loans[loan_id])

    await asyncio.sleep(1.1)
    await service.get_loan(loan_id)

    after = service._loan_manager._loans[loan_id]
    changed = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    assert not changed, f"a read mutated the stored loan: {changed}"


async def test_get_loan_does_not_return_the_ledger_by_reference(service):
    """The aliasing half. A consumer writing to the result edited the ledger."""
    loan = await service.create_loan("0xA", "ETH", 10.0, "USDC", 1000.0)

    result = await service.get_loan(loan["loan_id"])

    assert result is not service._loan_manager._loans[loan["loan_id"]]
    result["borrow_amount"] = 0.0
    assert service._loan_manager._loans[loan["loan_id"]]["borrow_amount"] == 1000.0


async def test_get_loan_still_reports_accrued_interest(service):
    """SCOPE PIN — and the point of the fix. The VALUE must still be correct;
    only the persistence and the aliasing go away. Reading no longer compounds:
    the answer is a function of the loan and the clock, not of how often anyone
    looked."""
    import asyncio

    loan = await service.create_loan("0xA", "ETH", 10.0, "USDC", 1000.0)
    await asyncio.sleep(1.1)

    first = await service.get_loan(loan["loan_id"])
    second = await service.get_loan(loan["loan_id"])

    assert first["accrued_interest"] > 0
    assert second["accrued_interest"] >= first["accrued_interest"]
