"""A refusal must never outrank a capability that works.

WHY THIS EXISTS. Making the sixteen `unavailable` entries speak changed what a
mis-ranked match COSTS. Before, an unavailable entry winning the top slot was
harmless: its guide carried no `action_name`, the consumer raised KeyError, and
the whole enrichment was discarded — the user simply got no grounding. After, the
same mis-ranking produces "NOT AVAILABLE ... Do not attempt this action and do
not imply it succeeded."

So a silent ranking quirk became a loud wrong answer, and over-firing is
invisible to the existing control, which only proves that GIBBERISH stays silent.
This file uses real utterances that currently work.

MEASURED AT THE TIME OF WRITING: 916 probes — every keyword of every one of the
192 available actions — and ZERO were displaced by an unavailable entry. Both
collisions reported by an adversarial pass (deploy_contract intruding on social
composition, request_deletion masking check_privacy_dependencies on its own
canonical utterance) were REFUTED by driving them.

ONE REAL EDGE SURVIVED, and it is the reason for the tie-break: `permanent
storage` scores exactly 3.0 for BOTH decentralized_store (works) and
arweave_store (unavailable). The working one won — by dict insertion order, not
by design. One reordering and a working capability would start refusing.

THE DISPOSITION RULE, applied: if an unavailable notice displaces a working
capability, the fix is scoping or ranking — never accepting a degraded working
path because the refusal is honest. An honest message that costs a user a working
feature is a net loss.
"""

from __future__ import annotations

import pytest

from runtime.chat.intent_actions import INTENT_ACTION_MAP, match_intent

UNAVAILABLE = {a for a, g in INTENT_ACTION_MAP.items() if g.get("unavailable")}
AVAILABLE = {a for a in INTENT_ACTION_MAP if a not in UNAVAILABLE}


def _name_of(entry: dict) -> str | None:
    """match_intent returns a copy without its key, so the entry must be
    resolved by content.

    RESOLVE BY KEYWORDS, NOT DESCRIPTION. The first version of this helper keyed
    on `description` and silently mis-resolved six entries that shared one — it
    reported 11/16 reachable when the real figure was 16/16, an artifact of the
    measuring tool rather than a fact about the code. Keywords are unique per
    entry and that uniqueness is itself enforced by
    tests/test_intent_keyword_uniqueness.py, so it is a safe key; description
    uniqueness was never a property anyone guaranteed.
    """
    probe = tuple(entry.get("keywords") or ())
    for action, guide in INTENT_ACTION_MAP.items():
        if tuple(guide.get("keywords") or ()) == probe:
            return action
    return None


def test_no_working_action_is_displaced_on_its_own_keywords():
    """THE RATCHET, at zero. Every keyword of every available action, checked
    against the entry that would actually answer it."""
    displaced = []
    for action in sorted(AVAILABLE):
        for keyword in INTENT_ACTION_MAP[action].get("keywords") or []:
            matches = match_intent(keyword)
            if not matches:
                continue
            winner = _name_of(matches[0])
            if winner in UNAVAILABLE:
                displaced.append(f"{action}: {keyword!r} now answered by {winner}")

    assert not displaced, (
        "a working capability is being refused on its own canonical wording — "
        "fix by scoping keywords or ranking, NOT by accepting it because the "
        f"refusal is honest:\n  " + "\n  ".join(displaced)
    )


def test_availability_breaks_a_score_tie():
    """THE SPECIFIC EDGE. Both score 3.0; the one that works must win."""
    matches = match_intent("permanent storage")

    assert _name_of(matches[0]) == "decentralized_store"
    assert matches[1]["score"] == matches[0]["score"], (
        "the scores are no longer tied — this test is no longer exercising the "
        "tie-break it was written for"
    )
    assert _name_of(matches[1]) == "arweave_store"


def test_the_ranking_does_not_depend_on_dict_insertion_order():
    """PROOF THAT THE TIE-BREAK IS REAL, not luck.

    At the previous commit the sort key was the score alone, so a tie resolved to
    whichever entry `INTENT_ACTION_MAP` happened to yield first. Rebuilding the
    map in reverse order flipped the winner to the unavailable entry. With
    availability in the sort key the result is invariant, which is the property
    that actually matters — nobody will notice a dict reordering, and the failure
    it would cause is a working feature answering "not available".
    """
    import runtime.chat.intent_actions as mod

    original = mod.INTENT_ACTION_MAP
    try:
        mod.INTENT_ACTION_MAP = dict(reversed(list(original.items())))
        reversed_winner = mod.match_intent("permanent storage")[0]
        # resolve against the reversed map, same description-based lookup
        name = next(
            (a for a, g in mod.INTENT_ACTION_MAP.items()
             if g.get("description") == reversed_winner.get("description")),
            None,
        )
    finally:
        mod.INTENT_ACTION_MAP = original

    assert name == "decentralized_store", (
        "the tie resolves differently when the map is reordered — ranking is "
        "still decided by insertion order, so a working capability is one "
        "refactor away from refusing"
    )


def test_the_order_is_total():
    """No pair of returned matches is ambiguous: equal scores are further
    ordered by availability then name, so repeated calls cannot disagree."""
    for probe in ("permanent storage", "payment", "vote", "storage", "deploy"):
        first = [(_name_of(m), m["score"]) for m in match_intent(probe)]
        again = [(_name_of(m), m["score"]) for m in match_intent(probe)]
        assert first == again, f"{probe!r} does not rank deterministically"


@pytest.mark.parametrize(
    "utterance",
    [
        "post this to my feed",
        "check privacy dependencies",
        "privacy dependencies",
        "check my data dependencies",
        "post this to my feed: I just deployed a contract",
    ],
)
def test_the_reported_collisions_do_not_reproduce(utterance):
    """THE TWO REPORTED CASES, pinned as refuted.

    Recorded rather than discarded: a refuted finding is still worth a test, so
    that if the collision ever becomes real it is caught here instead of being
    re-reported and re-investigated from scratch.
    """
    matches = match_intent(utterance)
    if not matches:
        return
    assert _name_of(matches[0]) not in UNAVAILABLE, (
        f"{utterance!r} is now answered by an unavailable capability"
    )


def test_making_the_sixteen_speak_did_not_silence_them():
    """SCOPE PIN, the other way. The tie-break must not push unavailable entries
    out of the results altogether — they still have to reach the user, which is
    the whole point of the repair this hardens."""
    reachable = sum(
        1 for action in UNAVAILABLE
        if any(_name_of(m) == action for m in match_intent(
            INTENT_ACTION_MAP[action]["keywords"][0])[:2])
    )

    assert reachable >= 14, (
        f"only {reachable}/16 unavailable entries appear in the top two for "
        "their own keyword — the tie-break has started suppressing them"
    )
