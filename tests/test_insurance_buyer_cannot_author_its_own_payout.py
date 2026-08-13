"""DOMAIN 18-E / 18-F / 18-G — the buyer wrote the test, stated the price, and
was told the policy renewed.

Three findings, one theme: every input a payout decision turns on was supplied
by the party the decision pays.

18-E  the PREDICATE   — `metric`, `comparator`, `threshold` lifted verbatim
                        from the buyer's coverage dict
18-F  the PRICE       — `create_parametric_policy` never called the fee engine
18-G  the RECORD      — `renew_coverage` attested and published a renewal it
                        never performed

§AG, POINTED AT OUR OWN WORK. 18-D made the weather alias resolve
("temperature" -> the emitted "temp"). Before it, the shipped default weather
policy was DEAD — the metric never matched, so it denied everything. After it,
the default resolves, and the shipped `threshold=0` with comparator `gt` pays
out on any temperature above freezing. 18-D removed a denial defect and armed
a payout defect underneath it. The census lane recorded the precondition — "the
honest default is dead, which inverts the incentive" — without knowing a later
fix would revive it.

    The detector, turned inward: which of this engagement's own fixes changed
    an input that THIS defect reads?

That is why 18-E removes the defaults rather than correcting them. A defaulted
decision number is a payout condition nobody chose.
"""

from __future__ import annotations

import math

import pytest

from runtime.blockchain.services.insurance._predicate import (
    PredicateError,
    build_predicate,
)
from runtime.blockchain.services.insurance.service import InsuranceService


def _armed(svc: InsuranceService) -> InsuranceService:
    """Arm the deployment gate deliberately, and say so.

    Every method under test returns `not_deployed` until this is done, so a
    test that skipped it would pass against a service that never ran a line of
    the logic it claims to check.
    """
    svc._web3.available = True
    svc._policy_contract = "0xC0FFEE"
    svc._web3.is_placeholder = lambda _v: False
    return svc


@pytest.fixture
def svc() -> InsuranceService:
    return _armed(InsuranceService({}))


# ══════════════════════════════════════════════════════════════════════════
# 18-E · the buyer cannot name a field that is not a peril
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("metric", ["timestamp", "cached", "oracle_type", "location"])
def test_a_buyer_cannot_point_the_trigger_at_an_envelope_field(metric):
    """DEFECT-PROVER. `metric` was an UNRESTRICTED KEY LOOKUP into whatever the
    gateway returned. Measured at the census pin, against an HONEST oracle
    reporting calm weather: metric="timestamp", threshold=0, "gt" -> APPROVED
    50,000 (the envelope's unix clock always exceeds 0); metric="cached",
    threshold=-1, "gt" -> APPROVED 50,000 (a bool, float()-ed to 0.0).

    The buyer did not need an implausible threshold. Naming the envelope's own
    clock was enough.
    """
    with pytest.raises(PredicateError, match="not an insurable weather peril"):
        build_predicate("weather", {"metric": metric, "comparator": "gt",
                                    "threshold": 0})


def test_the_shipped_weather_default_can_no_longer_be_issued():
    """DEFECT-PROVER, AND THE §AG INSTANCE ABOUT OUR OWN FIX.

    Post-18-D and pre-18-E this was measured returning `measured=True,
    met=True` against an honest 21.0C reading — a guaranteed payout on an
    ordinary day, issued by default, with no attacker and no malformed input.

    A policy that names no peril and no threshold is now refused rather than
    defaulted.
    """
    with pytest.raises(PredicateError, match="requires an explicit 'metric'"):
        build_predicate("weather", {"location": "Denver"})


@pytest.mark.parametrize("threshold", [0, 10.0, 34.9, -273.0])
def test_a_heat_policy_must_trigger_on_heat(threshold):
    """DEFECT-PROVER. `temperature > 0` is not insurance, it is a subscription.
    The band requires a heat policy to trigger above a genuine heat extreme."""
    with pytest.raises(PredicateError, match="outside the insurable range"):
        build_predicate("weather", {"metric": "temperature", "comparator": "gt",
                                    "threshold": threshold})


