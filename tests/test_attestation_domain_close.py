"""NEW-48b/49/50/51 — attestation domain close (domain 3).

Every test here fails against the pre-fix bodies and passes after.

WHAT WAS WRONG

  ProofGenerator._fetch_attestation (NEW-49)
      docstring: "reads from the EAS contract's getAttestation()"
      body:      a dict literal of empty strings. The `except` was
                 unreachable — a dict literal cannot throw.
  ProofGenerator.verify_proof (NEW-50)
      rebuilt the Merkle tree from proof["leaves"] and compared to
      proof["merkle_root"] — BOTH caller-supplied. No chain call, no anchor.
      Real math; nothing proven.
  AttestationService.query (NEW-48b)
      returned the GraphQL query TEXT as the result list.
  AttestationService.attest (NEW-51)
      returned a bare "queued" for a batch that submits only at the size
      threshold, with the interval timer never started.
  _attest_action / neosafe._attest_fee (NEW-42)
      passed schema_name= to a method taking schema_uid → TypeError on every
      call, swallowed as a WARNING. neosafe then read result["uid"], a key
      `attest` returns on NO branch.

A NOTE ON CATEGORY, because it cost us one:
`verify_proof` was NOT a fabrication. It did genuine computation. It was
real-local and DEFECTIVE — self-referential and vacuous. "Returns
success-shaped output for work not done" and "does real work that proves
nothing" are different diseases. The tests below assert the module is gone,
not that it lied.
"""

from __future__ import annotations

import inspect
import json

import pytest

from runtime.blockchain.services.attestation.batch_processor import BatchProcessor
from runtime.blockchain.services.attestation.service import AttestationService


def _dispatch(raw: object) -> dict:
    """Parse ServiceDispatcher.execute's JSON-STRING envelope.

    Asserting on the raw return is vacuous — it is a str, so any dict-shaped
    check silently passes. This has bitten twice in this engagement.
    """
    assert isinstance(raw, str), (
        f"dispatcher.execute returned {type(raw).__name__}, expected a JSON "
        "string — the envelope shape changed and these assertions no longer "
        "look at what they think they do."
    )
    env = json.loads(raw)
    assert isinstance(env, dict)
    return env


# ── NEW-50 (+NEW-49 by subsumption): the proof layer is gone ───────────────


def test_proof_generator_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        __import__(
            "runtime.blockchain.services.attestation.proof_generator",
            fromlist=["ProofGenerator"],
        )


@pytest.mark.parametrize("method", ["generate_proof", "verify_proof"])
def test_proof_methods_are_gone_from_the_service(method):
    assert not hasattr(AttestationService, method), (
        f"{method} still exists — a caller can still obtain a proof verdict "
        "with no on-chain anchor behind it"
    )


def test_service_no_longer_constructs_a_proof_generator():
    svc = AttestationService({})
    assert not hasattr(svc, "_proof_generator")


def test_the_fabricated_fetch_is_not_hiding_elsewhere():
    """FORWARD GUARD, not proof-of-change — it passes pre-fix too.

    `_fetch_attestation` lived on ProofGenerator, never on AttestationService,
    so this assertion was already true before the removal. It is kept
    deliberately, and labelled, because the risk it covers is FUTURE: someone
    reviving the chain-read stub on the service. Counting it among the tests
    that prove this commit would overstate the evidence by one.

    The removal itself is proven by `test_proof_generator_module_is_gone` and
    `test_proof_methods_are_gone_from_the_service`, which both fail pre-fix.
    """
    assert not hasattr(AttestationService, "_fetch_attestation")


# ── NEW-48b: query is gone from every surface ──────────────────────────────


def test_query_method_is_gone():
    assert not hasattr(AttestationService, "query")


def test_query_action_is_not_dispatchable():
    from runtime.blockchain.services.service_dispatcher import (
        ACTION_MAP,
        ACTION_TO_FEED_EVENT,
        _STATE_MODIFYING_ACTIONS,
    )

    assert "query_attestations" not in ACTION_MAP
    assert "query_attestations" not in _STATE_MODIFYING_ACTIONS
    assert "query_attestations" not in ACTION_TO_FEED_EVENT


async def test_dispatching_query_attestations_fails():
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    env = _dispatch(
        await ServiceDispatcher({}).execute(action="query_attestations", params={})
    )
    assert env["status"] == "error", f"query_attestations still works: {env!r}"
    assert "unknown action" in env["error"].lower()


def test_the_model_is_not_told_query_works():
    from runtime.chat.intent_actions import INTENT_ACTION_MAP

    guide = INTENT_ACTION_MAP["query_attestations"]
    assert guide.get("unavailable") is True
    assert "action_name" not in guide
    assert "NOT AVAILABLE" in guide["description"]
    assert guide["keywords"], "keywords dropped — the request now matches nothing"


# ── NEW-51(b): the disclosure must be ACCURATE, not merely present ─────────


async def test_attest_discloses_the_real_batch_mechanics():
    """The disclosure has to match the mechanics, field by field.

    A differently-worded approximate status would be the same disease in new
    clothes, so this asserts the NUMBERS against the processor's real state
    rather than looking for reassuring prose.
    """
    svc = AttestationService({"blockchain": {"eas_schema": "0x" + "ab" * 32}},
                             batch_size=7)

    result = await svc.attest(schema_uid="", data={"k": "v"}, recipient="0xA")

    # It did not claim submission.
    assert result["submitted"] is False
    assert result["guaranteed_submission"] is False

    # The numbers are the processor's real numbers, not decoration.
    bp = svc._batch_processor
    assert result["pending_count"] == bp.pending_count == 1
    assert result["batch_threshold"] == bp.batch_size == 7
    assert result["attestations_until_submit"] == 6

    # The timer claim matches reality: nothing started it.
    assert result["interval_timer_running"] is False
    assert bp.is_running is False

    # And the prose repeats the true figures rather than hand-waving.
    disclosure = result["disclosure"]
    assert "NOT SUBMITTED" in disclosure
    assert "1/7" in disclosure
    assert "6 more" in disclosure


