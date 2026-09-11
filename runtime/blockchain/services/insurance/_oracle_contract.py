"""DOMAIN 18-D — the oracle contract: where a measurement lives, and what it
is called.

THE DEFECT THIS FILE EXISTS TO PREVENT. Five condition evaluators each read
their decision field off the top level of an ``OracleGateway`` response and
substituted a hard-coded default when it was absent:

    delay_minutes -> 0        rainfall_mm  -> 999      magnitude -> 0
    loss_amount   -> 0        hack_detected -> False

The field was never present, and EVERY DEFAULT FAVOURS THE INSURER. Measured
end to end pre-fix: a flight delayed 300 minutes against a 120-minute
threshold evaluated ``met = False``; rainfall 2mm against a 50mm drought
threshold, ``False``; magnitude 7.8 against 5.0, ``False``; a confirmed
$2,000,000 hack against a $100,000 threshold, ``False``. The control that
proves it is the key and not the arithmetic: the same reading with the metric
renamed to the key the provider actually emits evaluated ``met = True``.

THE MEASUREMENT LIVES IN A DIFFERENT PLACE DEPENDING ON THE ORACLE TYPE, which
is why no individual reader could be correct:

  * ``weather`` — ``_handle_weather`` returns WeatherOracle's canonical shape,
    which the gateway merges INTO the envelope. The measurement is FLAT, and
    the mismatch is the NAME: the policy default metric is ``temperature``
    while ``WeatherOracle._normalise_current`` emits ``temp``.
  * ``flight_delay`` / ``crop`` / ``earthquake`` / ``smart_contract_hack`` —
    all route through ``_handle_custom``, which NESTS the provider body under
    ``"data"``. The measurement is one level DOWN.

Two shapes, one class of defect. A reader that knows one shape is wrong about
the other, so the contract cannot live in the readers — it lives here, and
both sides conform to it.

THE SECOND HALF, WHICH IS A SEPARATE DEFECT. ``_verify_via_oracle`` guarded
itself with ``if not oracle_data``. That tests the ENVELOPE, not the
MEASUREMENT — and the envelope is never empty, because the gateway always
merges ``oracle_type``, ``cached`` and ``timestamp`` into it. So a ``data: {}``
body — the shape ``_handle_custom`` returns for any HTTP 200 whose payload did
not parse — passed the guard, the defaults fired, and flight_delay, crop and
earthquake all APPROVED AT FULL PAYOUT on a measurement nobody took.

The same key mismatch therefore denies every honest claim AND approves on an
empty payload, with the outcome decided only by which way the comparator
points. ``extract_measurement`` is the fix for both halves: it returns ``None``
when there is no measurement, and ``None`` is not a reading.

§AC. An absent measurement must not be reportable as a negative one. Every
evaluator here returns a three-valued :class:`Verdict` — met / not met /
NOT MEASURED — because a shape-based control that sees only ``False`` cannot
tell a real "the event did not happen" from an honest "we could not check",
and a claimant is owed the true one.

§T.2 — ALIASES ARE MEASURED, NEVER INVENTED. ``FIELD_ALIASES`` carries exactly
one alias, ``temperature`` -> ``temp``, because that is the one an emitter in
this repository was OBSERVED to produce (``WeatherOracle._normalise_current``,
pinned by ``test_the_weather_oracle_still_emits_the_key_this_contract_names``).
The custom-backed trigger types are fed by a config-supplied provider URL:
there is no platform-side emitter to conform to, so no alias for them can be
established, and inventing one would fabricate a control. For those, absence
of the canonical field means NOT MEASURED — which is the honest reading.
"""

from __future__ import annotations

import math
from typing import Any, NamedTuple

__all__ = [
    "ENVELOPE_KEYS",
    "FIELD_ALIASES",
    "Verdict",
    "extract_measurement",
    "read_measurement",
]

#: Keys the gateway merges into every response regardless of oracle type.
#: These describe the RESPONSE, not the thing measured.
ENVELOPE_KEYS: frozenset[str] = frozenset({"oracle_type", "cached", "timestamp"})

#: Canonical field name -> key names an emitter in this repository is MEASURED
#: to produce. Order is preference order. See §T.2 in the module docstring:
#: this map is evidence, not guesswork.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    # WeatherOracle._normalise_current / _normalise_historical emit "temp".
    "temperature": ("temperature", "temp"),
}


class Verdict(NamedTuple):
    """A trigger evaluation that can say "I could not tell".

    ``met`` is only meaningful when ``measured`` is True. A caller that reads
    ``met`` alone gets a fail-closed answer, which is safe but not honest;
    callers that report a decision to a claimant must read ``measured`` too.
    """

    met: bool
    measured: bool
    reason: str


def extract_measurement(envelope: Any) -> dict[str, Any] | None:
    """Return the MEASUREMENT inside an OracleGateway response, or ``None``.

    ``None`` means NO MEASUREMENT WAS OBTAINED. It is never a reading, and it
    must never be defaulted into one.

    Handles both response shapes (see the module docstring): a ``"data"`` key
    marks a ``_handle_custom``-shaped response whose provider body is nested,
    and its absence marks a handler that merged its canonical shape into the
    envelope.
    """
    if not isinstance(envelope, dict):
        return None

    if "data" in envelope:
        # Custom-backed handlers nest the provider body. An empty or non-dict
        # body is NOT a measurement — this is the half of the defect that let
        # `data: {}` through `if not oracle_data` and approved a full payout.
        inner = envelope["data"]
        return inner if isinstance(inner, dict) and inner else None

    payload = {k: v for k, v in envelope.items() if k not in ENVELOPE_KEYS}
    return payload or None


def read_measurement(data: dict[str, Any], field: str) -> Any | None:
    """Read *field* from a measurement, returning ``None`` when it is absent.

    THE WHOLE POINT IS THE MISSING DEFAULT. Every caller of this function
    previously supplied one, and every default it supplied favoured the
    insurer. ``None`` here means the oracle did not report this field, which
    is a different fact from "the oracle reported zero".
    """
    for key in FIELD_ALIASES.get(field, (field,)):
        if key in data and data[key] is not None:
            return data[key]
    return None


def read_number(data: dict[str, Any], field: str) -> float | None:
    """Read *field* as a finite number, or ``None`` if absent/unusable.

    A non-finite reading is treated as NOT MEASURED rather than as a value.
    NaN satisfies neither half of an ordered comparison (§W's fifth guard
    shape, 17-B), so admitting one would put a value into the comparison that
    the comparison cannot bound — and calling that "not met" would be the
    §AC conflation this module exists to prevent.
    """
    raw = read_measurement(data, field)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None