@pytest.mark.parametrize("policy_type,key,value", [
    ("earthquake", "magnitude_threshold", -1e9),
    ("earthquake", "magnitude_threshold", 0),
    ("flight_delay", "delay_minutes", 0),
    ("crop", "rainfall_threshold_mm", 1000),
    ("smart_contract_hack", "loss_threshold", 0),
])
def test_a_threshold_any_reading_satisfies_is_refused(policy_type, key, value):
    """DEFECT-PROVER. Each of these was measured paying out at the census pin
    against an honest oracle. `magnitude_threshold=-1e9` approved on any HTTP
    200; `delay_minutes=0` approved on any non-empty body; the shipped
    `loss_threshold=0` made a zero reported loss satisfy the trigger."""
    with pytest.raises(PredicateError, match="outside the insurable range"):
        build_predicate(policy_type, {key: value})


@pytest.mark.parametrize("policy_type,key", [
    ("earthquake", "magnitude_threshold"),
    ("flight_delay", "delay_minutes"),
    ("crop", "rainfall_threshold_mm"),
    ("smart_contract_hack", "loss_threshold"),
])
def test_an_absent_decision_number_is_a_refusal_not_a_default(policy_type, key):
    """DEFECT-PROVER (§T). Every one of these had a default, and a defaulted
    decision number is a payout condition nobody chose. 18-D proved the cost:
    a default that was harmless only because a SEPARATE bug made it
    unreachable."""
    with pytest.raises(PredicateError, match="requires an explicit"):
        build_predicate(policy_type, {"location": "somewhere"})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_threshold_is_refused(bad):
    """DEFECT-PROVER. §W's fifth shape at the predicate layer: NaN satisfies
    neither bound of the band check, so without an explicit finiteness test it
    would pass both."""
    with pytest.raises(PredicateError, match="finite"):
        build_predicate("earthquake", {"magnitude_threshold": bad})


def test_an_honest_extreme_policy_still_issues():
    """SCOPE PIN — the control. A real catastrophe policy must still be
    writable, or the fix has replaced a payout hole with a denial of service."""
    p = build_predicate("weather", {"metric": "temperature", "comparator": "gt",
                                    "threshold": 45.0, "location": "Phoenix"})
    assert p["threshold"] == 45.0 and p["metric"] == "temperature"
    q = build_predicate("earthquake", {"magnitude_threshold": 6.5})
    assert q["magnitude_threshold"] == 6.5


def test_a_policy_type_with_no_parametric_trigger_is_unchanged():
    """SCOPE PIN — `{}` remains the signal that no trigger is registered."""
    assert build_predicate("not_a_parametric_type", {"anything": 1}) == {}


# ══════════════════════════════════════════════════════════════════════════
# 18-F · the unpriced twin
# ══════════════════════════════════════════════════════════════════════════


async def test_the_parametric_path_cannot_be_bought_at_a_price_the_buyer_names(svc):
    """DEFECT-PROVER. Measured at the pin: coverage 90,000 with premium 0.0 was
    written ACTIVE, then settled APPROVED, driving the reserve to 0.0 — against
    an honest quote of 1,440.0. The buyer supplied BOTH numbers and nothing
    reconciled them. §U at its limit: the party bound by the pricing decision
    IS the pricing decision."""
    await svc._reserve_fund.deposit(200_000.0)
    out = await svc.create_parametric_policy(
        holder="0xBUYER", trigger_type="flight_delay",
        trigger_params={"delay_minutes": 180},
        coverage_amount=90_000.0, premium=0.0,
    )
    assert out["status"] == "rejected"
    assert "below required" in out["reason"]


