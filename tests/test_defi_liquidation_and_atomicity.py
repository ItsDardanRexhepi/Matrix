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


# ── 16-J: posting an offer is not funding a loan ─────────────────────────


async def test_posting_an_offer_awards_no_reputation(service):
    """16-J. Pre-fix, `create_p2p_offer` awarded the event literally named
    `loan_funded` (+10, the schedule's joint-largest positive) the moment an
    offer was POSTED — no borrower, no acceptance, no collateral, no funds
    moved, no obligation to honour it.

    Reputation is what other participants read to decide whether to transact
    with a lender, so an event awarded for an INTENTION rather than an ACT
    inflates precisely the signal it exists to carry. It was also free-riding by
    construction: post offers, accrue "funded" credit, never fill one.
    """
    before = await service.get_reputation("0xL")

    await service.create_p2p_offer("0xL", "USDC", 1000.0, 0.05, 30)

    after = await service.get_reputation("0xL")
    assert after["score"] == before["score"], (
        "posting an offer moved the lender's reputation"
    )
    assert after["total_events"] == before["total_events"]


async def test_the_award_moves_to_acceptance(service):
    """The event is not deleted — it is relocated to the first moment the lender
    has actually done the thing it is named for."""
    offer = await service.create_p2p_offer("0xL", "USDC", 1000.0, 0.05, 30)
    before = await service.get_reputation("0xL")

    await service.accept_p2p_offer(
        offer["offer_id"], "0xB",
        {"token": "ETH", "amount": 1.0, "value_usd": 1.0},
    )

    after = await service.get_reputation("0xL")
    assert after["score"] > before["score"], "funding a loan earned nothing"


async def test_the_borrower_does_not_receive_the_lenders_credit(service):
    """SCOPE PIN on the relocation. `loan_funded` belongs to the party who
    funded it; awarding it to whoever triggered the call would be a different
    defect with the same shape."""
    offer = await service.create_p2p_offer("0xL", "USDC", 1000.0, 0.05, 30)

    await service.accept_p2p_offer(
        offer["offer_id"], "0xB",
        {"token": "ETH", "amount": 1.0, "value_usd": 1.0},
    )

    borrower = await service.get_reputation("0xB")
    assert borrower["total_events"] == 0, (
        "the borrower received the lender's funding credit"
    )


# ── 16-L / 16-M: documentation that stated the opposite of the code ──────


def test_the_loan_store_comment_is_not_inverted():
    """16-L. The comment read "used only when contracts are not deployed". The
    reverse holds: create_loan's gate returns not_deployed BEFORE the line that
    writes the store, so it is populated ONLY when contracts ARE deployed.

    Load-bearing for severity, not cosmetic — a reader trusting it would treat
    this as throwaway state for the undeployed case, when it is the live ledger
    of the deployed one, and the store 16-C's collateral-release defect ran
    through.
    """
    import pathlib

    src = (
        pathlib.Path(__file__).resolve().parent.parent
        / "runtime" / "blockchain" / "services" / "defi" / "loans.py"
    ).read_text()

    # NOTE: the old wording is deliberately QUOTED inside the correction, so a
    # bare "not in src" would match my own quote. Assert on the corrective
    # marker and on the absence of the wording as a LIVE comment line instead.
    live_comment = [
        ln for ln in src.splitlines()
        if ln.strip().startswith("# In-memory loan storage")
    ]
    assert not live_comment, f"the inverted comment is back: {live_comment}"

    # WHITESPACE-NORMALISE BEFORE MATCHING. The corrective marker wraps across a
    # comment line, so "# " lands mid-phrase and a contiguous substring search
    # finds nothing. That is instrument failure #2 exactly, recurring in a test
    # I wrote after cataloguing it — the check that fails to observe its subject
    # because of how the subject is formatted.
    flat = " ".join(src.replace("#", " ").split())
    assert "ONLY when contracts ARE deployed" in flat


async def test_an_undeployed_service_never_populates_the_loan_store():
    """THE FACT THE COMMENT GOT BACKWARDS, asserted rather than described.

    TAKES NO `service` FIXTURE, DELIBERATELY. That fixture monkeypatches
    `svc._web3`, and `Web3Manager.get_shared()` is a PROCESS-WIDE SINGLETON — so
    requesting it here would make this "undeployed" instance inherit a deployed
    gate. The L.3 aliasing trap, met a second time, in the test that exists to
    prove the undeployed path.
    """
    from runtime.blockchain.services.defi import DeFiService

    undeployed = DeFiService({})  # no gate patched anywhere in this test
    result = await undeployed.create_loan("0xA", "ETH", 10.0, "USDC", 1000.0)

    assert result["status"] == "not_deployed"
    assert undeployed._loan_manager._loans == {}, (
        "the store filled while contracts were NOT deployed"
    )