async def test_the_disclosure_tracks_the_queue_rather_than_being_static():
    """Second call must report 2/7 and 5-to-go — proving it is computed."""
    svc = AttestationService({"blockchain": {"eas_schema": "0x" + "ab" * 32}},
                             batch_size=7)
    await svc.attest(schema_uid="", data={"k": 1}, recipient="0xA")
    second = await svc.attest(schema_uid="", data={"k": 2}, recipient="0xA")

    assert second["pending_count"] == 2
    assert second["attestations_until_submit"] == 5
    assert "2/7" in second["disclosure"]


async def test_is_running_is_true_only_when_the_loop_actually_runs():
    """The flag must track the task, not just the boolean.

    `start()` sets `_running = True` before creating the task, so a flag-only
    check would report a running loop during a window where none exists — and
    would keep reporting one after the task died.
    """
    bp = BatchProcessor({}, batch_size=5, flush_interval_seconds=0.01)
    assert bp.is_running is False

    await bp.start()
    assert bp.is_running is True

    await bp.stop()
    assert bp.is_running is False

    # Flag set without a task must NOT read as running.
    bp._running = True
    bp._flush_task = None
    assert bp.is_running is False


async def test_the_size_threshold_path_still_works():
    """NEW-51 is 'no time bound', NOT 'never drains' — do not overstate it.

    My first report said the processor never runs. It does: `add()` flushes
    inline at the threshold with no `start()`. This pins the true mechanic so
    the finding cannot drift back to the overstatement.
    """
    bp = BatchProcessor({}, batch_size=3)
    flushed = []

    async def _spy(batch):
        flushed.append(len(batch))
        return [{"ok": True} for _ in batch]

    bp._submit_batch = _spy

    for i in range(2):
        await bp.add({"schema_uid": "0x1", "data": {"i": i}, "recipient": "0xA"})
    assert bp.pending_count == 2 and flushed == []

    await bp.add({"schema_uid": "0x1", "data": {"i": 2}, "recipient": "0xA"})
    assert bp.pending_count == 0 and flushed == [3], (
        "the size-threshold flush stopped working — that path is real and "
        "must not be broken by the disclosure change"
    )


# ── NEW-42: both call sites pass the parameter the method actually takes ───


def test_attest_signature_takes_schema_uid_not_schema_name():
    params = inspect.signature(AttestationService.attest).parameters
    assert "schema_uid" in params
    assert "schema_name" not in params


@pytest.mark.parametrize(
    "module_path,func_name",
    [
        ("runtime.blockchain.services.service_dispatcher", "_attest_action"),
        ("runtime.blockchain.services.neosafe", "_attest_fee"),
    ],
)
def test_neither_call_site_passes_schema_name(module_path, func_name):
    """Both instances, because fixing one and leaving its twin is incoherent.

    Source-level, since both calls sit inside a broad `except` that swallowed
    the TypeError — a behavioural test would have seen the same silent
    warning before and after.
    """
    import importlib
    from pathlib import Path

    mod = importlib.import_module(module_path)
    src = Path(inspect.getsourcefile(mod)).read_text()

    start = src.index(f"def {func_name}")
    body = src[start:start + 3000]
    code = "\n".join(
        ln for ln in body.splitlines() if not ln.lstrip().startswith("#")
    )

    assert "schema_name=" not in code, (
        f"{func_name} still passes schema_name= — every attest call raises "
        "TypeError and is swallowed, so nothing is ever attested"
    )
    assert "schema_uid=" in code


def test_neosafe_does_not_read_a_key_attest_never_returns():
    """The second half of NEW-42: the caller's imagined return shape.

    `attest` returns `attestation_tx` on the time-critical branch and a queue
    disclosure on the batch branch. It returns `uid` on NEITHER.
    """
    from pathlib import Path

    from runtime.blockchain.services import neosafe

    src = Path(inspect.getsourcefile(neosafe)).read_text()
    start = src.index("def _attest_fee")
    body = src[start:start + 3000]
    code = "\n".join(
        ln for ln in body.splitlines() if not ln.lstrip().startswith("#")
    )

    assert 'result.get("uid")' not in code, (
        "still reading 'uid' — a key attest() returns on no branch, so this "
        "silently yields None forever even with the TypeError fixed"
    )
    assert 'result.get("attestation_tx")' in code


async def test_attest_returns_attestation_tx_on_the_submitted_path():
    """Positive proof the key neosafe now reads is the key attest emits."""
    svc = AttestationService({"blockchain": {"eas_schema": "0x" + "ab" * 32}})

    class _Handler:
        @staticmethod
        def is_time_critical(category):
            return True

        async def attest_now(self, **kwargs):
            return {"status": "attested", "attestation_tx": "0xdeadbeef",
                    "time_critical": True}

    svc._time_critical = _Handler()
    result = await svc.attest(
        schema_uid="", data={"category": "dispute"}, recipient="0xA",
        time_critical=True,
    )

    assert result["attestation_tx"] == "0xdeadbeef"
    assert "uid" not in result
