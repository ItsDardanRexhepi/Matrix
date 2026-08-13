"""DOMAIN 18-J / 18-K / 18-L — three controls with no input, reporting measured values.

The shared shape: a mechanism exists, looks like a control, is read by
consumers as authoritative — and nothing ever feeds it. Not a lenient control;
an absent one wearing a control's clothes.

18-J  EXPOSURE      `ReserveFund._active_coverage` was a counter maintained by
                    `add_coverage`/`remove_coverage`, which had ZERO CALLERS
                    tree-wide. So it was permanently 0.0, `check_solvency`
                    weighed only the single policy being written and never the
                    accumulated book, and `get_balance` reported
                    `active_coverage: 0.0` / `reserve_ratio: Infinity` as
                    facts. MEASURED: fifteen 50,000 policies against a 90,000
                    reserve, each individually "solvent", real ratio 1.20
                    against a 1.5 floor.

18-K  HISTORY       `EligibilityTracker.record_claim` had ZERO CALLERS, so
                    `_history` never received a claim event,
                    `_compute_risk_score` returned 0.0 for everyone forever,
                    and two of the three `check_eligibility` gates were
                    structurally unreachable — while `check_eligibility` and
                    `get_history` both reported `risk_score` and
                    `total_claims` as measured.

18-L  ASSESSMENT    `assess_risk` returned `risk_score: 50` and
                    `premium_estimate: 0.0` as LITERALS. No engine consulted,
                    no history read, identical for every holder and every
                    policy type. MEASURED against the honest engine: 0.0
                    versus 2000.0. "assessed" is a real-outcome status, so the
                    dispatcher attested and published an assessment that had
                    assessed nothing — and this was the one insurance action
                    that still reached its caller while the ownership actions
                    were dead (18-H). The fabricating path worked; the honest
                    ones did not.

WHY 18-J DELETES THE COUNTER RATHER THAN CALLING IT. The obvious repair is to
call `add_coverage` on issue and `remove_coverage` on cancel and payout. That
leaves EXPIRY, which has no event to hook — a policy lapses because a timestamp
passed — so any counter silently over-states exposure from the first lapse
onward. A counter that can drift is the same defect with a working
implementation. Exposure is now derived from the policy book on every decision.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.insurance.reserve_fund import ReserveFund
from runtime.blockchain.services.insurance.service import InsuranceService


def _armed(svc: InsuranceService) -> InsuranceService:
    svc._web3.available = True
    svc._policy_contract = "0xC0FFEE"
    svc._web3.is_placeholder = lambda _v: False
    return svc


async def _quake(svc, holder="alice", amount=50_000.0):
    return await svc.create_policy(
        holder=holder, policy_type="earthquake",
        coverage={"amount": amount, "magnitude_threshold": 6.0},
        premium=1e9,
    )


# ══════════════════════════════════════════════════════════════════════════
# 18-J · exposure
# ══════════════════════════════════════════════════════════════════════════


async def test_the_solvency_gate_weighs_the_whole_book_not_one_policy():
    """DEFECT-PROVER. Pre-fix every policy was checked against an exposure of
    zero, so fifteen 50,000 policies all passed against a 90,000 reserve. The
    gate now accumulates: 90,000 backs one 50,000 policy at ratio 1.8 and
    refuses the second at a required 150,000."""
    svc = _armed(InsuranceService({"insurance": {"initial_reserve": 90_000.0}}))
    first = await _quake(svc, "h1")
    second = await _quake(svc, "h2")

    assert first["status"] == "active"
    assert second["status"] == "rejected"
    assert "Reserve fund insufficient" in second["reason"]


async def test_exposure_is_reported_as_a_real_number():
    """DEFECT-PROVER. `active_coverage` was structurally 0.0 and
    `reserve_ratio` structurally Infinity, both presented as measurements."""
    svc = _armed(InsuranceService({"insurance": {"initial_reserve": 500_000.0}}))
    await _quake(svc, "h1", 50_000.0)
    await _quake(svc, "h2", 50_000.0)

    bal = await svc._reserve_fund.get_balance()
    assert bal["active_coverage"] == 100_000.0
    assert bal["reserve_ratio"] == pytest.approx(5.0)
    assert bal["exposure_is_measured"] is True


async def test_a_reserve_with_no_book_says_it_is_not_measuring():
    """DEFECT-PROVER (§AC). A detached ReserveFund reports zero exposure,
    which is indistinguishable IN SHAPE from a genuinely empty book. The flag
    is what tells a real zero from an unmeasured one."""
    bare = ReserveFund({"insurance": {"initial_reserve": 1_000.0}})
    bal = await bare.get_balance()
    assert bal["active_coverage"] == 0.0
    assert bal["exposure_is_measured"] is False


async def test_a_cancelled_policy_stops_counting_against_the_reserve():
    """DEFECT-PROVER, and the case a counter would have got wrong. Exposure is
    derived, so releasing capacity needs no decrement to remember."""
    svc = _armed(InsuranceService({"insurance": {"initial_reserve": 90_000.0}}))
    first = await _quake(svc, "alice")
    assert (await _quake(svc, "bob"))["status"] == "rejected"

    await svc.cancel_policy(first["policy_id"], caller="alice")
    assert (await _quake(svc, "bob"))["status"] == "active"


async def test_an_expired_policy_stops_counting_against_the_reserve():
    """DEFECT-PROVER, AND THE REASON THE COUNTER WAS NOT REVIVED. Expiry has
    no event to decrement on — the policy lapses because a timestamp passed.
    A maintained counter would hold this capacity hostage forever."""
    import time as _t
    svc = _armed(InsuranceService({"insurance": {"initial_reserve": 90_000.0}}))
    first = await _quake(svc, "alice")
    assert (await _quake(svc, "bob"))["status"] == "rejected"

    svc._policies[first["policy_id"]]["expires_at"] = int(_t.time()) - 1
    assert (await _quake(svc, "bob"))["status"] == "active"


def test_the_dead_counter_methods_are_gone():
    """SCOPE PIN, STRUCTURAL. Leaving `add_coverage`/`remove_coverage` in place
    unused would be worse than the bug: a later reader finds two methods that
    look like the exposure mechanism and concludes exposure is tracked (§T.3,
    §AM.3). They are deleted, and this fails if either returns."""
    assert not hasattr(ReserveFund, "add_coverage")
    assert not hasattr(ReserveFund, "remove_coverage")


# ══════════════════════════════════════════════════════════════════════════
# 18-K · claim history
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("silent_oracle", [True, False])
async def test_a_decided_claim_reaches_the_holders_history(silent_oracle):
    """DEFECT-PROVER. Recorded at BOTH claim-decision sites, and for BOTH
    outcomes — a denial is as much a fact about a holder as an approval, and
    `_compute_risk_score` reads the denied ratio explicitly."""
    svc = _armed(InsuranceService({"insurance": {"initial_reserve": 5_000_000.0}}))
    pol = await _quake(svc, "alice", 1_000.0)

    async def oracle(_t):
        return {} if silent_oracle else {
            "oracle_type": "custom", "cached": False, "timestamp": 1,
            "data": {"magnitude": 7.9},
        }
    svc._trigger_manager._fetch_oracle_data = oracle

    await svc.file_claim(pol["policy_id"], caller="alice")

    history = await svc._eligibility.get_history("alice")
    assert history["total_claims"] == 1


async def test_the_risk_score_moves_once_a_claim_is_on_record():
    """DEFECT-PROVER. `_compute_risk_score` returned 0.0 for everyone forever
    because its only input had no writer. Measured: 0.0 before a claim,
    48.0 after."""
    svc = _armed(InsuranceService({"insurance": {"initial_reserve": 5_000_000.0}}))
    before = (await svc.assess_risk("alice", "earthquake",
                                    {"coverage_amount": 1_000.0}))["risk_score"]
    pol = await _quake(svc, "alice", 1_000.0)

    async def silent(_t):
        return {}
    svc._trigger_manager._fetch_oracle_data = silent
    await svc.file_claim(pol["policy_id"], caller="alice")

    after = (await svc.assess_risk("alice", "earthquake",
                                   {"coverage_amount": 1_000.0}))["risk_score"]
    assert before == 0.0
    assert after > before, "a claim on record must move the holder's risk score"


# ══════════════════════════════════════════════════════════════════════════
# 18-L · the assessment that assessed nothing
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("policy_type,amount", [
    ("earthquake", 100_000.0),
    ("weather", 25_000.0),
    ("flight_delay", 5_000.0),
])
async def test_the_premium_estimate_comes_from_the_engine_that_prices_policies(
    policy_type, amount,
):
    """DEFECT-PROVER. `premium_estimate` was the literal 0.0 for every holder,
    every policy type and every amount. Compared against the real engine
    rather than against a constant, so a future divergence between the quote
    and the price fails here."""
    svc = _armed(InsuranceService({}))
    out = await svc.assess_risk("alice", policy_type,
                                {"coverage_amount": amount})
    honest = await svc._fee_engine.calculate_premium(
        policy_type, amount, svc._default_duration, {})

    assert out["premium_estimate"] == honest["total_premium"]
    assert out["premium_estimate"] > 0.0


async def test_the_estimate_discloses_whose_number_it_is_quoted_against():
    """DEFECT-PROVER (§U / 16-G idiom). The coverage amount is the ENQUIRER'S,
    and no policy is created here. An estimate that did not say so reads as a
    price the platform has agreed to."""
    svc = _armed(InsuranceService({}))
    out = await svc.assess_risk("alice", "earthquake",
                                {"coverage_amount": 100_000.0})
    assert out["estimate_basis"] == "caller_supplied_coverage_amount"
    assert out["estimate_is_binding"] is False


async def test_assess_risk_validates_its_policy_type():
    """DEFECT-PROVER. It accepted any string and returned a confident
    assessment for a peril the platform does not insure."""
    svc = _armed(InsuranceService({}))
    with pytest.raises(ValueError, match="Unknown policy_type"):
        await svc.assess_risk("alice", "banana", {"coverage_amount": 1.0})


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
async def test_a_non_finite_coverage_cannot_be_assessed(bad):
    """DEFECT-PROVER. The estimate is computed from a caller-supplied amount,
    so it needs the same finiteness guard as the paths that price a real
    policy (18-B)."""
    svc = _armed(InsuranceService({}))
    with pytest.raises(ValueError, match="finite"):
        await svc.assess_risk("alice", "earthquake", {"coverage_amount": bad})


# ══════════════════════════════════════════════════════════════════════════
# 18-M · the reserve's own arithmetic
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("op", ["withdraw", "deposit"])
async def test_the_reserve_refuses_a_non_finite_amount(op, bad):
    """DEFECT-PROVER, DEFENCE IN DEPTH. Both bounded comparisons in `withdraw`
    are False against NaN — `nan <= 0` and `nan > balance` — so a NaN
    satisfied neither and passed both, and the subtraction made `_balance`
    itself NaN. Every later solvency comparison is then False: the
    correctly-priced path is refused forever while the unpriced one is
    unbounded.

    `deposit` was NaN-blind on the same shape and NO census finding named it —
    27 findings enumerated the withdrawal side and none the deposit side. A
    chokepoint fix at `withdraw` alone would have left this half open (§AK.2).

    Both `_policies` writers now reject non-finite amounts, so there is no
    armed path here today. This is the guard at the arithmetic itself, so a
    future fourth writer cannot reopen it.
    """
    fund = ReserveFund({"insurance": {"initial_reserve": 1_000.0}})
    with pytest.raises(ValueError, match="finite"):
        await getattr(fund, op)(bad)
    assert fund._balance == 1_000.0


async def test_the_reserve_still_refuses_an_oversized_withdrawal():
    """SCOPE PIN — the original insufficiency guard must still bind."""
    fund = ReserveFund({"insurance": {"initial_reserve": 1_000.0}})
    with pytest.raises(ValueError, match="Insufficient reserve"):
        await fund.withdraw(5_000.0)


# ══════════════════════════════════════════════════════════════════════════
# 18-N · the same ledger call, classified in opposite directions
# ══════════════════════════════════════════════════════════════════════════


async def test_both_claim_paths_disclose_that_no_value_moved():
    """DEFECT-PROVER. `auto_settle_claim` and `file_claim` both reach
    `ReserveFund.withdraw`, which is a ledger decrement — no transfer occurs on
    either. The sibling disclosed it; `file_claim` returned an "approved" claim
    with a `payout_amount` and said nothing, so the identical fact was
    disclosed on one path and withheld on the other.

    `file_claim` is the more dangerous half: it is the path a claimant actually
    files on, and "approved, payout_amount 50000.0" reads as "you have been
    paid"."""
    svc = _armed(InsuranceService({"insurance": {"initial_reserve": 5_000_000.0}}))
    pol = await _quake(svc, "alice", 1_000.0)

    async def real_quake(_t):
        return {"oracle_type": "custom", "cached": False, "timestamp": 1,
                "data": {"magnitude": 7.9}}
    svc._trigger_manager._fetch_oracle_data = real_quake

    claim = await svc.file_claim(pol["policy_id"], caller="alice")

    assert claim["status"] == "approved"
    assert claim["value_moved"] is False
    assert "NOT a transfer" in claim["disclosure"]


