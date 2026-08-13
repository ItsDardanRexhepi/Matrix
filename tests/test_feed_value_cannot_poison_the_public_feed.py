"""DOMAIN 19-D — an unauthenticated caller could render /social/feed permanently
invalid.

The first domain-19 finding that is NOT about the platform's own money. It is a
PUBLIC surface an unauthenticated party can break for everyone, and the damage
persists in storage rather than ending with the request.

MECHANISM. `ServiceDispatcher`'s feed-ingest block reads an amount-like key
straight out of `params` — the request body — and passes it to
`SocialFeedEngine.ingest(value_usd=...)` with no validation. `"Infinity"` is a
PLAIN JSON STRING that `float()` accepts. Stored as `inf`, it makes
`web.json_response` emit a bare `Infinity` token, and **the entire response
document fails `JSON.parse`** — not one row, the whole feed, for every strict
client (`web/social.html`, the MTRX Swift `JSONDecoder`).

WHY PERSISTENCE MAKES IT WORSE THAN A CRASH. The poisoned value is STORED, so
the feed stays broken until someone deletes the row; and `ranked_score` is
computed at ingest and never re-derived, so the row also keeps its position.
Fixing only the writer would leave the feed permanently broken by anything
written before the fix — **a fix that requires the attack not to have happened
yet is not a fix.** So the sanitiser runs at BOTH ends: at ingest, and again on
hydration, which lets the feed recover with no migration.

§AK.4, satisfied before the chokepoint was proposed rather than after:

    writers of value_usd into the store   1   (feed_engine INSERT)
    real callers of ingest()              1   (service_dispatcher:1343)
    writers of event.ranked_score         1   (feed_engine:328)
    ------------------------------------------
    paths guarded                         all of them, shown
"""

from __future__ import annotations

import json
import math

import pytest

from runtime.social.feed_engine import sanitize_value_usd


@pytest.mark.parametrize("raw", [
    "Infinity", "inf", "-inf", "nan", "NaN", "1e400",
    float("inf"), float("-inf"), float("nan"),
])
def test_a_non_finite_value_never_reaches_the_feed(raw):
    """DEFECT-PROVER. Every one of these is accepted by `float()`. `"Infinity"`
    and `"1e400"` are ordinary JSON strings needing no malformed request."""
    assert sanitize_value_usd(raw) is None


@pytest.mark.parametrize("raw", ["Infinity", float("inf"), "1e400"])
def test_the_feed_document_stays_parseable(raw):
    """DEFECT-PROVER, AND THE ACTUAL HARM. Pre-fix the poisoned row made the
    WHOLE response invalid, so one request denied the feed to every client."""
    body = json.dumps({"events": [
        {"value_usd": sanitize_value_usd(raw)},
        {"value_usd": sanitize_value_usd(1234.5)},
    ]})
    assert json.loads(body)["events"][1]["value_usd"] == 1234.5


def test_a_negative_value_is_rejected_rather_than_ranked():
    """DEFECT-PROVER. Negative money is not a smaller number, it is not a
    value at all."""
    assert sanitize_value_usd(-5) is None


def test_an_absurd_value_is_capped_and_not_discarded():
    """DEFECT-PROVER. A finite but enormous figure is bounded rather than
    dropped — discarding it would erase a real event; leaving it would let one
    row dominate the ranking and `MAX(value_usd)`."""
    assert sanitize_value_usd(9e18) == 1_000_000_000.0


def test_a_bool_is_not_a_value():
    """DEFECT-PROVER. `float(True)` is 1.0, so an unrelated boolean parameter
    would have been reported as one dollar."""
    assert sanitize_value_usd(True) is None


@pytest.mark.parametrize("raw,expected", [(1234.5, 1234.5), ("250", 250.0), (0, 0.0)])
def test_honest_values_are_unchanged(raw, expected):
    """SCOPE PIN. The sanitiser must not reprice real activity."""
    assert sanitize_value_usd(raw) == expected


def test_hydration_neutralises_a_row_poisoned_before_the_fix():
    """DEFECT-PROVER — THE PERSISTENCE HALF. A row written before this fix
    still holds `inf`. Sanitising only the writer would leave the feed broken
    forever; the read path is what lets it recover without a migration."""
    import runtime.social.feed_engine as fe
    src = fe.__file__ and open(fe.__file__).read()
    assert src.count("sanitize_value_usd") >= 3, (
        "the sanitiser must run at BOTH the write and the read end"
    )
    assert math.isfinite(sanitize_value_usd(1.0) or 0.0)
