"""A node accepting the bytes is not the chain agreeing they were valid.

CLUSTER attest-money, the axis the cluster's own fixes established and then did
not finish applying.

`neosafe.route_revenue` returned `"routed"` the moment `send_transaction`
returned, and `routed` reads as a real outcome, so the dispatcher EAS-attested
it and the public feed announced platform revenue that may have reverted. The
fix there was to wait for the receipt and attest from THAT. `web3_manager`
carries the shared form of it, `settle_transaction`, and says in its own header
what the two helpers beside it are for:

    Both emit the disclosure flags `settled` / `value_moved`, which are the
    highest-priority clause in `_outcome_is_real` and in `report_of`. A service
    that omits them gets graded on its status string alone.

TWENTY-SIX METHODS OMIT THEM. They build a transaction, broadcast it, and return
`{"status": "submitted", "tx_hash": ...}` with no `settled` key and no receipt
wait — nine services, every one of them reachable as a state-modifying action:
the five CCIP bridges, both payment channels, both token-bound accounts, the
three auction/orderbook writes, four advanced-governance writes, three NFT
lending writes, MPC recovery and session keys, the Lens profile, the keeper job,
the compute job.

`"submitted"` is in `_REAL_OUTCOME_STATUSES`, so `_outcome_is_real` answered
True for every one of them and the platform wrote an EAS attestation — a durable
claim addressed to third parties, whose entire value is that someone who does
not trust this platform can check it — asserting that a bridge, a channel close
or a liquidation HAPPENED, on the evidence that a node had accepted the bytes.
The same predicate governs the public feed, so the feed announced it too.

THE GATE HAD TWO ANSWERS AND THE TRUTH HAS THREE. Moving `"submitted"` out of
the real-outcome vocabulary would route these to `_attest_refusal`, which writes
"ACTION DECLINED" — a broadcast is not a decline, and that is the same defect
facing the other way. So the gate gains its third answer: settled, broadcast,
refused. A broadcast is recorded as a broadcast, carrying the hash that makes it
checkable, and is neither attested as done nor announced as done.

NOT A NEW VOCABULARY. `settle_transaction` already emits `settled: True` on a
confirmed receipt — including when its settled status is the word "submitted" —
and that flag still outranks everything, so no service that waits for its
receipt loses its attestation.

WHAT THIS DOES NOT TOUCH: `report_of`. Outcome learning asks whether the CALL
succeeded, and for a broadcast it did — the bytes went out. That question and
"may this be attested as done" are different, which is the distinction
`outcome_truth` was written to keep.
"""

from __future__ import annotations

import ast
import asyncio
import json
import pathlib

import pytest

from runtime.blockchain.services.service_dispatcher import (
    ACTION_MAP,
    RECORD_BROADCAST,
    RECORD_REFUSED,
    RECORD_SETTLED,
    _BROADCAST_STATUSES,
    _REAL_OUTCOME_STATUSES,
    _STATE_MODIFYING_ACTIONS,
    ServiceDispatcher,
    _record_verdict,
)

_SERVICES = pathlib.Path(__file__).resolve().parents[1] / "runtime" / "blockchain" / "services"


class _SpyFeed:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def ingest(self, **kwargs):  # noqa: D401 - test double
        self.published.append(kwargs)


@pytest.fixture
def dispatcher_with_spies():
    d = ServiceDispatcher({})
    feed = _SpyFeed()
    d._feed_engine = feed
    attested: list[str] = []
    declined: list[str] = []
    broadcast: list[str] = []

    async def _spy_attest(action, service_name, params, result, *, actor: str = "",
                          actor_source: str = ""):
        attested.append(action)

    async def _spy_refusal(action, service_name, params, result, *, actor: str = "",
                           actor_source: str = ""):
        declined.append(action)

    async def _spy_broadcast(action, service_name, params, result, *, actor: str = "",
                             actor_source: str = ""):
        broadcast.append(action)

    d._attest_action = _spy_attest
    d._attest_refusal = _spy_refusal
    # Only bound once the third answer exists; harmless before then.
    d._record_broadcast = _spy_broadcast
    return d, feed, attested, declined, broadcast


# ── the census ───────────────────────────────────────────────────────────


