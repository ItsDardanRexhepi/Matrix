"""Contract pair P3: ServiceDispatcher result -> outcome_truth.report_of (engines Phase 1).

The dispatcher's envelope states a verdict about the call in ``call_outcome``,
computed by ``report_of`` from the service's result and one fact only the
dispatcher holds — whether the action changes state. Downstream readers (the
ReAct loop, outcome learning, the routes that relay a dispatcher result) read
that field back with ``report_of`` again. The durable records are decided beside it by
``_record_verdict``. The two sides share three status vocabularies, kept in
the dispatcher and read lazily by outcome_truth.

This pair drives the producer — a real ``ServiceDispatcher.execute`` over a
stub service — for every case of dataset 3, parses the envelope with the
consumer, and pins, against a golden file:

  * what the envelope states for a state-modifying action and for a read;
  * that the consumer reads back exactly what the producer stated;
  * what ``report_of`` answers for the bare result either way, and what
    ``_record_verdict`` records;

and holds the vocabularies disjoint (a word cannot be both a real outcome and a
non-outcome) and the answers total (every case lands on a known answer).

Silence — ``{}``, ``None``, a result with no status — reads as success today:
the measured default this codebase's services rely on. The evidence engine is
to read it as unstated for its own verdicts while learning keeps the default
(open decision OD-8), so it is pinned here as it is, not marked as a defect.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.blockchain.services import service_dispatcher as sd  # noqa: E402
from runtime.protocols.outcome_truth import (  # noqa: E402
    FAILURE, OUTCOME_FIELD, SUCCESS, UNKNOWN, report_of,
)
from tests.test_evidence_shadow_matches_legacy_verdict import (  # noqa: E402
    ACTOR, PARAMS, READ_ACTION, STATE_ACTION, _dispatcher, outcome_shape_corpus,
)

GOLDEN = Path(__file__).parent / "golden" / "p3_dispatcher_outcome_truth.json"
WRITE = os.environ.get("ENGINES_BASELINE", "").strip().lower() == "write"
REPORTS = {SUCCESS, FAILURE, UNKNOWN}
VERDICTS = {sd.RECORD_SETTLED, sd.RECORD_BROADCAST, sd.RECORD_REFUSED}


async def measure() -> dict:
    out = {}
    for label, result in outcome_shape_corpus():
        state = json.loads(await _dispatcher(result, []).execute(
            STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR))
        read = json.loads(await _dispatcher(result, [], action=READ_ACTION).execute(
            READ_ACTION, params={"address": ACTOR}))
        out[label] = {
            "envelope_state": state[OUTCOME_FIELD],
            "envelope_read": read[OUTCOME_FIELD],
            "consumer_state": report_of(state),
            "consumer_read": report_of(read),
            "bare_state": report_of(result, status_describes_the_call=True),
            "bare_read": report_of(result, status_describes_the_call=False),
            "record_verdict": sd._record_verdict(result),
        }
    return out


@pytest.fixture
async def measured():
    previous = sd.set_evidence_shadow_sink(None)
    try:
        return await measure()
    finally:
        sd.set_evidence_shadow_sink(previous)


async def test_the_pair_answers_the_golden_verdicts(measured):
    if WRITE:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(measured, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    assert measured == json.loads(GOLDEN.read_text(encoding="utf-8"))


async def test_the_consumer_reads_back_what_the_producer_stated(measured):
    for label, row in measured.items():
        assert row["consumer_state"] == row["envelope_state"], label
        assert row["consumer_read"] == row["envelope_read"], label
        assert row["envelope_state"] == row["bare_state"], label
        assert row["envelope_read"] == row["bare_read"], label


async def test_every_case_lands_on_a_known_answer(measured):
    for label, row in measured.items():
        assert {row[k] for k in row if k != "record_verdict"} <= REPORTS, label
        assert row["record_verdict"] in VERDICTS, label


def test_the_vocabularies_are_disjoint_and_broadcast_is_a_real_word():
    assert not (sd._REAL_OUTCOME_STATUSES & sd._NON_OUTCOME_STATUSES)
    assert sd._BROADCAST_STATUSES <= sd._REAL_OUTCOME_STATUSES
    assert (len(sd._REAL_OUTCOME_STATUSES), len(sd._NON_OUTCOME_STATUSES),
            len(sd._BROADCAST_STATUSES)) == (102, 62, 3)


async def test_silence_reads_as_success_today(measured):
    """Pinned as it is (OD-8 is open): the evidence engine will read these as
    unstated for its own verdicts; the learning default is not changed here."""
    for label in ("empty", "none", "no-status"):
        assert measured[label]["envelope_state"] == SUCCESS, label
        assert measured[label]["record_verdict"] in {sd.RECORD_SETTLED, sd.RECORD_REFUSED}, label
