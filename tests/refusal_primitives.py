"""The refusal vocabulary every name-matching detector must import. ONE list.

WHY THIS FILE EXISTS — a rename blinded a detector, and the silence read as
success.

Several controls in this suite recognise "this method can honestly refuse" by
looking for the NAME of a refusal primitive in the method's source:

    D6  test_uuid_mint_fabrication_shape.py   `_is_gated`, plus a file-level
                                              skip that drops any file not
                                              mentioning a primitive at all
    D7  test_fake_delivery_detector.py        the "real or refuses" token set
    D10 test_discarded_refusal_detector.py    `_refusing_methods`

NEW-94 wrapped `not_deployed_response` in `staking_not_deployed` so the whole
staking domain could gate on one switch — a rename made in good faith, to
improve the code. D6 matched the old literal and skipped files that never
mention it, so THE ENTIRE STAKING PACKAGE WENT INVISIBLE. Its gate-asymmetry
count fell from 7 classes / 11 methods to 6 / 10, and that drop was recorded as
confirmation that the staking asymmetry had been fixed. It was the opposite.

The demonstration was a controlled experiment, not an argument: an adversarial
verifier DISABLED EVERY STAKING GATE and re-ran D6. Still 6 / 10. Still no
staking entry. The count had fallen because the instrument had stopped looking.

A DETECTOR THAT GETS QUIETER WHEN YOU CHANGE THE THING IT WATCHES IS WORSE THAN
NO DETECTOR, because silence is indistinguishable from success. And the general
lesson is structural, not a bug in D6's logic — its logic was correct: ANY
name-matching control can be blinded by a rename, including a rename made to
improve the code.

WHY A REGISTRY RATHER THAN A FIX TO EACH DETECTOR. It makes the blinding
IMPOSSIBLE rather than detected. One place declares the vocabulary; every
name-matching detector imports it. A new wrapper either registers here, or the
detectors do not recognise it as a refusal at all — which fails LOUD (D10's
`test_every_refusal_wrapper_is_registered` goes red) instead of quiet.

THIS FILE IS LOAD-BEARING FOR THREE CONTROLS, so it is itself proven rather
than trusted — see tests/test_refusal_registry.py:

  * no detector may match a refusal name it did not get from here, or the class
    comes back one hardcoded literal at a time;
  * adding a name must make the detectors see a new wrapper, and removing one
    must make them stop — a shared dependency that is not mutation-tested is a
    single point of silent failure for all three.

Callers must use `mentions_refusal()` / `is_refusal_name()` rather than reading
`REFUSAL_PRIMITIVES` into a module-level binding of their own: the functions
resolve the tuple at CALL time, which is what lets the registry be mutated in a
test and is exactly the indirection that keeps the three detectors honest.
"""

from __future__ import annotations

#: Every function that can produce an honest refusal on a caller's behalf.
REFUSAL_PRIMITIVES: tuple[str, ...] = (
    "not_deployed_response",       # the primitive (runtime/blockchain/web3_manager.py)
    "staking_not_deployed",        # NEW-94 wrapper (services/staking/arming.py)
    # 19-A wrapper (services/restaking/_guards.py).
    #
    # NAMED `require_restaking_enabled`, NOT `require_enabled`, AND THE REASON
    # IS A MEASURED FALSE POSITIVE. `mentions_refusal` matches by SUBSTRING, so
    # registering the shorter name made every call site of the PRE-EXISTING,
    # unrelated `RealEstateService._require_enabled` (service.py:114) classify
    # as a refusal wrapper. D10 then reported two "discards" in real_estate
    # that are correct code: `get_property` RAISES on absence, and its callers
    # discard the return deliberately — `# 404-equivalent if absent`.
    #
    # A substring-matched registry is only as safe as the DISTINCTIVENESS of
    # the names in it. Any entry that is a substring of an unrelated identifier
    # silently widens the graph and manufactures findings. Register
    # domain-qualified names.
    "require_restaking_enabled",
)


def mentions_refusal(source: str) -> bool:
    """True if this source text can produce a refusal through any primitive."""
    return any(p in source for p in REFUSAL_PRIMITIVES)


def is_refusal_name(name: str | None) -> bool:
    """True if `name` is a registered refusal primitive."""
    return name in REFUSAL_PRIMITIVES
