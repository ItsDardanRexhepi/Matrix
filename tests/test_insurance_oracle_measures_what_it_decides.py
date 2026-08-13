"""DOMAIN 18-D — the oracle read the wrong key, and every default favoured the
insurer.

ONE DEFECT, THREE LENSES. This was filed by three separate census lanes as
three findings — "false-refusal-attested-as-measurement", "the refusal
misstates its ground", and "the shipped-default metric mismatch". They are one
key mismatch seen from three positions, and disposing them separately would
have produced three partial fixes. §AK.2: a fix that names one call site while
several share the defect is a half-fix by construction.

THE MECHANISM. Five condition evaluators each read their decision field off the
TOP LEVEL of an OracleGateway response and substituted a hard-coded default
when it was absent:

    delay_minutes -> 0     rainfall_mm -> 999     magnitude -> 0
    loss_amount   -> 0     hack_detected -> False

The field was never at the top level, so every evaluation ran on defaults, and
EVERY DEFAULT FAVOURS THE INSURER.

AND THE MEASUREMENT LIVES SOMEWHERE DIFFERENT DEPENDING ON THE ORACLE TYPE,
which is why no individual reader could have been right:

    weather                  -> merged FLAT into the envelope; the mismatch is
                                the NAME ("temperature" vs the emitted "temp")
    flight_delay / crop /    -> routed through _handle_custom, which NESTS the
    earthquake / hack           provider body under "data"

THE TWO DIRECTIONS ARE WHAT MAKE IT WORSE THAN A DENIAL BUG — and their
PRECONDITIONS DIFFER, which is the part worth stating precisely:

    honest claim, real measurement    -> DENIED, 5 of 5 trigger types.
                                         Needs nothing: the shipped default
                                         against the platform's own oracle.

    empty `data: {}`, claimant-chosen -> APPROVED at full payout, 3 of 5.
    threshold                            Needs the claimant to pick the
                                         threshold, which the API lets them do
                                         (§U composing with 18-D).

Both measured at 462d317. At the SHIPPED thresholds an empty payload happens
to deny in all five — luck, not a control, and the ground it reports is false
either way. The approval direction is reached by
`_build_trigger_conditions` reading every threshold from caller-supplied
`coverage`: delay_minutes=0 against a fabricated 0, magnitude_threshold=0
against a fabricated 0, rainfall_threshold_mm=1000 against a fabricated 999.

The two that resist do so by accident of shape, not by control: `hack` needs a
conjunction whose other term defaults False, and `weather` already refused an
absent reading (`if value is None: return False`) — it was not fabricating a
value, it was looking in the wrong place. One of the five evaluators had the
right instinct and still returned the wrong answer.

§AM — WHY THREE INDEPENDENT READERS STALLED ON `_verify_via_oracle`.
The method is exceptionally well written. It fails closed on every enumerated
case, and its docstring explicitly forbids the exact conflation it commits:
"cannot verify must never read as verified". Its guard, `if not oracle_data`,
tests the ENVELOPE and never the MEASUREMENT — it asks whether the oracle
replied, never whether it replied about the thing we insured. The care in the
method is what stopped anyone looking past it.

    An artifact that explicitly names the failure it is committing reads as
    immune to it.

That is a stronger §AM instance than the four before it: §W.1 was
sophistication suppressing the question, §AM.2 was unresponsiveness reading as
inertness. This is A STATED COMMITMENT TO A PRINCIPLE READING AS EVIDENCE THE
PRINCIPLE HOLDS — the most transferable of the family, because "the code says
it doesn't do X" is exactly the kind of thing a reviewer treats as settling the
question.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.insurance._oracle_contract import (
    FIELD_ALIASES,
    extract_measurement,
    read_number,
)
from runtime.blockchain.services.insurance.trigger_manager import TriggerManager

CONFIG: dict = {"insurance": {}}


@pytest.fixture
def tm() -> TriggerManager:
    return TriggerManager(CONFIG)


def _custom(body: dict) -> dict:
    """A gateway envelope as `_handle_custom` actually builds one."""
    return {
        "oracle_type": "custom",
        "cached": False,
        "timestamp": 1_700_000_000,
        "url": "https://provider.example/api",
        "method": "GET",
        "status_code": 200,
        "data": body,
    }


def _weather(body: dict) -> dict:
    """A gateway envelope as `_handle_weather` actually builds one — the
    WeatherOracle shape is merged FLAT, not nested."""
    return {
        "oracle_type": "weather",
        "cached": False,
        "timestamp": 1_700_000_000,
        **body,
    }


async def _trigger(tm: TriggerManager, ttype: str, conditions: dict) -> dict:
    return await tm.register_trigger("pol-1", ttype, conditions)


# ══════════════════════════════════════════════════════════════════════════
# Direction one: the honest claimant, denied
# ══════════════════════════════════════════════════════════════════════════


async def test_a_real_flight_delay_is_measured_rather_than_defaulted(tm):
    """DEFECT-PROVER. Pre-fix: `data.get("delay_minutes", 0)` read the
    ENVELOPE, found nothing, and evaluated 0 >= 120 -> False. A passenger
    delayed five hours was told their trigger was not satisfied."""
    trig = await _trigger(tm, "flight_delay", {"delay_minutes": 120})
    v = await tm.evaluate_condition_detailed(
        trig, oracle_data=_custom({"delay_minutes": 300}),
    )
    assert v.measured is True
    assert v.met is True, "a 300-minute delay must satisfy a 120-minute trigger"


async def test_a_real_drought_is_measured_rather_than_defaulted(tm):
    """DEFECT-PROVER, AND THE SHARPEST OF THE FIVE DEFAULTS. `rainfall_mm`
    defaulted to 999 — a fabricated downpour. Crop cover triggers when
    rainfall falls BELOW the threshold, so the default denied every drought
    claim the policy existed to pay."""
    trig = await _trigger(tm, "crop", {"rainfall_threshold_mm": 50})
    v = await tm.evaluate_condition_detailed(
        trig, oracle_data=_custom({"rainfall_mm": 2.0}),
    )
    assert v.measured is True
    assert v.met is True, "2mm against a 50mm drought threshold is a drought"


async def test_a_real_earthquake_is_measured_rather_than_defaulted(tm):
    """DEFECT-PROVER. `magnitude` defaulted to 0 — no earthquake, ever."""
    trig = await _trigger(tm, "earthquake", {"magnitude_threshold": 5.0})
    v = await tm.evaluate_condition_detailed(
        trig, oracle_data=_custom({"magnitude": 7.8}),
    )
    assert v.measured is True
    assert v.met is True


async def test_a_confirmed_hack_is_measured_rather_than_defaulted(tm):
    """DEFECT-PROVER. `hack_detected` defaulted to False, so the conjunction
    was False regardless of the loss. Note the two defaults pointed in
    OPPOSITE directions on the same reading: `loss_amount` defaulted to 0.0,
    which satisfies the shipped default threshold of 0."""
    trig = await _trigger(tm, "smart_contract_hack", {"loss_threshold": 100_000})
    v = await tm.evaluate_condition_detailed(
        trig, oracle_data=_custom({"hack_detected": True, "loss_amount": 2_000_000}),
    )
    assert v.measured is True
    assert v.met is True


async def test_the_shipped_weather_default_reads_the_key_the_oracle_emits(tm):
    """DEFECT-PROVER, AND THE ONE THAT NEEDS NO ATTACKER.

    `_build_trigger_conditions` defaults a weather policy's metric to
    "temperature". `WeatherOracle._normalise_current` emits "temp". Nobody has
    to do anything wrong for this to fire: it is the platform's own default
    policy against the platform's own oracle, and pre-fix every such policy
    denied every claim.
    """
    trig = await _trigger(tm, "weather", {"metric": "temperature",
                                          "threshold": 40.0, "comparator": "gt"})
    v = await tm.evaluate_condition_detailed(
        trig, oracle_data=_weather({"location": "Phoenix", "temp": 47.2}),
    )
    assert v.measured is True
    assert v.met is True, "47.2C must exceed a 40C threshold"


# ══════════════════════════════════════════════════════════════════════════
# Direction two: the empty payload, approved
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("ttype,conditions", [
    ("flight_delay", {"delay_minutes": 120}),
    ("crop", {"rainfall_threshold_mm": 50}),
    ("earthquake", {"magnitude_threshold": 5.0}),
    ("smart_contract_hack", {"loss_threshold": 0}),
    ("weather", {"metric": "temperature", "threshold": 0, "comparator": "gte"}),
])
async def test_an_empty_payload_is_not_a_measurement(tm, ttype, conditions):
    """DEFECT-PROVER — THE OTHER HALF, AND A SEPARATE GUARD DEFECT.

    `data: {}` is what `_handle_custom` returns for any HTTP 200 whose body did
    not parse. The envelope around it is non-empty, so `if not oracle_data`
    passed it straight through to evaluators that then decided on defaults.

    MEASURED, NOT ASSUMED: at these SHIPPED thresholds the pre-fix defaults all
    happened to DENY. That is luck, not a control — see the test below, which
    is where the payout actually comes from. What is wrong at these thresholds
    is the GROUND: the claimant was told the trigger was not satisfied when
    nothing had been measured. `measured` is the field that fixes it (§AC);
    fail-closed alone would be safe and still dishonest.
    """
    trig = await _trigger(tm, ttype, conditions)
    v = await tm.evaluate_condition_detailed(trig, oracle_data=_custom({}))
    assert v.measured is False
    assert v.met is False


@pytest.mark.parametrize("ttype,conditions", [
    ("flight_delay", {"delay_minutes": 0}),
    ("earthquake", {"magnitude_threshold": 0}),
    ("crop", {"rainfall_threshold_mm": 1000}),
])
async def test_a_claimant_cannot_pick_a_threshold_its_own_default_satisfies(
    tm, ttype, conditions,
):
    """DEFECT-PROVER — THE APPROVAL DIRECTION, AND §U COMPOSING WITH 18-D.

    `_build_trigger_conditions` reads EVERY threshold from the caller-supplied
    `coverage` dict. So the claimant chooses the number the fabricated default
    is compared against, and can choose one the default satisfies:

        delay_minutes=0          -> fabricated 0   >= 0     -> APPROVED
        magnitude_threshold=0    -> fabricated 0   >= 0     -> APPROVED
        rainfall_threshold_mm=1000 -> fabricated 999 < 1000 -> APPROVED

    Measured at 462d317: 3 of 5 trigger types approve a full payout on a
    `data: {}` body. The remaining two deny for reasons that are accidents of
    shape, not controls — `hack` needs a conjunction whose other term defaults
    False, and `weather` already refused an absent reading (`if value is None`)
    and was merely reading the wrong key.

    THE PRECONDITIONS OF THE TWO DIRECTIONS DIFFER, which is worth stating
    precisely: the denial half needs nothing at all — it is the shipped default
    against the platform's own oracle. The approval half needs the claimant to
    choose the threshold, which the API lets them do.
    """
    trig = await _trigger(tm, ttype, conditions)
    v = await tm.evaluate_condition_detailed(trig, oracle_data=_custom({}))
    assert v.measured is False
    assert v.met is False, (
        "an unmeasured trigger must never satisfy a claimant-chosen threshold"
    )


async def test_a_refusal_says_it_could_not_check_not_that_nothing_happened(tm):
    """DEFECT-PROVER (§AC). The whole point of the three-valued verdict: a
    claimant denied because the oracle was silent is owed a different sentence
    from one denied because the event did not occur."""
    trig = await _trigger(tm, "earthquake", {"magnitude_threshold": 5.0})
    v = await tm.evaluate_condition_detailed(trig, oracle_data=_custom({"foo": 1}))
    assert v.measured is False
    assert "could not be checked" in v.reason
    assert "magnitude" in v.reason, "the refusal must name the field it wanted"


async def test_a_nested_body_is_not_confused_with_a_flat_one(tm):
    """DEFECT-PROVER. The contract is the only place that knows the shape
    differs by oracle type. A custom envelope whose ENVELOPE carries a
    plausible-looking key must not be read as a measurement."""
    trig = await _trigger(tm, "earthquake", {"magnitude_threshold": 5.0})
    envelope = _custom({})
    envelope["magnitude"] = 9.9  # sitting in the envelope, not the payload
    v = await tm.evaluate_condition_detailed(trig, oracle_data=envelope)
    assert v.measured is False, "an envelope key is not a provider measurement"


# ══════════════════════════════════════════════════════════════════════════
# Scope pins — these must have held BEFORE the fix too
# ══════════════════════════════════════════════════════════════════════════


async def test_a_genuine_non_event_still_does_not_trigger(tm):
    """SCOPE PIN. Uses only the pre-existing boolean API. Healthy rainfall
    against a drought threshold must still refuse to pay."""
    trig = await _trigger(tm, "crop", {"rainfall_threshold_mm": 50})
    assert await tm.evaluate_condition(
        trig, oracle_data=_custom({"rainfall_mm": 140.0}),
    ) is False


async def test_a_below_threshold_delay_still_does_not_trigger(tm):
    """SCOPE PIN — pre-existing boolean API, honest negative."""
    trig = await _trigger(tm, "flight_delay", {"delay_minutes": 120})
    assert await tm.evaluate_condition(
        trig, oracle_data=_custom({"delay_minutes": 30}),
    ) is False


async def test_an_unknown_trigger_type_still_fails_closed(tm):
    """SCOPE PIN — pre-existing boolean API."""
    trig = await _trigger(tm, "not_a_real_type", {})
    assert await tm.evaluate_condition(trig, oracle_data=_custom({"x": 1})) is False


# ══════════════════════════════════════════════════════════════════════════
# The contract, pinned rather than the individual reads
# ══════════════════════════════════════════════════════════════════════════


def test_the_weather_oracle_still_emits_the_key_this_contract_names():
    """THE CONTRACT PIN, AND THE REASON THE ALIAS MAP IS EVIDENCE.

    §T.2: aliases are MEASURED, never invented. `FIELD_ALIASES` claims
    WeatherOracle emits "temp". This test reads the emitter and fails if that
    stops being true — which is what makes both sides conform to the contract
    rather than to each other's current behaviour. If this test ever fails,
    the alias map is stale, not the oracle.
    """
    from runtime.blockchain.services.oracle_gateway.weather_oracle import (
        WeatherOracle,
    )

    shape = WeatherOracle._normalise_current(
        {"main": {"temp": 21.0}, "wind": {}, "weather": [{"description": "clear"}]},
        "Testville",
    )
    aliases = FIELD_ALIASES["temperature"]
    assert any(k in shape for k in aliases), (
        f"WeatherOracle emits {sorted(shape)}; the contract expects one of "
        f"{aliases}"
    )
    assert read_number(shape, "temperature") == 21.0


def test_a_non_finite_reading_is_not_measured_rather_than_not_met():
    """DEFECT-PROVER at the contract. §W's fifth guard shape, 17-B: a NaN
    satisfies neither half of an ordered comparison, so admitting one puts a
    value into the comparison the comparison cannot bound. Calling that
    "not met" would be the §AC conflation in a new costume."""
    assert read_number({"magnitude": float("nan")}, "magnitude") is None
    assert read_number({"magnitude": float("inf")}, "magnitude") is None
    assert read_number({"magnitude": 6.1}, "magnitude") == 6.1


def test_a_bare_envelope_carries_no_measurement():
    """DEFECT-PROVER at the contract. This is the exact input that made
    `if not oracle_data` a false guard: truthy, and empty of anything the
    policy insures."""
    assert extract_measurement(
        {"oracle_type": "weather", "cached": False, "timestamp": 1}
    ) is None
    assert extract_measurement(_custom({})) is None
    assert extract_measurement(None) is None