def test_the_documented_config_key_is_not_claimed_unless_it_is_read():
    """16-M. The class docstring told operators that accepted collateral tokens
    are configured under `defi.collateral_tokens`. Measured: ZERO readers
    repo-wide. The set is the hardcoded `_collateral_factors` literal.

    The unfed-control shape (14-C's empty sanctions list) expressed as
    documentation: an operator setting that key to RESTRICT accepted collateral
    would see it silently ignored and believe the restriction was in force.

    Pinned as a biconditional — if someone later wires the key up, the docstring
    may claim it again, and this test says so rather than blocking the feature.
    """
    import pathlib

    base = pathlib.Path(__file__).resolve().parent.parent / "runtime"
    src = (base / "blockchain" / "services" / "defi" / "collateral.py").read_text()

    readers = [
        p for p in base.rglob("*.py")
        if "collateral_tokens" in p.read_text(errors="ignore")
        and p.name != "collateral.py"
    ]

    if readers:
        return  # the key is wired now; the docstring may legitimately claim it

    assert "WHICH NOTHING READS" in src, (
        "collateral.py documents defi.collateral_tokens as a live config key "
        "while nothing in the repo reads it"
    )


# ══════════════════════════════════════════════════════════════════════════
# 16-P / 16-Q / 16-R — the remaining confirmed defi findings
# ══════════════════════════════════════════════════════════════════════════


def _active_loan(service):
    """A healthy loan: 10 ETH collateral against 1000 USDC, ratio 20x."""
    lm = service._loan_manager
    loan_id = "loan_test"
    lm._loans[loan_id] = {
        "loan_id": loan_id, "borrower": "0xA",
        "collateral_token": "ETH", "collateral_amount": 10.0,
        "borrow_token": "USDC", "borrow_amount": 1000.0,
        "accrued_interest": 0.0, "interest_rate": 0.05,
        "status": lm._loans.get(loan_id, {}).get("status") or _LoanStatus().ACTIVE,
        "last_interest_update": int(time.time()),
        "created_at": int(time.time()),
    }
    return lm, loan_id


class _LoanStatus:
    def __init__(self):
        from runtime.blockchain.services.defi.loans import LoanStatus
        self.ACTIVE = LoanStatus.ACTIVE


# ── 16-P: a NaN price liquidates a healthy loan ───────────────────────────


async def test_a_nan_price_cannot_make_a_healthy_loan_liquidatable(service):
    """THE NON-FINITE CLASS, THIRD GUARD SHAPE — an eligibility test.

    15-D walked the sign check (`amount <= 0`), 16-A the ratio check
    (`collateral_ratio < min`). This is `current_ratio >= threshold`, and it
    fails identically: with a NaN price the ratio is NaN, `NaN >= threshold` is
    FALSE, so the "above threshold, refuse" branch is SKIPPED and execution
    falls through to the liquidation determination.

    A loan collateralised at 20x is marked liquidation-due. The guard reads as a
    protection and inverts into the attack — §W.1's ordering rule, which is why
    triage goes by what a guard protects and never by how sound it looks.
    """
    lm, loan_id = _active_loan(service)

    with pytest.raises(ValueError, match="finite"):
        await lm.liquidate(loan_id, collateral_price=float("nan"),
                           borrow_price=1.0)

    assert lm._loans[loan_id].get("liquidation_due") is not True, (
        "a 20x-collateralised loan was marked liquidation-due by a NaN price"
    )


async def test_a_zero_price_is_refused_not_a_zero_division(service):
    """The seizure arithmetic divides by `collateral_price`. Pre-fix a zero
    price raised ZeroDivisionError from inside a method that had ALREADY accrued
    interest onto the loan — an uncaught arithmetic error standing in for a
    validation refusal, with the record left mutated."""
    lm, loan_id = _active_loan(service)

    with pytest.raises(ValueError, match="positive"):
        await lm.liquidate(loan_id, collateral_price=0.0, borrow_price=1.0)


async def test_a_refused_price_leaves_the_loan_untouched(service):
    """16-F's ordering lesson, re-applied. The guard runs BEFORE
    `_accrue_interest`, so a refused call changes nothing at all — not the
    interest, not the timestamp. Validation after mutation leaves the record
    changed by a call that refused."""
    lm, loan_id = _active_loan(service)
    before = dict(lm._loans[loan_id])

    for bad in (float("nan"), float("inf"), 0.0, -5.0):
        with pytest.raises(ValueError):
            await lm.liquidate(loan_id, collateral_price=bad, borrow_price=1.0)
        with pytest.raises(ValueError):
            await lm.liquidate(loan_id, collateral_price=2000.0, borrow_price=bad)

    assert lm._loans[loan_id] == before, (
        "a refused liquidation mutated the loan record"
    )