async def test_the_parametric_path_validates_its_policy_type(svc):
    """DEFECT-PROVER. `policy_type` was written verbatim into the canonical
    field the claim path reads. Measured: "banana" produced an ACTIVE policy
    with a registered trigger, published to the public feed as
    insurance_policy_created. Its guarded twin has always raised here."""
    with pytest.raises(ValueError, match="Unknown trigger_type"):
        await svc.create_parametric_policy(
            holder="0xB", trigger_type="banana", trigger_params={},
            coverage_amount=100.0, premium=100.0,
        )


async def test_a_non_finite_coverage_cannot_reach_the_reserve(svc):
    """DEFECT-PROVER, AND THE STRICTLY WORST OUTCOME AT THE PIN.

    This method was the SOLE injection point for a NaN coverage — the guarded
    twin rejects one incidentally at solvency (`balance >= nan` is False).
    Measured chain: NaN coverage -> active -> approved with payout nan ->
    ReserveFund._balance becomes nan -> every subsequent honest create_policy
    is rejected FOREVER with "Reserve fund insufficient" while this path
    becomes unbounded. The correctly-priced path is bricked and the unpriced
    one is not.
    """
    await svc._reserve_fund.deposit(90_000.0)
    with pytest.raises(ValueError, match="finite"):
        await svc.create_parametric_policy(
            holder="0xB", trigger_type="flight_delay",
            trigger_params={"delay_minutes": 180},
            coverage_amount=float("nan"), premium=0.0,
        )
    assert math.isfinite(svc._reserve_fund._balance), (
        "a NaN balance is unrecoverable: every later solvency comparison is "
        "False, so the honest path is refused forever"
    )
    # ...and the honest path still works, which is the half that mattered.
    ok = await svc.create_policy(
        holder="0xHONEST", policy_type="earthquake",
        coverage={"amount": 1_000.0, "magnitude_threshold": 6.0},
        premium=100_000.0,
    )
    assert ok["status"] == "active"


async def test_the_parametric_path_honours_the_coverage_ceiling(svc):
    """DEFECT-PROVER. `insurance.max_coverage` was honoured on the twin and
    ignored here — measured side by side: create_policy raised "exceeds max
    1000000.0" while create_parametric_policy returned active with 1e9."""
    await svc._reserve_fund.deposit(10.0)
    with pytest.raises(ValueError, match="exceeds max"):
        await svc.create_parametric_policy(
            holder="0xB", trigger_type="earthquake",
            trigger_params={"magnitude_threshold": 6.0},
            coverage_amount=1e9, premium=1e9,
        )


async def test_trigger_params_cannot_overwrite_the_gated_coverage_amount(svc):
    """DEFECT-PROVER — 18-I, AND A HOLE 18-F ITSELF LEFT OPEN.

    18-F added the guarded twin's GATES and not the twin's RECORD
    CONSTRUCTION. The record built `coverage` as
    `{"amount": coverage_amount, ..., **(trigger_params or {})}` — splat last,
    excluding nothing — so a buyer-supplied `trigger_params["amount"]`
    OVERWROTE the value every gate had just validated, and `ClaimsProcessor`
    pays `policy["coverage"]["amount"]`.

    MEASURED at 5eee277 with all of 18-F's gates in place: an honest premium
    of 75.0 for 1,000 of cover, a legitimate in-band predicate, and an HONEST
    oracle reporting a real M7.8 paid out 5,000,000 — five times
    `max_coverage`, a figure neither solvency nor the fee engine ever saw.

    §AK.2 at its sharpest: guarding the INPUT to a record while leaving the
    record's construction unguarded moves the defect one field over.
    """
    await svc._reserve_fund.deposit(10_000_000.0)
    quote = await svc._fee_engine.calculate_premium(
        "earthquake", 1000.0, 365, {},
        trigger_conditions=svc._build_trigger_conditions(
            "earthquake", {"magnitude_threshold": 6.0}),
    )
    rec = await svc.create_parametric_policy(
        holder="0xALICE", trigger_type="earthquake",
        trigger_params={"magnitude_threshold": 6.0, "amount": 5_000_000.0},
        coverage_amount=1000.0, premium=quote["total_premium"],
    )
    assert rec["coverage"]["amount"] == 1000.0, (
        "the payout field must carry the GATED amount, not the buyer's"
    )
    assert rec["coverage"]["magnitude_threshold"] == 6.0, (
        "legitimate trigger_params keys must still reach the record"
    )


