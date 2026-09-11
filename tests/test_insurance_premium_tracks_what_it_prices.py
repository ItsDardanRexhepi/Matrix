"""DOMAIN 18-P / 18-Q / 18-R — the premium and the thing it is meant to price.

18-Q  MONOTONICITY   The tier rate was chosen by the WHOLE coverage amount and
                     multiplied across all of it, so the premium was
                     NON-MONOTONIC in the amount insured. Measured pre-fix
                     (weather, 365d): 1,000 of cover cost 50.00 and 1,001 cost
                     30.03. Three cliffs, each an arbitrage — buy a pound more,
                     pay less for it. Tiers are now marginal, like brackets.

18-P  SEVERITY       The premium was CONSTANT in the variable that decides
                     whether the platform pays at all. Measured: 50,000 of heat
                     cover for a year cost 1,000.00 whether the trigger was
                     >35C (fires most summers) or >59C (essentially never).

18-R  PROVENANCE     Risk factors are declared by the applicant and verified by
                     nothing. 18-A closed the SCALING half; this is the half it
                     recorded as open. Disclosure does not reduce the discount —
                     it stops the quote presenting it as a priced fact.

THE 18-P DEFERRAL, AND WHY IT WAS REVERSED RATHER THAN INHERITED.
18-E filed this registered-not-closed: pricing a threshold needs an actuarial
model this repository does not have, and inventing one would fabricate a
control. Re-examined at close, the premise fails. THIS ENGINE ALREADY PRICES BY
DECLARED MULTIPLIERS WITH NO ACTUARIAL DERIVATION — `earthquake: 1.5`,
`smart_contract_hack: 2.0`, and the tier rates themselves. A declared severity
multiplier is the same KIND of object the engine is built from, not a new kind
of claim. Keeping `earthquake: 1.5` while refusing to price the threshold is
inconsistent, not conservative.

What it is NOT: an estimate of how often a peril occurs. It says where inside
the platform's OWN declared insurable band the buyer chose to sit. Where no
bounded scale exists the result says `severity_priced: False` rather than
carrying a silent 1.0 — a refusal to guess is not a neutral value (§AC).
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.insurance._predicate import (
    build_predicate,
    trigger_ease,
)
from runtime.blockchain.services.insurance.fee_engine import FeeEngine


@pytest.fixture
def fee() -> FeeEngine:
    return FeeEngine({})


# ══════════════════════════════════════════════════════════════════════════
# 18-Q · more cover must never cost less
# ══════════════════════════════════════════════════════════════════════════


AMOUNTS = [1.0, 500.0, 999.0, 1_000.0, 1_001.0, 5_000.0, 9_999.0, 10_000.0,
           10_001.0, 50_000.0, 99_999.0, 100_000.0, 100_001.0, 500_000.0, 1e6]


async def test_the_premium_never_falls_as_coverage_rises(fee):
    """DEFECT-PROVER. Pre-fix there were three cliffs at the tier boundaries,
    each one an arbitrage. Asserted across the whole range rather than at the
    three known boundaries, so a future re-tiering that introduces a FOURTH
    cliff fails here too."""
    premiums = [
        (amt, (await fee.calculate_premium("weather", amt, 365, {}))["total_premium"])
        for amt in AMOUNTS
    ]
    inversions = [
        (lo, hi) for (lo, plo), (hi, phi) in zip(premiums, premiums[1:]) if phi < plo
    ]
    assert inversions == [], f"more cover cost less at: {inversions}"


@pytest.mark.parametrize("boundary,just_over", [
    (1_000.0, 1_001.0), (10_000.0, 10_001.0), (100_000.0, 100_001.0),
])
async def test_each_tier_boundary_is_continuous(fee, boundary, just_over):
    """DEFECT-PROVER at the exact measured cliffs. 1,000 -> 50.00 and
    1,001 -> 30.03 pre-fix; the step is now upward and small."""
    at = (await fee.calculate_premium("weather", boundary, 365, {}))["total_premium"]
    over = (await fee.calculate_premium("weather", just_over, 365, {}))["total_premium"]
    assert over >= at
    assert over - at < 1.0, "a marginal pound should cost roughly a marginal rate"


async def test_the_tier_slices_are_reported(fee):
    """DEFECT-PROVER. `tier_rate` is now an EFFECTIVE rate across the whole
    amount, which is a different quantity from the old single-tier rate. The
    slices are reported so the number can be checked rather than trusted."""
    q = await fee.calculate_premium("weather", 50_000.0, 365, {})
    slices = q["tier_slices"]
    assert [s["rate"] for s in slices] == [0.05, 0.03, 0.02]
    assert sum(s["amount"] for s in slices) == pytest.approx(
        50_000.0 * q["tier_rate"], rel=1e-9)


# ══════════════════════════════════════════════════════════════════════════
# 18-P · the premium tracks the trigger
# ══════════════════════════════════════════════════════════════════════════


async def test_an_easier_trigger_costs_more(fee):
    """DEFECT-PROVER. All three cost 1,000.00 pre-fix. The ordering is the
    claim — a policy that pays out most summers must not cost the same as one
    that essentially never pays."""
    quotes = []
    for threshold in (35.0, 45.0, 59.0):
        conditions = build_predicate("weather", {
            "metric": "temperature", "comparator": "gt", "threshold": threshold})
        q = await fee.calculate_premium(
            "weather", 50_000.0, 365, {}, trigger_conditions=conditions)
        quotes.append(q["total_premium"])

    assert quotes[0] > quotes[1] > quotes[2], (
        f"premium must fall as the trigger gets harder, got {quotes}"
    )


async def test_a_drought_trigger_prices_in_the_other_direction(fee):
    """DEFECT-PROVER. A `lt` trigger fires BELOW its threshold, so a HIGHER
    number is the easier one. A single direction applied to both would have
    priced drought cover exactly backwards."""
    easy = build_predicate("crop", {"rainfall_threshold_mm": 99.0})
    hard = build_predicate("crop", {"rainfall_threshold_mm": 1.0})
    q_easy = await fee.calculate_premium("crop", 10_000.0, 365, {},
                                         trigger_conditions=easy)
    q_hard = await fee.calculate_premium("crop", 10_000.0, 365, {},
                                         trigger_conditions=hard)
    assert q_easy["total_premium"] > q_hard["total_premium"]


async def test_an_unpriceable_trigger_says_so_rather_than_assuming_neutral(fee):
    """DEFECT-PROVER (§AC). `smart_contract_hack`'s loss floor is unbounded
    above, so there is no scale to place a threshold on. The result reports
    `severity_priced: False` instead of silently carrying a 1.0 multiplier
    that would be indistinguishable from a genuinely mid-band trigger."""
    conditions = build_predicate("smart_contract_hack", {"loss_threshold": 100_000.0})
    q = await fee.calculate_premium("smart_contract_hack", 50_000.0, 365, {},
                                    trigger_conditions=conditions)
    assert q["severity_priced"] is False
    assert q["trigger_ease"] is None
    assert q["severity_multiplier"] == 1.0


async def test_pricing_without_a_predicate_is_unchanged(fee):
    """SCOPE PIN. `trigger_conditions` is optional, and omitting it must not
    silently apply a severity multiplier."""
    q = await fee.calculate_premium("weather", 50_000.0, 365, {})
    assert q["severity_priced"] is False
    assert q["severity_multiplier"] == 1.0


@pytest.mark.parametrize("policy_type,conditions", [
    ("weather", {"metric": "temperature", "comparator": "gt", "threshold": 35.0}),
    ("weather", {"metric": "temperature", "comparator": "lt", "threshold": -10.0}),
    ("earthquake", {"magnitude_threshold": 4.0}),
    ("flight_delay", {"delay_minutes": 60}),
    ("crop", {"rainfall_threshold_mm": 100.0}),
])
def test_the_easiest_underwritable_trigger_scores_one(policy_type, conditions):
    """DEFECT-PROVER. The near end of each band is the most expensive point,
    and it must be identified consistently across every type and BOTH
    comparator directions."""
    assert trigger_ease(policy_type, build_predicate(policy_type, conditions)) == 1.0


# ══════════════════════════════════════════════════════════════════════════
# 18-R · whose claim the discount is
# ══════════════════════════════════════════════════════════════════════════


async def test_a_declared_discount_is_marked_as_the_applicants_own_claim(fee):
    """DEFECT-PROVER (§U, 16-G idiom). Nothing verifies `first_time_buyer` or
    `multi_policy_discount`. 18-A closed the SCALING half — a caller may select
    a factor, not scale one — and explicitly recorded this half as open,
    because checking it needs an underwriting source that does not exist here
    and inventing one would fabricate a control.

    Measured: two declared discounts take 1,120.00 to 952.00, asserted by the
    party who pays and checked by nobody. Disclosure does not reduce that. It
    stops the quote presenting it as a priced fact.
    """
    q = await fee.calculate_premium(
        "weather", 50_000.0, 365,
        {"first_time_buyer": True, "multi_policy_discount": True})

    assert q["risk_factors_verified"] is False
    assert "not verified" in q["risk_factors_disclosure"]
    assert all(f["source"] == "caller_asserted" for f in q["breakdown"])
    assert all(f["verified"] is False for f in q["breakdown"])


async def test_a_quote_with_no_declared_factors_makes_no_such_claim(fee):
    """SCOPE PIN (§AC). A policy that declared nothing must not carry a
    disclosure about unverified declarations — `None` distinguishes "no claim
    was made" from "a claim was made and not checked"."""
    q = await fee.calculate_premium("weather", 50_000.0, 365, {})
    assert q["risk_factors_verified"] is None
    assert q["risk_factors_disclosure"] == ""