# ── 16-Q: the reported utilisation was not the one the rate used ──────────


async def test_the_reported_utilisation_is_the_one_the_rate_was_computed_from(service):
    """TWO READERS OF ONE QUANTITY, WITH DIFFERENT DEFAULTS.

    `_calculate_interest_rate` read `_pool_total.get(token, 1.0)`; `get_rates`
    read `_pool_total.get(token, 0.0)`. For a token with no pool entry and any
    borrowing, the rate came from utilisation 1.0 — the maximum kink, via a
    fabricated denominator of one unit — while the SAME dict reported
    `"utilisation": 0.0`. A borrower charged the top rate by an API reporting an
    idle pool.

    The finding was filed as "the rate model reads a control nothing feeds".
    That premise is false — `_pool_total` has a writer, `update_pool_total`,
    reached from four call sites. The defect is a DIVERGENT control, not an
    unfed one, which is the harder version: each reader is correct alone.
    """
    lm = service._loan_manager
    lm._pool_borrowed["USDC"] = 250.0          # borrowings, no pool entry

    rates = await lm.get_rates("USDC")

    assert rates["utilisation"] == 1.0, (
        f"reported utilisation {rates['utilisation']} contradicts the rate, "
        f"which is computed from 1.0"
    )
    # the rate is unchanged by the fix — only the reported number becomes true
    assert rates["borrow_rate"] == round(lm._calculate_interest_rate("USDC"), 6)


async def test_an_empty_pool_with_no_borrowings_is_idle_not_fully_drawn(service):
    """SCOPE PIN. "No pool entry" must not become "fully utilised" across the
    board — that would be the mirror-image fabrication."""
    lm = service._loan_manager
    assert (await lm.get_rates("DAI"))["utilisation"] == 0.0


async def test_utilisation_is_the_real_ratio_when_the_pool_is_funded(service):
    """SCOPE PIN. The ordinary path is untouched."""
    lm = service._loan_manager
    lm.update_pool_total("USDC", 1000.0)
    lm._pool_borrowed["USDC"] = 400.0
    assert (await lm.get_rates("USDC"))["utilisation"] == 0.4


# ── 16-R: the pool ledger drifted down on every repayment ─────────────────


async def test_repaying_interest_does_not_reduce_recorded_borrowings(service):
    """THE LEDGER WAS INCREMENTED BY PRINCIPAL AND DECREMENTED BY PRINCIPAL
    PLUS INTEREST.

    `create_loan` adds `borrow_amount`; `repay_loan` subtracted the whole
    `repay_amount`, which is applied to interest first. So every repayment of a
    loan carrying interest removed more from `_pool_borrowed` than the loan ever
    added. The drift understates outstanding borrowings, and utilisation, and
    the rate charged to every later borrower. `max(0, ...)` kept it from ever
    going visibly negative, which is why it reads as correct.
    """
    lm, loan_id = _active_loan(service)
    lm._pool_borrowed["USDC"] = 1000.0
    lm._loans[loan_id]["accrued_interest"] = 50.0
    lm._loans[loan_id]["last_interest_update"] = int(time.time())

    await lm.repay_loan(loan_id, 50.0)          # pays interest ONLY

    assert lm._pool_borrowed["USDC"] == 1000.0, (
        f"an interest-only repayment moved recorded borrowings to "
        f"{lm._pool_borrowed['USDC']}; no principal was repaid"
    )
    assert lm._loans[loan_id]["accrued_interest"] == 0.0
    assert lm._loans[loan_id]["borrow_amount"] == 1000.0


async def test_repaying_principal_does_reduce_recorded_borrowings(service):
    """SCOPE PIN. The ledger must still track real principal movement — a fix
    that stopped decrementing at all would be the mirror-image defect."""
    lm, loan_id = _active_loan(service)
    lm._pool_borrowed["USDC"] = 1000.0
    lm._loans[loan_id]["accrued_interest"] = 50.0
    lm._loans[loan_id]["last_interest_update"] = int(time.time())

    await lm.repay_loan(loan_id, 250.0)         # 50 interest + 200 principal

    assert lm._pool_borrowed["USDC"] == 800.0
    assert lm._loans[loan_id]["borrow_amount"] == 800.0


async def test_the_ledger_returns_to_zero_over_a_full_lifecycle(service):
    """THE INVARIANT, not the arithmetic. Whatever a loan added, repaying it in
    full removes exactly that — no more, whatever interest accrued in between."""
    lm, loan_id = _active_loan(service)
    lm._pool_borrowed["USDC"] = 1000.0
    lm._loans[loan_id]["accrued_interest"] = 137.42

    await lm.repay_loan(loan_id, 1137.42)

    assert lm._pool_borrowed["USDC"] == 0.0
    assert lm._loans[loan_id]["status"].value == "repaid"
