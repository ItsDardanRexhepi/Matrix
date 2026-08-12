"""The refusal primitives every detector must recognise. ONE list, shared.

WHY THIS FILE EXISTS — a wrapper blinded two detectors, not one.

Several controls in this suite recognise "this method can honestly refuse" by
looking for the NAME of the refusal primitive in the method's source:

    D6  test_uuid_mint_fabrication_shape.py   `_is_gated`, and a file-level
                                              skip that drops any file not
                                              mentioning the primitive at all
    D10 test_discarded_refusal_detector.py    `_refusing_methods`

Name-matching means WRAPPING the primitive in a helper hides every caller of
that helper from every one of them, simultaneously and silently — the
detectors keep reporting green over code they can no longer see.

NEW-94 did exactly this. It introduced `staking_not_deployed` (a thin wrapper
around `not_deployed_response`) to gate the whole staking domain on one switch,
and removed the primitive's name from all three staking sources. D10 was
updated in the same commit. D6 WAS NOT, and the consequence was worse than a
blind spot:

    D6's gate-asymmetry count fell from 7 classes / 11 methods to 6 / 10, and
    that drop was read as evidence the staking asymmetry had been FIXED.
    It was not evidence of anything. The file-level skip had simply stopped
    reading the staking package. An adversarial verifier proved it by
    disabling every staking gate and re-running D6: still 6 / 10, still no
    staking entry.

A number that moves for the right reason and a number that moves because the
instrument stopped looking are indistinguishable from the outside. That is the
failure this file prevents: register a wrapper ONCE, here, and every detector
that imports this list keeps its reach.

If you add a new refusal wrapper, add it below. D10's
`test_every_refusal_wrapper_is_registered` fails until you do.
"""

from __future__ import annotations

#: Every function that can produce an honest refusal on a caller's behalf.
REFUSAL_PRIMITIVES: tuple[str, ...] = (
    "not_deployed_response",       # the primitive (runtime/blockchain/web3_manager.py)
    "staking_not_deployed",        # NEW-94 wrapper (services/staking/arming.py)
)


def mentions_refusal(source: str) -> bool:
    """True if this source text can produce a refusal through any primitive."""
    return any(p in source for p in REFUSAL_PRIMITIVES)
