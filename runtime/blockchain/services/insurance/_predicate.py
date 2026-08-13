"""DOMAIN 18-E — the policyholder wrote the test their own payout is decided by.

THE DEFECT. `_build_trigger_conditions` lifted `metric`, `comparator` and
`threshold` verbatim out of the `coverage` dict the BUYER supplies at purchase
time, with no validation and no bounds. The oracle-routed verifier NEW-78
installed then evaluated that buyer-authored predicate against honest oracle
data. The code was entirely correct — it fetched live data, evaluated the
registered condition, failed closed on every fault. ONLY THE PROVENANCE OF THE
PREDICATE WAS WRONG, which is why a detector looking for a missing check found
nothing to flag: a check runs, against a number the beneficiary wrote.

Measured at the census pin, all with well-typed ordinary values and an HONEST
oracle reporting calm weather:

    metric="timestamp",  threshold=0,  "gt"  -> APPROVED 50,000
    metric="cached",     threshold=-1, "gt"  -> APPROVED 50,000  (a bool -> 0.0)
    magnitude_threshold=-1e9                 -> APPROVED on any HTTP 200
    delay_minutes=0                          -> APPROVED on any non-empty body

`metric` was the worst of the three: an UNRESTRICTED KEY LOOKUP into the oracle
envelope. The buyer did not need an implausible threshold — naming the
envelope's own clock was enough. Four of five policy types were riggable with a
single out-of-range number.

§AG — AND THIS ONE IS ABOUT OUR OWN FIX. 18-D made the weather alias resolve
(`temperature` -> the emitted `temp`). Before it, the SHIPPED DEFAULT weather
policy was dead: the metric never matched, so it denied every claim. After it,
the default resolves — and the shipped default `threshold=0` with comparator
`gt` pays out on ANY temperature above freezing. MEASURED post-18-D: a default
weather policy against an honest 21.0C reading returns `measured=True,
met=True`. 18-D removed a denial defect and armed a payout defect underneath
it. The census lane saw the precondition ("the honest default is dead, which
inverts the incentive") without knowing a later fix would revive it.

    §AG's detector, pointed at our own work: which of this engagement's fixes
    changed an input that THIS defect reads?

That is why there are NO DEFAULTS for decision numbers in this module. A
default threshold is a stated constraint that binds in the wrong direction
(§T): absence of a threshold is now a REFUSAL TO ISSUE, not a zero.

WHAT THIS MODULE DOES AND DOES NOT CLAIM. It enforces three things:

  1. `metric` must name a PERIL the platform actually insures — not an
     arbitrary key of whatever the gateway returned.
  2. `comparator` must be a direction that makes sense for that peril.
  3. `threshold` must be finite and must sit in the INSURABLE-EXTREME BAND for
     that peril — a policy must insure against a catastrophe, not a Tuesday.

The bands below are a PLATFORM POLICY DECISION ENCODED IN CODE. They are not
an actuarial model and this module does not claim to price anything. Their
basis is stated per entry so a reviewer can disagree with a specific number
rather than with an unexplained constant.

WHAT REMAINS OPEN, STATED RATHER THAN QUIETLY LEFT. Within a band the buyer
still chooses, and `FeeEngine.calculate_premium` never reads `metric`,
`comparator` or `threshold` — so a policy triggering at 35C and one triggering
at 55C cost exactly the same premium. This module bounds the abuse; it does not
price the residual. That residual is D18-FEE-C2 and it is registered, not
closed. Bounding an unbounded input to a band is a real control; calling it a
pricing fix would be the §AN.1 error — a clamp that turns unbounded abuse into
a uniform one, described as a safety rail.
"""

from __future__ import annotations

import math
from typing import Any, NamedTuple

__all__ = [
    "PREDICATE_SPECS",
    "PredicateError",
    "build_predicate",
    "trigger_ease",
]


class PredicateError(ValueError):
    """A trigger predicate the platform will not underwrite."""


class Band(NamedTuple):
    """An insurable-extreme band for one (metric, comparator) pair."""

    lo: float
    hi: float
    basis: str