# ══════════════════════════════════════════════════════════════════════════
# 18-O · the corpus that scripted a promise the code could not keep
# ══════════════════════════════════════════════════════════════════════════


def test_the_scripted_renewal_call_can_actually_be_made():
    """DEFECT-PROVER (§T.3). The corpus declared `new_period` and
    `updated_coverage`; the method accepts neither, so driving the shipped
    example produced "renew_coverage() got an unexpected keyword argument
    'new_period'". A shipped example that cannot run is written and not
    wired."""
    import inspect
    import runtime.chat.intent_actions as ia

    entry = next(
        v["cover_renew"] for name in dir(ia)
        if isinstance(v := getattr(ia, name), dict) and "cover_renew" in v
    )
    accepted = inspect.signature(InsuranceService.renew_coverage).parameters
    declared = ([p["name"] for p in entry["required_params"]]
                + [p["name"] for p in entry.get("optional_params", [])])

    assert [p for p in declared if p not in accepted] == []


def test_the_corpus_does_not_promise_cover_before_the_call_returns():
    """DEFECT-PROVER (§AH, one layer above the code). The example line read
    "Your coverage continues uninterrupted." against a method that renewed
    nothing. The model was not fabricating — it was repeating a guarantee the
    platform wrote down for it. 18-G made renewal real, but it can still refuse
    on price or status, so the assurance must follow the result."""
    import runtime.chat.intent_actions as ia

    entry = next(
        v["cover_renew"] for name in dir(ia)
        if isinstance(v := getattr(ia, name), dict) and "cover_renew" in v
    )
    example = entry["example_conversation"]
    assert "continues uninterrupted" not in example
    assert example.index("platform_action") < example.index("Renewed"), (
        "the outcome must be stated AFTER the call, not before it"
    )