def _bare_broadcast_methods() -> set[tuple[str, str]]:
    """Every method returning a broadcast status with no `settled` key.

    Re-derived from the tree rather than listed, so a method added later on the
    same pattern is caught here instead of shipping an attestation for an
    unconfirmed transaction.
    """
    words = {"submitted", "claim_submitted", "verification_submitted"}
    found: set[tuple[str, str]] = set()
    for path in _SERVICES.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(node):
                if not (isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict)):
                    continue
                keys = {k.value for k in sub.value.keys if isinstance(k, ast.Constant)}
                vals = {v.value for v in sub.value.values if isinstance(v, ast.Constant)}
                if "status" in keys and "settled" not in keys and (vals & words):
                    found.add((str(path.relative_to(_SERVICES)), node.name))
    return found


def test_the_bare_broadcast_surface_is_what_it_was_measured_to_be():
    """PREMISE. If this shrinks to nothing the defect is gone by another route;
    if it grows, a new method joined the pattern and the gate must still cover
    it. Either way the number is not allowed to drift unnoticed."""
    found = _bare_broadcast_methods()
    assert len(found) >= 20, (
        "the bare-broadcast surface this fix was measured against has "
        f"disappeared ({len(found)} found) — re-derive before trusting the gate"
    )


def test_those_methods_are_reachable_as_attested_actions():
    """REACHABILITY. A defect behind an unreachable path is a different finding.
    These are state-modifying actions, which is the ENTIRE condition under which
    the dispatcher attests and publishes."""
    method_names = {m for _, m in _bare_broadcast_methods()}
    reachable = {
        action for action, spec in ACTION_MAP.items()
        if isinstance(spec, (tuple, list)) and len(spec) > 1
        and spec[1] in method_names and action in _STATE_MODIFYING_ACTIONS
    }
    assert len(reachable) >= 20, (
        f"expected the broadcast methods to be reachable as attested actions, "
        f"found {sorted(reachable)}"
    )


# ── the predicate ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "label,result",
    [
        ("the shape 26 methods return", {"status": "submitted", "tx_hash": "0xabc"}),
        ("compute's reward claim", {"status": "claim_submitted", "tx_hash": "0xabc"}),
        ("explorer verification", {"status": "verification_submitted"}),
        ("case-insensitive", {"status": "SUBMITTED"}),
    ],
)
def test_a_bare_broadcast_is_its_own_answer(label, result):
    """Not settled, and NOT a refusal. Both of the other two answers are false
    about a transaction that was sent and may yet be mined."""
    assert _record_verdict(result) == RECORD_BROADCAST, label


@pytest.mark.parametrize(
    "label,result",
    [
        # THE ORDERING ARGUMENT, ASSERTED. `settle_transaction`'s settled status
        # DEFAULTS to the word "submitted", so a gate reading the word before
        # the flag would strip the attestation from every service that waits for
        # its receipt — neosafe, restaking, creator_platforms.
        ("settle_transaction's confirmed shape",
         {"status": "submitted", "settled": True, "value_moved": True,
          "block_number": 1, "tx_hash": "0xabc"}),
        ("a plain success with no chain in sight", {"pool_id": "p", "shares_minted": 1.0}),
        ("completed", {"status": "completed"}),
        ("a record-creating action", {"status": "pending", "created": True}),
    ],
)
def test_a_settlement_is_still_a_settlement(label, result):
    """SCOPE PIN. The great majority of attested actions never touch a chain and
    never emit `settled`; diverting them would be the mirror-image defect."""
    assert _record_verdict(result) == RECORD_SETTLED, label


@pytest.mark.parametrize(
    "label,result",
    [
        ("not_deployed", {"status": "not_deployed"}),
        ("error", {"status": "error"}),
        ("this audit's unsettled idiom", {"status": "recorded_unsettled"}),
        ("flags outrank the word", {"status": "submitted", "settled": False}),
        ("value_moved False", {"status": "submitted", "value_moved": False}),
        ("None", None),
        ("not a dict", "ok"),
    ],
)
def test_a_refusal_is_not_laundered_into_a_broadcast(label, result):
    """THE THIRD ANSWER MUST NOT BECOME A PLACE REFUSALS HIDE.

    Note the last two: a service that says `settled: False` while its status
    word says "submitted" is refusing, and 15-A's flags outrank the word in
    BOTH directions — that is the clause `_outcome_is_real` already runs first,
    and routing through it is why this holds without restating it.
    """
    assert _record_verdict(result) == RECORD_REFUSED, label


