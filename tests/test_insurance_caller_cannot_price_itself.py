"""DOMAIN 18-A / 18-B — the applicant priced its own policy, and the guard that
set the payout could not see NaN.

18-A / §AN — A CATEGORY ABOVE §U. The previous six §U instances let the
beneficiary supply an INPUT. This let them supply the COEFFICIENT applied to a
constant the platform defined:

    adj = self._risk_adjustments.get(factor_name, 0.0)   # platform's -0.10
    if isinstance(factor_value, (int, float)):
        adj *= float(factor_value)                       # caller's multiplier

Measured pre-fix, coverage 100000 / 365d / parametric:

    {}                          -> 2000.00
    {first_time_buyer: True}    -> 1800.00
    {first_time_buyer: 10}      ->    0.01
    {first_time_buyer: 1000}    ->    0.01
    NaN, inf                    ->    0.01

§AN.1 — THE CLAMP IS WHAT MADE IT QUIET. Every abusive value landed on the same
floor, so 10, 1000, NaN and inf produced an identical unremarkable number. No
error, no anomaly, just a very cheap policy. A floor that turns unbounded abuse
into a uniform minimum is a defect disguised as a safety rail — the same shape as
`max(0, ...)` hiding 16-R's ledger drift.

A CALLER MAY SELECT A FACTOR. A CALLER MAY NOT SCALE ONE. Declaring
`first_time_buyer` is a claim the platform prices; deciding it is worth ten times
the platform's own figure is arithmetic on the platform's policy.

STILL OPEN, RECORDED NOT FIXED: nothing verifies `first_time_buyer` itself. That
needs an underwriting source this repo does not have, and inventing one would
fabricate a control. REJECTED ALTERNATIVE: drop negative adjustments entirely —
rejected because it silently reprices every honest policy that legitimately
qualifies, trading a bounded abuse for an unbounded overcharge.

18-B — §W's FIFTH SHAPE IN THE METHOD THAT SETS THE PAYOUT. `create_policy`
guards coverage with `<= 0` and `> max`; a NaN satisfies NEITHER and passes both.
`approve_claim` later pays `float(policy["coverage"]["amount"])`, so a NaN
coverage becomes a NaN payout on a claim the platform approves. `premium <
expected_premium` is defeated identically.

§AM.2 — WHY THIS WAS ALMOST MISSED. A first pass probed four risk-factor keys,
saw 2000.0 unchanged across all four, and read the constant output as a dead
input. The keys were simply the wrong four. **A constant output is exactly what a
correctly-defended input also produces** — the safe case and the unexamined case
are observationally identical. Only reading the CONSUMER's key set separates them.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.insurance.fee_engine import FeeEngine

CFG: dict = {}
COVER, DAYS, KIND = 100_000.0, 365, "weather"


@pytest.fixture
def fees() -> FeeEngine:
    return FeeEngine(CFG)


async def _p(fees, rf):
    return (await fees.calculate_premium(KIND, COVER, DAYS, rf))["total_premium"]


# ── 18-A: select a factor, never scale one ───────────────────────────────


async def test_a_caller_supplied_multiplier_does_not_scale_the_discount(fees):
    """DEFECT-PROVER. `{first_time_buyer: 10}` drove the premium to the 0.01
    floor pre-fix. The declaration is now worth exactly what the platform says
    it is worth, however large a number the caller attaches to it."""
    declared = await _p(fees, {"first_time_buyer": True})
    scaled = await _p(fees, {"first_time_buyer": 10})
    huge = await _p(fees, {"first_time_buyer": 1000})

    assert scaled == declared, "a caller-supplied multiplier still scales the discount"
    assert huge == declared


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), -1, 0])
async def test_a_non_finite_or_nonpositive_factor_is_not_a_declaration(fees, bad):
    """DEFECT-PROVER. NaN and inf reached the 0.01 floor pre-fix. A value that is
    not a positive finite number is not a declaration of anything, so the factor
    is ignored rather than applied."""
    assert await _p(fees, {"first_time_buyer": bad}) == await _p(fees, {})


async def test_an_unknown_factor_name_changes_nothing(fees):
    """SCOPE PIN — passes before and after; no new field is named."""
    assert await _p(fees, {"not_a_real_factor": True}) == await _p(fees, {})


async def test_a_legitimate_declaration_still_earns_its_discount(fees):
    """SCOPE PIN, AND THE ONE THAT MATTERS. The rejected alternative was to drop
    negative adjustments entirely; that would silently reprice every honest
    policy that legitimately qualifies. The discount must still apply, once."""
    base = await _p(fees, {})
    one = await _p(fees, {"first_time_buyer": True})
    both = await _p(fees, {"first_time_buyer": True, "multi_policy_discount": True})

    assert one < base, "a legitimate declaration no longer earns its discount"
    assert both < one


async def test_a_surcharge_factor_still_increases_the_premium(fees):
    """SCOPE PIN. The fix must not neuter POSITIVE adjustments either — that
    would be the mirror-image defect, an undercharge instead of an overcharge."""
    assert await _p(fees, {"high_frequency_area": True}) > await _p(fees, {})


# ── 18-B: §W's fifth shape, in the method that sets the payout ───────────

from runtime.blockchain.services.insurance.service import InsuranceService

SVC_CFG = {"insurance": {}}


@pytest.fixture
def svc(monkeypatch) -> InsuranceService:
    """ARMED-BY-DEPLOYMENT, and the fixture is where that is stated.

    `create_policy` returns `not_deployed` BEFORE it validates anything —
    measured: with the shipped config the NaN never reaches the bounds, because
    the method never gets there. So 18-B is **disarmed by deployment today and
    armed the moment `insurance.policy_contract` is set**, which is a runbook
    step. The validation sits AFTER the gate, so deploying turns the contract on
    and the guard on at the same instant, with no window in which the guard has
    been exercised.

    This fixture patches the gate open, which is the ONLY way to test the code
    the operator will actually run. A test that omitted it would pass against
    `not_deployed` and prove nothing — instrument failure #11's shape, an
    assertion that cannot fail because it never reaches its subject.
    """
    svc = InsuranceService(SVC_CFG)
    monkeypatch.setattr(svc._web3, "available", True)
    monkeypatch.setattr(svc._web3, "is_placeholder", lambda _a: False)
    return svc


async def test_the_premise_the_gate_is_what_stops_it_today(monkeypatch):
    """PREMISE, and the arming classification stated as a test.

    With the contract UNSET, `create_policy` never reaches its own validation —
    which is why 18-B is disarmed today and armed by a runbook step.

    THE GATE IS FORCED CLOSED HERE, NOT ASSUMED. `Web3Manager.get_shared()` is a
    PROCESS-WIDE SINGLETON, so a sibling test that patches it available leaks
    into this one: an earlier version of this test passed alone and failed in
    company — the third time this engagement has hit that trap (16-L, 16's
    undeployed-path test, here). A premise test that depends on ambient state is
    not establishing its premise, it is inheriting it.
    """
    plain = InsuranceService(SVC_CFG)
    monkeypatch.setattr(plain._web3, "available", False)
    out = await plain.create_policy(
        holder="0xH", policy_type="weather",
        coverage={"amount": float("nan"), "duration_days": 365}, premium=2000.0)
    assert out["status"] == "not_deployed", out


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
async def test_a_non_finite_coverage_cannot_pass_both_bounds(svc, bad):
    """DEFECT-PROVER, AND THE SHARPEST FORM OF §W's FIFTH SHAPE.

    `coverage_amount <= 0` and `coverage_amount > self._max_coverage` are two
    bounds written to cover both directions — defence in depth. **A NaN
    satisfies NEITHER, so it passes both.** Adding the second bound widened the
    gap rather than narrowing it.

    And this is the method that SETS THE PAYOUT: `approve_claim` later pays
    `float(policy["coverage"]["amount"])`, so a NaN here becomes a NaN payout on
    a claim the platform approves.
    """
    with pytest.raises(ValueError, match="finite"):
        await svc.create_policy(
            holder="0xH", policy_type="weather",
            coverage={"amount": bad, "duration_days": 365}, premium=2000.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
async def test_a_non_finite_premium_cannot_walk_through_the_sufficiency_check(svc, bad):
    """DEFECT-PROVER. `premium < expected_premium` is defeated by NaN the same
    way — the policy priced by a number that is not one.

    18-P moved the predicate build AHEAD of pricing, so a policy with no
    predicate is now refused before the premium is ever examined. This test
    supplies a VALID predicate deliberately: without one it would still pass,
    on the wrong refusal, and the guard it exists to prove would be masked
    rather than exercised."""
    with pytest.raises(ValueError, match="finite"):
        await svc.create_policy(
            holder="0xH", policy_type="weather",
            coverage={"amount": 100_000.0, "duration_days": 365,
                      "metric": "temperature", "comparator": "gt",
                      "threshold": 45.0},
            premium=bad)


async def test_the_original_bounds_still_bind(svc):
    """SCOPE PIN. The finite check is added BEFORE the range checks, not instead
    of them — a fix that swallowed the original guards would be a regression."""
    with pytest.raises(ValueError, match="positive"):
        await svc.create_policy(
            holder="0xH", policy_type="weather",
            coverage={"amount": -5.0, "duration_days": 365}, premium=2000.0)