async def test_a_non_finite_amount_cannot_reach_the_record_through_trigger_params(svc):
    """DEFECT-PROVER — 18-I's NaN limb, which 18-F's own commit message
    claimed to have closed and had not. The finiteness guard ran on
    `coverage_amount`; the record then took `trigger_params["amount"]`, so a
    NaN landed in the field the payout reads and poisoned the reserve from
    there."""
    await svc._reserve_fund.deposit(10_000_000.0)
    rec = await svc.create_parametric_policy(
        holder="0xB", trigger_type="earthquake",
        trigger_params={"magnitude_threshold": 6.0, "amount": float("nan")},
        coverage_amount=1000.0, premium=1e9,
    )
    assert math.isfinite(rec["coverage"]["amount"])
    assert rec["coverage"]["amount"] == 1000.0


async def test_both_policy_writers_exclude_the_same_keys():
    """DEFECT-PROVER, STRUCTURAL. The two writers into `_policies` must agree
    on which caller-supplied keys may reach `coverage`.

    They source the AMOUNT differently, and that difference is the whole
    finding: `create_policy` reads it out of the coverage dict, so the gated
    value and the dict entry are the same number and there is nothing to
    clobber. `create_parametric_policy` takes it as a SEPARATE parameter and
    then splatted a second dict over the result — so the gate and the record
    could disagree, and did.

    What both must share is the exclusion of keys that are inputs to a gate
    rather than fields of a policy. `risk_factors` is the clearest: it is
    consumed by the fee engine and must never become part of the coverage the
    claim path reads.
    """
    svc = _armed(InsuranceService({}))
    await svc._reserve_fund.deposit(10_000_000.0)
    hostile = {"duration_days": 99999, "risk_factors": {"first_time_buyer": 1e9}}

    classic = await svc.create_policy(
        holder="0xA", policy_type="earthquake",
        coverage={"amount": 1000.0, "magnitude_threshold": 6.0, **hostile},
        premium=1e9)
    parametric = await svc.create_parametric_policy(
        holder="0xB", trigger_type="earthquake",
        trigger_params={"magnitude_threshold": 6.0, "amount": 9_999_999.0,
                        **hostile},
        coverage_amount=1000.0, premium=1e9)

    for name, rec in (("create_policy", classic),
                      ("create_parametric_policy", parametric)):
        assert "risk_factors" not in rec["coverage"], f"{name} leaked risk_factors"

    assert parametric["coverage"]["amount"] == 1000.0, (
        "the parametric writer must keep the GATED amount, not the buyer's"
    )
    assert classic["coverage"]["amount"] == 1000.0


async def test_the_parametric_path_still_refuses_what_the_reserve_cannot_back(svc):
    """DEFECT-PROVER. No solvency check ran on this path at all."""
    await svc._reserve_fund.deposit(100.0)
    out = await svc.create_parametric_policy(
        holder="0xB", trigger_type="earthquake",
        trigger_params={"magnitude_threshold": 6.0},
        coverage_amount=50_000.0, premium=1e9,
    )
    assert out["status"] == "rejected"
    assert "Reserve fund insufficient" in out["reason"]


# ══════════════════════════════════════════════════════════════════════════
# 18-G · the renewal that renewed nothing
# ══════════════════════════════════════════════════════════════════════════


async def _issue(svc: InsuranceService, holder="0xALICE") -> dict:
    await svc._reserve_fund.deposit(500_000.0)
    return await svc.create_policy(
        holder=holder, policy_type="earthquake",
        coverage={"amount": 10_000.0, "magnitude_threshold": 6.0,
                  "location": "SF"},
        premium=100_000.0,
    )


