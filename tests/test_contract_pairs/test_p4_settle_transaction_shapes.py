"""Contract pair P4: the receipt readers -> the verdict that consumes them (engines Phase 1).

Two functions turn a broadcast into an answer: ``web3_manager.settle_transaction``
(the shared form: a service under ``services/`` that waits for the receipt of
its own broadcast waits through it, except restaking) and its older twin in
``services/restaking/_guards.py``, which ``services/restaking/service.py`` waits
through instead at each of its call sites. Each has three
answers — settled (receipt status 1), failed (mined and reverted) and pending
(no receipt inside the wait window) — and today the dispatcher's
``_record_verdict`` and ``report_of`` are what read them. The evidence engine's
parser will be the next reader.

This pair drives both readers against a stub node for all three branches and
pins, against a golden file, the shape each returns (its keys and its flag
values) and what the consumers answer for it:

  * both readers give the same answer on every branch;
  * settled -> recorded settled; reverted -> recorded refused (a receipt
    answered, the outcome is established, nothing moved); pending -> recorded as
    a broadcast, reported unknown;
  * no shape carries a confirmation depth: a status-1 receipt settles at depth
    0, which is adversarial case A3, measured here as it is;
  * a cancelled wait is re-raised by both, never read as an answer;
  * dataset 3's settle cases (tests/test_evidence_shadow_matches_legacy_verdict.py)
    are exactly these shapes, so the shadow test covers what the readers emit.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.blockchain.services import service_dispatcher as sd  # noqa: E402
from runtime.blockchain.services.restaking import _guards  # noqa: E402
from runtime.blockchain import web3_manager  # noqa: E402
from runtime.protocols.outcome_truth import report_of  # noqa: E402
from tests.test_evidence_shadow_matches_legacy_verdict import TX, outcome_shape_corpus  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "p4_settle_transaction_shapes.json"
WRITE = os.environ.get("ENGINES_BASELINE", "").strip().lower() == "write"

READERS = {
    "web3_manager.settle_transaction": lambda w3: web3_manager.settle_transaction(
        w3, TX, "method", "service", {}),
    "restaking._guards.settle_transaction": lambda w3: _guards.settle_transaction(
        w3, TX, "method", "service", {}),
}


class StubNode:
    """``wait_for_receipt`` answers with a receipt, or raises."""

    def __init__(self, receipt=None, raises: BaseException | None = None):
        self._receipt, self._raises = receipt, raises

    async def wait_for_receipt(self, tx_hash, timeout=None):
        if self._raises is not None:
            raise self._raises
        return self._receipt


BRANCHES = {
    "settled": lambda: StubNode(SimpleNamespace(status=1, blockNumber=7, gasUsed=21000,
                                                contractAddress=None)),
    "reverted": lambda: StubNode(SimpleNamespace(status=0, blockNumber=7, gasUsed=21000,
                                                 contractAddress=None)),
    "pending": lambda: StubNode(raises=TimeoutError("no receipt in the window")),
}

FLAGS = ("status", "settled", "value_moved", "broadcast")


async def measure() -> dict:
    out: dict = {}
    for reader, call in READERS.items():
        for branch, node in BRANCHES.items():
            shape = await call(node())
            out.setdefault(reader, {})[branch] = {
                "keys": sorted(shape),
                **{f: shape.get(f) for f in FLAGS},
                "record_verdict": sd._record_verdict(shape),
                "report": report_of(shape),
            }
    return out


@pytest.fixture
async def measured():
    return await measure()


async def test_the_readers_emit_the_golden_shapes(measured):
    if WRITE:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(measured, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    assert measured == json.loads(GOLDEN.read_text(encoding="utf-8"))


async def test_both_readers_answer_alike(measured):
    twin, shared = measured["restaking._guards.settle_transaction"], measured["web3_manager.settle_transaction"]
    for branch in BRANCHES:
        for key in (*FLAGS, "record_verdict", "report"):
            assert twin[branch][key] == shared[branch][key], (branch, key)


async def test_the_consumers_read_the_three_answers(measured):
    for reader, branches in measured.items():
        assert branches["settled"]["record_verdict"] == sd.RECORD_SETTLED, reader
        assert branches["reverted"]["record_verdict"] == sd.RECORD_REFUSED, reader
        assert branches["pending"]["record_verdict"] == sd.RECORD_BROADCAST, reader
        assert branches["pending"]["report"] == "unknown", reader


async def test_no_shape_carries_a_confirmation_depth(measured):
    for reader, branches in measured.items():
        for branch, shape in branches.items():
            assert not {"depth", "confirmations", "finalized"} & set(shape["keys"]), (reader, branch)


@pytest.mark.parametrize("reader", sorted(READERS))
async def test_a_cancelled_wait_is_not_an_answer(reader):
    with pytest.raises(asyncio.CancelledError):
        await READERS[reader](StubNode(raises=asyncio.CancelledError()))


async def test_dataset_3_holds_these_shapes():
    corpus = dict(outcome_shape_corpus())
    for branch, case in (("settled", "settle:settled"), ("reverted", "settle:reverted"),
                         ("pending", "settle:pending")):
        emitted = await READERS["web3_manager.settle_transaction"](BRANCHES[branch]())
        assert emitted == corpus[case], branch