#: policy_type -> {metric -> {comparator -> Band}}
#:
#: A metric absent from this table cannot be named by a buyer, which is what
#: stops `timestamp` and `cached` being used as measurements.
PREDICATE_SPECS: dict[str, dict[str, dict[str, Band]]] = {
    "weather": {
        "temperature": {
            # Heat cover must trigger above a genuine heat extreme. 35C is the
            # conventional heatwave threshold; 60C is above the highest
            # reliably recorded surface temperature, so a threshold beyond it
            # describes an event that cannot occur.
            "gt": Band(35.0, 60.0, "heat extreme; upper bound = above any recorded surface temperature"),
            # Freeze cover, mirrored. -10C is a hard freeze; -90C is below the
            # lowest recorded surface temperature.
            "lt": Band(-90.0, -10.0, "hard freeze; lower bound = below any recorded surface temperature"),
        },
        "wind_speed": {
            # 17 m/s is Beaufort 8 (gale). 120 m/s exceeds the strongest
            # measured surface gust.
            "gt": Band(17.0, 120.0, "gale force (Beaufort 8) and above, in m/s"),
        },
    },
    "flight_delay": {
        "delay_minutes": {
            # Below an hour is an inconvenience, not an insurable loss. 1440
            # minutes is a full day, beyond which the event is a cancellation.
            "gte": Band(60.0, 1440.0, "one hour to one day of delay"),
        },
    },
    "crop": {
        "rainfall_threshold_mm": {
            # Drought cover triggers BELOW the threshold, so the threshold is
            # the dry limit. Above 100mm over the measured period is not a
            # drought by any definition.
            "lt": Band(0.1, 100.0, "drought: rainfall below the stated limit, in mm"),
        },
    },
    "earthquake": {
        "magnitude_threshold": {
            # Below M4.0 is rarely damaging; M10.0 exceeds any recorded event.
            "gte": Band(4.0, 10.0, "moment magnitude; M4.0 is the damage threshold"),
        },
    },
    "smart_contract_hack": {
        "loss_threshold": {
            # The shipped default was 0, which made ANY reported loss — including
            # a zero one — satisfy the trigger. A loss floor must be positive.
            "gte": Band(1.0, math.inf, "reported loss floor; must be positive"),
        },
    },
}

#: The condition key each policy type carries its threshold under, and the
#: comparator the platform fixes for the non-weather perils. Only `weather`
#: lets the buyer choose a direction, because heat and freeze are genuinely
#: different products; the rest have one meaningful direction each.
_FIXED: dict[str, tuple[str, str]] = {
    "flight_delay": ("delay_minutes", "gte"),
    "crop": ("rainfall_threshold_mm", "lt"),
    "earthquake": ("magnitude_threshold", "gte"),
    "smart_contract_hack": ("loss_threshold", "gte"),
}

#: Descriptive fields a buyer may supply freely. These do NOT decide a payout,
#: so they are copied through unvalidated — enumerated here so that the set of
#: keys reaching a trigger record is closed rather than open (§T.2).
_DESCRIPTIVE: dict[str, tuple[str, ...]] = {
    "weather": ("location",),
    "flight_delay": ("flight_number",),
    "crop": ("location", "crop_type"),
    "earthquake": ("location",),
    "smart_contract_hack": ("contract_address",),
}


def trigger_ease(policy_type: str, conditions: dict) -> float | None:
    """How EASY the registered trigger is to satisfy, on 0.0..1.0. 18-P.

    1.0 is the easiest threshold the platform will underwrite (the near end of
    the insurable band), 0.0 the hardest (the far end). Returns ``None`` when
    the trigger cannot be placed on a bounded scale, which is a refusal to
    guess rather than a zero.

    THIS IS A DECLARED SCHEDULE, NOT A RISK MODEL, and the distinction is the
    whole reason it is safe to add. It does not estimate how often a peril
    occurs; it says where inside the platform's own declared band the buyer
    chose to sit. It lives here because the bands live here (18-E) — the
    alternative was a second copy of them in the fee engine.
    """
    spec = PREDICATE_SPECS.get(policy_type)
    if not spec:
        return None

    if policy_type == "weather":
        metric = conditions.get("metric")
        comparator = conditions.get("comparator")
        if metric not in spec or comparator not in spec.get(metric, {}):
            return None
        band = spec[metric][comparator]
        threshold = conditions.get("threshold")
    else:
        key, comparator = _FIXED[policy_type]
        band = spec[key][comparator]
        threshold = conditions.get(key)

    if threshold is None:
        return None
    try:
        value = float(threshold)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if not math.isfinite(band.lo) or not math.isfinite(band.hi):
        # `smart_contract_hack`'s loss floor is unbounded above, so there is no
        # scale to place a threshold on. Saying so beats inventing an upper
        # bound purely to make the arithmetic work.
        return None
    if band.hi == band.lo:
        return None

    position = (value - band.lo) / (band.hi - band.lo)
    position = min(1.0, max(0.0, position))

    # A `lt` trigger fires BELOW its threshold, so a HIGHER number is the
    # easier one; every other comparator fires above, where LOWER is easier.
    return position if comparator == "lt" else 1.0 - position