def test_the_broadcast_vocabulary_is_drawn_from_the_real_outcome_set():
    """PREMISE OF THE WHOLE FIX. These words were classified as REAL outcomes —
    that is precisely why they were attested. If one were ever moved to the
    non-outcome set instead, it would become a refusal, which is the mislabel
    this fix exists to avoid, and this fails."""
    assert _BROADCAST_STATUSES <= _REAL_OUTCOME_STATUSES, (
        "a broadcast word left the real-outcome vocabulary — it is now recorded "
        "as a REFUSAL, which is false about a transaction that was sent"
    )


# ── end to end ───────────────────────────────────────────────────────────


async def test_a_bare_broadcast_is_not_attested_as_a_completed_action(
    dispatcher_with_spies, monkeypatch,
):
    """THE LOAD-BEARING ASSERTION.

    Pre-fix this wrote an EAS attestation saying `create_tba` happened, on the
    evidence that a node had accepted the bytes. The transaction may revert.
    """
    d, feed, attested, declined, broadcast = dispatcher_with_spies

    from runtime.blockchain.services.tba.service import TokenBoundAccountService

    async def _broadcast_only(self, **params):
        return {
            "status": "submitted",
            "service": "tba",
            "method": "create_tba",
            "tx_hash": "0xdeadbeef",
        }

    monkeypatch.setattr(TokenBoundAccountService, "create_tba", _broadcast_only)

    await d.execute("create_tba", params={
        "token_contract": "0x" + "1" * 40, "token_id": 1,
    })
    await asyncio.sleep(0)

    assert attested == [], (
        "an unconfirmed broadcast was EAS-attested as a completed action"
    )
    assert feed.published == [], (
        "an unconfirmed broadcast was announced on the public feed as done"
    )


async def test_the_broadcast_is_still_recorded_as_a_broadcast(
    dispatcher_with_spies, monkeypatch,
):
    """THE THIRD ANSWER, NOT SILENCE AND NOT A DECLINE.

    Suppressing the record would trade a false record for no record. Calling it
    a refusal would be a falsehood in the other direction: the bytes went out
    and the hash is real.
    """
    d, feed, attested, declined, broadcast = dispatcher_with_spies

    from runtime.blockchain.services.tba.service import TokenBoundAccountService

    async def _broadcast_only(self, **params):
        return {"status": "submitted", "tx_hash": "0xdeadbeef"}

    monkeypatch.setattr(TokenBoundAccountService, "create_tba", _broadcast_only)

    await d.execute("create_tba", params={
        "token_contract": "0x" + "1" * 40, "token_id": 1,
    })

    assert broadcast == ["create_tba"], "the broadcast left no record at all"
    assert declined == [], "a broadcast was recorded as a refusal"


async def test_a_confirmed_settlement_is_still_attested(
    dispatcher_with_spies, monkeypatch,
):
    """SCOPE PIN, and the reason the fix reads the flag rather than the word.

    `settle_transaction` returns its settled status — which DEFAULTS to the
    word "submitted" — alongside `settled: True` once the receipt is in. A gate
    keyed on the word alone would stop attesting exactly the services that do
    wait for their receipt, which is the whole remediation facing backwards.
    """
    d, feed, attested, declined, broadcast = dispatcher_with_spies

    from runtime.blockchain.services.tba.service import TokenBoundAccountService

    async def _settled(self, **params):
        return {
            "status": "submitted",
            "tx_hash": "0xdeadbeef",
            "settled": True,
            "value_moved": True,
            "block_number": 12345,
        }

    monkeypatch.setattr(TokenBoundAccountService, "create_tba", _settled)

    await d.execute("create_tba", params={
        "token_contract": "0x" + "1" * 40, "token_id": 1,
    })
    await asyncio.sleep(0)

    assert attested == ["create_tba"], (
        "a settlement confirmed by a receipt lost its attestation"
    )
    assert [p["action"] for p in feed.published] == ["create_tba"]
    assert broadcast == []


async def test_a_refusal_is_still_a_refusal(dispatcher_with_spies, monkeypatch):
    """SCOPE PIN. The third answer must not become a place refusals hide."""
    d, feed, attested, declined, broadcast = dispatcher_with_spies

    from runtime.blockchain.services.tba.service import TokenBoundAccountService

    async def _refused(self, **params):
        return {"status": "not_deployed", "service": "tba"}

    monkeypatch.setattr(TokenBoundAccountService, "create_tba", _refused)

    await d.execute("create_tba", params={
        "token_contract": "0x" + "1" * 40, "token_id": 1,
    })

    assert declined == ["create_tba"]
    assert attested == []
    assert broadcast == []
    assert feed.published == []