async def test_renewing_a_policy_that_does_not_exist_is_not_a_renewal(svc):
    """DEFECT-PROVER. Any policy_id string returned status "renewed", and
    "renewed" is in _REAL_OUTCOME_STATUSES — so the dispatcher ATTESTED the
    renewal into the audit record and PUBLISHED it to the public social feed.
    A fabricated outcome, made permanent and announced."""
    out = await svc.renew_coverage("pol_does_not_exist", 1.0, 365, caller="0xX")
    assert out["status"] == "not_found"

    from runtime.blockchain.services.service_dispatcher import _outcome_is_real
    assert _outcome_is_real(out) is False, (
        "the dispatcher would attest and publish a renewal of a policy that "
        "does not exist"
    )


async def test_a_stranger_cannot_renew_someone_elses_policy(svc):
    """DEFECT-PROVER. The method took NO caller parameter at all — the NEW-78b
    ownership sweep covered file_claim and cancel_policy and never reached it."""
    pol = await _issue(svc)
    with pytest.raises(PermissionError):
        await svc.renew_coverage(pol["policy_id"], 1e9, 365, caller="0xMALLORY")


async def test_a_renewal_actually_moves_the_expiry(svc):
    """DEFECT-PROVER, AND THE HEART OF IT. The method never looked the policy
    up and never wrote to the store. `new_expiry` was `now + extension_days`,
    computed from the caller's own argument, never read from the policy's
    actual expires_at and never persisted — so the holder was told publicly
    that cover continued while the stored policy expired on its original date
    and every claim path then refused them as expired."""
    pol = await _issue(svc)
    before = svc._policies[pol["policy_id"]]["expires_at"]

    out = await svc.renew_coverage(pol["policy_id"], 1e9, 365, caller="0xALICE")

    assert out["status"] == "renewed"
    after = svc._policies[pol["policy_id"]]["expires_at"]
    assert after == before + 365 * 86400, (
        "the STORED policy must carry the new expiry, not just the reply"
    )
    assert out["new_expiry"] == after, "the reply must agree with the store"


async def test_a_renewal_must_be_paid_for(svc):
    """DEFECT-PROVER. `additional_premium` was echoed into the record and never
    compared with anything — a free extension of cover for any number, or none."""
    pol = await _issue(svc)
    before = svc._policies[pol["policy_id"]]["expires_at"]

    out = await svc.renew_coverage(pol["policy_id"], 0.01, 365, caller="0xALICE")

    assert out["status"] == "rejected"
    assert "below the required" in out["reason"]
    assert svc._policies[pol["policy_id"]]["expires_at"] == before, (
        "a rejected renewal must not move the expiry"
    )


async def test_a_cancelled_policy_cannot_be_renewed(svc):
    """DEFECT-PROVER. Status was never consulted: a cancelled policy returned
    "renewed" like any other."""
    pol = await _issue(svc)
    await svc.cancel_policy(pol["policy_id"], caller="0xALICE")
    out = await svc.renew_coverage(pol["policy_id"], 1e9, 365, caller="0xALICE")
    assert out["status"] == "rejected"
    assert "cancelled" in out["reason"]


async def test_a_lapsed_policy_renews_from_today_not_from_its_old_expiry(svc):
    """DEFECT-PROVER for a hazard the fix itself could have introduced.

    Extending a long-lapsed policy from its ORIGINAL expiry would sell cover
    for a period already past — the holder pays a year's premium and receives
    a month of future cover. The base is whichever of (old expiry, now) is
    later.
    """
    import time as _t
    pol = await _issue(svc)
    stored = svc._policies[pol["policy_id"]]
    stored["expires_at"] = int(_t.time()) - 400 * 86400  # lapsed a year ago
    stored["status"] = "expired"

    out = await svc.renew_coverage(pol["policy_id"], 1e9, 365, caller="0xALICE")

    assert out["status"] == "renewed"
    assert out["new_expiry"] > int(_t.time()) + 364 * 86400, (
        "a lapsed policy must renew forward from today, not from its lapse"
    )