def _finite(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise PredicateError(
            f"{name} must be a number, got {value!r}"
        ) from None
    if not math.isfinite(out):
        raise PredicateError(
            f"{name} must be a finite number, got {value!r} — a non-finite "
            f"value satisfies neither bound of a range check and passes both"
        )
    return out


def _check_band(metric: str, comparator: str, threshold: float, band: Band) -> None:
    if not (band.lo <= threshold <= band.hi):
        raise PredicateError(
            f"threshold {threshold} for {metric} '{comparator}' is outside the "
            f"insurable range {band.lo}..{band.hi} ({band.basis}). A policy must "
            f"insure against an extreme, not against ordinary conditions."
        )


def build_predicate(policy_type: str, coverage: dict) -> dict[str, Any]:
    """Build a VALIDATED trigger predicate, or refuse to issue the policy.

    Raises :class:`PredicateError` rather than returning a predicate the
    platform will not stand behind. Refusing to issue is the conservative
    disposition: an unissued policy disappoints a buyer, while an issued one
    with a rigged predicate is a standing obligation to pay.

    Returns ``{}`` for a policy type that carries no parametric trigger, which
    is the pre-existing signal that no trigger should be registered.
    """
    spec = PREDICATE_SPECS.get(policy_type)
    if spec is None:
        return {}

    conditions: dict[str, Any] = {"policy_type": policy_type}
    for key in _DESCRIPTIVE.get(policy_type, ()):
        conditions[key] = coverage.get(key, "")

    if policy_type == "weather":
        metric = coverage.get("metric")
        if metric is None:
            raise PredicateError(
                "weather cover requires an explicit 'metric'. There is no safe "
                "default: the previous default named a field the weather oracle "
                "does not emit, and once that mismatch was corrected the "
                "accompanying default threshold of 0 paid out on any "
                "above-freezing reading."
            )
        if metric not in spec:
            raise PredicateError(
                f"'{metric}' is not an insurable weather peril. Permitted: "
                f"{sorted(spec)}. A metric outside this set is a key lookup "
                f"into the oracle envelope, not a measurement of a peril."
            )
        comparator = coverage.get("comparator")
        if comparator not in spec[metric]:
            raise PredicateError(
                f"comparator '{comparator}' is not offered for {metric}. "
                f"Permitted: {sorted(spec[metric])}."
            )
        if "threshold" not in coverage:
            raise PredicateError(
                "weather cover requires an explicit 'threshold'; there is no "
                "default (§AG: the previous default of 0 became a guaranteed "
                "payout the moment the metric alias was corrected)."
            )
        threshold = _finite(coverage["threshold"], "threshold")
        _check_band(metric, comparator, threshold, spec[metric][comparator])

        conditions["metric"] = metric
        conditions["comparator"] = comparator
        conditions["threshold"] = threshold
        return conditions

    key, comparator = _FIXED[policy_type]
    if key not in coverage:
        raise PredicateError(
            f"{policy_type} cover requires an explicit '{key}'; there is no "
            f"default, because a defaulted decision number is a payout "
            f"condition nobody chose."
        )
    threshold = _finite(coverage[key], key)
    _check_band(key, comparator, threshold, spec[key][comparator])
    conditions[key] = threshold
    return conditions
