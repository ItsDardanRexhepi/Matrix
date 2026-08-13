"""The record of what happened must check whether it happened.

DOMAIN 16-K. The largest single finding of the census, and the one whose payload
is the audit's own remediation idiom.

`ServiceDispatcher.execute` attested and published on ONE condition:

    if action in _STATE_MODIFYING_ACTIONS:
        await self._attest_action(...)
        ... self._feed_engine.ingest(action=action, ...)

Membership in the set was the entire test. `result` was read only to pull
`tx_hash` into the feed payload — never to decide WHETHER to record. So every
refusal was attested and announced as an action taken.

MEASURED: 182 attested actions, of which 62 return an honest refusal
(`not_deployed`, `recorded_unsettled`, `status: "error"`). **Every domain where
this audit replaced a fabricated success with an honest RETURNED refusal produced
a new false attestation** — the remediation and the defect compounded.

WHY IT WAS KEYED ON THE WRONG THING. A RAISED refusal never reached the block:
the exception unwinds past it. A RETURNED one always did. So the clean subset was
clean only because raise-vs-return got picked on local ergonomics, sixteen domains
deep, and never once on attestation behaviour. Verified by enumeration that no
disposition converted a raise into a return — the split is inherited, not
authored. **A style-keyed rule can therefore be got wrong by accident by a future
fix. `_outcome_is_real` cannot: it reads the result.**

BOTH SURFACES, ONE PREDICATE. Domain 8 established the feed is keyed on ACTION
NAME rather than result, so gating the attestation alone would leave the feed
announcing refusals — the half-fix this engagement keeps catching (15-A's log
line, 16-I's third entry point). The same predicate governs both.

THE REFUSAL IS STILL RECORDED, AS A REFUSAL. Suppression would trade a false
record for no record, which is the same defect facing the other way: an auditor
must be able to tell "the system declined" from "nothing was asked".

REACHABILITY — armed by deployment, and the arming step is on the runbook. Under
the shipped config `attest()` raises "EAS schema is not configured" and
`_feed_engine` is None, so neither sink fires. **The distance from no false
attestations to 62 is one config key — `blockchain.eas_schema` — which the
deployment runbook instructs the operator to set, for auditability.** This fix is
a DEPLOYMENT PREREQUISITE for that step.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.service_dispatcher import (
    _STATE_MODIFYING_ACTIONS,
    ServiceDispatcher,
    _outcome_is_real,
)


class _SpyFeed:
    """The feed spy. `ingest` is ASYNC because the dispatcher awaits it.

    It was sync until 16-O, and passed — because every test in 16-K drove a
    REFUSAL, so the publish call was never reached and never awaited. The first
    test to drive a genuine action through this fixture failed with "a coroutine
    was expected, got None". A test double only has to be right on the paths the
    tests take, which is its own quiet way of pinning the wrong thing.
    """

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

    async def _spy_attest(action, service, params, result):
        attested.append(action)

    async def _spy_refusal(action, service, params, result):
        declined.append(action)

    d._attest_action = _spy_attest
    d._attest_refusal = _spy_refusal
    return d, feed, attested, declined


# ── the predicate ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "label,result",
    [
        ("not_deployed", {"status": "not_deployed"}),
        ("error", {"status": "error"}),
        ("blocked", {"status": "blocked"}),
        ("15-A recorded_unsettled", {"status": "recorded_unsettled"}),
        ("16-E liquidation_due", {"status": "liquidation_due_unsettled"}),
        ("pending", {"status": "pending"}),
        ("STATUS SAYS DONE, FLAGS SAY NO", {"status": "completed", "settled": False}),
        ("value_moved False", {"status": "success", "value_moved": False}),
        ("None", None),
        ("not a dict", "ok"),
    ],
)
def test_a_non_outcome_is_not_treated_as_real(label, result):
    """AN EXPLICIT REFUSAL IS NEVER TREATED AS REAL.

    Note what is NOT in this list any more: a dict with no `status` key. A first
    version of the predicate put it here, reasoning "cannot tell -> do not
    attest". Measuring showed that 17 of the 182 attested actions return a
    SUCCESS with no status field, so that reading would have silently stopped
    attesting a sixth of the surface. Refusals in this codebase announce
    themselves; successes often do not.
    """
    assert _outcome_is_real(result) is False, label


@pytest.mark.parametrize(
    "label,result",
    [
        ("success + tx", {"status": "success", "tx_hash": "0xabc"}),
        ("completed", {"status": "completed"}),
        ("settled True", {"status": "completed", "settled": True}),
        ("case-insensitive", {"status": "SUCCESS"}),
        # THE 17 SHAPES A FIRST VERSION OF THE PREDICATE WOULD HAVE DROPPED.
        # Measured: 17 of the 182 attested actions return a success with NO
        # status key. Treating that as "cannot tell -> do not attest" would have
        # invented an evidence gap across a sixth of the surface.
        ("dex.add_liquidity shape", {"pool_id": "p1", "shares_minted": 10.0}),
        ("loyalty.earn_points shape", {"points_earned": 50, "balance": 120}),
        ("dao.join_dao shape", {"dao_id": "d1", "member": "0xA", "member_count": 3}),
    ],
)
def test_a_real_outcome_is_still_attestable(label, result):
    """SCOPE PIN. Failing closed must not swallow genuine actions — an
    attestation layer that never attests is the mirror-image defect."""
    assert _outcome_is_real(result) is True, label


def test_a_success_without_a_status_key_is_still_attested():
    """THE REGRESSION A FIRST VERSION OF THIS FIX INTRODUCED, pinned.

    Refusals in this codebase ANNOUNCE THEMSELVES — not_deployed, error,
    recorded_unsettled are all explicit. Successes often do not: 17 of the 182
    attested actions return a plain result dict with no status field. So absence
    of a status is evidence of SUCCESS, and treating it as "cannot tell" would
    silently stop attesting a sixth of the surface.

    "Fail closed" is only safe once you have correctly identified which
    direction closed is.
    """
    assert _outcome_is_real({"pool_id": "p1", "shares_minted": 10.0}) is True
    assert _outcome_is_real({"points_earned": 50}) is True
    # ...but an explicit refusal still wins, status key or not
    assert _outcome_is_real({"pool_id": "p1", "settled": False}) is False


def test_the_disclosure_flags_outrank_an_optimistic_status():
    """15-A's idiom, asserted directly. A record saying settled=False is telling
    you plainly that nothing moved, whatever some other field claims."""
    assert _outcome_is_real({"status": "completed", "settled": False}) is False
    assert _outcome_is_real({"status": "ok", "value_moved": False}) is False


# ── end to end ───────────────────────────────────────────────────────────


async def test_a_refusal_is_neither_attested_nor_published(dispatcher_with_spies):
    """THE LOAD-BEARING ASSERTION. Pre-fix this attested `create_loan` and
    published it to the public feed while the service returned `not_deployed`."""
    d, feed, attested, declined = dispatcher_with_spies

    await d.execute(
        "create_loan",
        params={
            "borrower": "0xA", "collateral_token": "ETH", "collateral_amount": 10.0,
            "borrow_token": "USDC", "borrow_amount": 1000.0,
        },
    )

    assert attested == [], "a refusal was attested as an action taken"
    assert feed.published == [], "a refusal was announced on the public feed"


async def test_the_refusal_is_still_recorded_as_a_refusal(dispatcher_with_spies):
    """SUPPRESSION WOULD BE A DIFFERENT DEFECT. An auditor must be able to tell
    'the system declined' from 'nothing was ever asked'. Both are answers; only
    one of them is silence."""
    d, feed, attested, declined = dispatcher_with_spies

    await d.execute(
        "create_loan",
        params={
            "borrower": "0xA", "collateral_token": "ETH", "collateral_amount": 10.0,
            "borrow_token": "USDC", "borrow_amount": 1000.0,
        },
    )

    assert declined == ["create_loan"], "the refusal left no record at all"


async def test_both_surfaces_are_governed_by_the_same_predicate():
    """DOMAIN 8's LESSON, PINNED. The feed is keyed on action name rather than
    result, so a fix that gates the attestation and not the feed leaves the feed
    announcing refusals. If these two ever diverge, this fails.

    Asserted structurally rather than behaviourally: both call sites must be
    governed by the one `_happened` value, so no future edit can gate one without
    the other.
    """
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(ServiceDispatcher.execute))
    tree = ast.parse(src)

    guards = [
        ast.unparse(n.test)
        for n in ast.walk(tree)
        if isinstance(n, ast.If) and "_happened" in ast.unparse(n.test)
    ]
    assert len(guards) >= 2, (
        f"expected the attest branch AND the feed branch to be governed by "
        f"_happened; found {len(guards)}: {guards}"
    )
    assert any("_feed_engine" in g for g in guards), (
        "the feed publish is not gated on the outcome — domain 8's half-fix"
    )


def test_the_blast_radius_is_still_what_the_finding_measured():
    """THE MEASUREMENT, PINNED. 16-K's severity rests on how many actions reach
    this block. If the set grows, the finding's scope grew with it and the
    closeout figure is stale."""
    assert len(_STATE_MODIFYING_ACTIONS) == 182, (
        f"_STATE_MODIFYING_ACTIONS is now {len(_STATE_MODIFYING_ACTIONS)}, not the "
        "182 recorded in closeout §Z/Z.1 — re-derive the 62 refusal-returning "
        "subset before quoting either number"
    )


# ══════════════════════════════════════════════════════════════════════════
# 16-N / 16-O — the adversarial pass on 16-K, and what it found
#
# 16-K's own commit shipped the defect 16-K exists to eliminate. The predicate
# ended `status not in _NON_OUTCOME_STATUSES`: a CLOSED DENY-LIST of 18 strings
# consulted about an OPEN vocabulary. Anything unanticipated read as a real
# outcome, so on the status axis it failed OPEN — the inversion of its own
# docstring, in the commit written to stop refusals being recorded as actions.
#
# 16-N (fails open): 115 distinct status strings are emitted by the packages
#   reachable from `_STATE_MODIFYING_ACTIONS`. Eighteen were classified. Among
#   the 97 that fell through: `compliance_hold` — a $5,000 cross-border payment
#   REFUSED by compliance, attested and published to the public feed as done,
#   while the SAME method's honest `recorded_unsettled` was correctly declined.
#   For that action the only shape reaching either surface was the refusal.
#
# 16-O (fails closed): `pending` and `queued` were read as dispositions when for
#   a record-creating action they are the NEW RECORD's lifecycle state.
#   `x402.create_payment` persists a payment and returns `status: "pending"`
#   because NEW-56 — an earlier fix in THIS audit — stopped it overwriting the
#   real status with "created". So this audit's honesty fix is what made 16-K
#   silence a genuine action, and the refusal log became the only record: an
#   affirmative falsehood, the one outcome the docstring ranks as unrecoverable.
#
# THE TWO POINT IN OPPOSITE DIRECTIONS, AND THAT IS THE DIAGNOSIS. `pending`
# means "claim NOT paid" in `insurance` and "payment record created" in `x402`,
# and both are honest. No classification of the STRING can be right for both, so
# the string cannot be the only evidence consulted.
# ══════════════════════════════════════════════════════════════════════════


# ── 16-N: the statuses the deny-list could not see ────────────────────────


@pytest.mark.parametrize(
    "status,where",
    [
        # reproduced end-to-end by the adversarial pass
        ("compliance_hold", "cross_border/service.py:141 send_payment, remit"),
        ("denied", "insurance/claims_processor.py:123 deny_claim"),
        # PREPARED, UNSIGNED transactions — `_prepared_response`'s own docstring
        # says the server "does NOT sign and does NOT broadcast". Identical in
        # kind to `recorded_unsettled`, which WAS in the deny-list; these were
        # missed only because the naming convention differs.
        ("prepared", "auctions/service.py:551 place_bid, create_auction, …"),
        ("prepared_unsigned", "advanced_governance quadratic_vote, vote_escrow, …"),
        # suffix drift: `error` was classified, `*_error` was not
        ("chain_error", "kyc/service.py:498 issue_kyc_credential"),
        ("provider_error", "kyc/service.py:254 start_kyc"),
        ("invalid_request", "kyc/service.py:195 start_kyc"),
        # nothing to do is not something done
        ("no_rewards", "staking/service.py:406 claim_staking_rewards"),
        ("not_found", "insurance/trigger_manager.py:80 cancel_insurance"),
        ("expired", "x402_payments/service.py:240 authorize_payment"),
        # this audit's own unsettled idiom, in services 16-K never re-read
        ("calculated_unpaid", "fundraising/refunds.py:210 trigger_refunds"),
        ("recorded_unqueued", "governance/service.py:586 timelock_queue"),
        ("matched_unsettled", "securities_exchange/exchange.py:282"),
    ],
)
def test_a_refusal_the_deny_list_never_anticipated_is_not_an_outcome(status, where):
    """DEFECT-PROVER (16-N). Every one of these returned True pre-fix."""
    assert _outcome_is_real({"status": status}) is False, where


def test_an_unrecognised_status_is_not_an_outcome():
    """THE POLARITY ITSELF, not the fourteen strings above.

    Adding the found strings to the deny-list would fix the cases found and
    leave the next unenumerated status open. The defect is the DEFAULT, and this
    is the assertion that pins it: a status nobody has classified is not
    evidence that anything happened.

    The measured asymmetry that decides the `status is None` case does not reach
    here. Absence of a status field is evidence of success — 17 of 182 actions
    return one. A service that BOTHERED TO NAME a status and named something
    unrecognised is the case where you cannot infer.
    """
    assert _outcome_is_real({"status": "quux_not_a_real_status"}) is False
    assert _outcome_is_real({"status": "settled_maybe"}) is False


def test_a_str_enum_member_is_normalised_to_its_value():
    """`str(LoanStatus.ACTIVE)` is 'LoanStatus.ACTIVE', NOT 'active'.

    Seven attested services return `(str, Enum)` members directly as `status`.
    Pre-fix every one of them missed the deny-list on the class-name prefix
    alone, so a refusal member would have been attested as real. Harmless in
    today's data — the members in use happen to be successes — which is exactly
    why it needed a test rather than a reading.
    """
    from enum import Enum

    class _S(str, Enum):
        REJECTED = "rejected"
        ACTIVE = "active"

    assert str(_S.REJECTED) != "rejected", "premise: bare str() does not unwrap"
    assert _outcome_is_real({"status": _S.REJECTED}) is False
    assert _outcome_is_real({"status": _S.ACTIVE}) is True


# ── 16-O: the genuine action the fix silenced ─────────────────────────────


def test_a_created_record_outranks_its_lifecycle_status():
    """DEFECT-PROVER (16-O). `create_payment` persists a real payment and returns
    the record's own status, "pending" — which 16-K read as a refusal.

    `created: True` is the service stating that it acted. It is the only
    evidence that can break the tie, because the same string is an honest
    refusal one package over.
    """
    assert _outcome_is_real({"payment_id": "p1", "status": "pending",
                             "created": True}) is True
    # ...and a pending OUTCOME, with no such claim, is still not an outcome
    assert _outcome_is_real({"claim_id": "c1", "status": "pending",
                             "reason": "Reserve insufficient"}) is False


def test_disclosure_flags_still_outrank_positive_evidence():
    """SCOPE PIN. "A record now exists" is a weaker claim than "no value moved".
    15-A's flags were added to be honest and must stay on top of the order."""
    assert _outcome_is_real({"status": "pending", "created": True,
                             "settled": False}) is False
    assert _outcome_is_real({"status": "active", "created": True,
                             "value_moved": False}) is False


async def test_create_payment_end_to_end_is_attested_again(dispatcher_with_spies):
    """THE REGRESSION, THROUGH THE REAL SERVICE. The predicate-level test above
    can be satisfied by a shape nothing returns; this drives the actual method.

    No test in 16-K did this — every case was a synthetic dict — which is how a
    vocabulary judgement shipped without ever being checked against a real
    record-creating action.
    """
    d, feed, attested, declined = dispatcher_with_spies

    import json

    # execute() returns SERIALISED JSON, not a dict — asserting on the object it
    # returns is asserting on rendered output, which is the rule this engagement
    # has had to relearn in three domains.
    out = json.loads(await d.execute("create_payment", params={
        "agent_id": "agent_1", "recipient": "0xB", "amount": 12.5,
        "token": "USDC", "purpose": "data access",
    }))

    assert out.get("status") == "ok", out
    assert out["result"].get("created") is True, "premise: the payment was created"
    assert out["result"].get("status") == "pending", (
        "premise: the record's own lifecycle status is what 16-K read as a refusal"
    )
    assert attested == ["create_payment"], "a genuine persisted action lost its record"

    # The feed publish is `asyncio.create_task(...)` — fire-and-forget — so it has
    # not run yet at the point execute() returns. Yield once. Without this the
    # assertion below passes for refusals and fails for successes, i.e. it would
    # read as "the feed is correctly silent" on exactly the case it is meant to
    # prove, which is the least useful direction for a test to be wrong in.
    import asyncio

    await asyncio.sleep(0)
    assert [p["action"] for p in feed.published] == ["create_payment"]
    assert declined == [], "a real action was logged as declined"


# ── the ratchet that makes "unanticipated" a test failure ─────────────────


def _censused_statuses() -> dict[str, str]:
    """Every status literal the attested services can emit -> first site.

    THE INSTRUMENT IS THE POINT, so its blind spots are named — and it was
    WRONG THREE TIMES while this fix was being written, each time in instrument
    failure #12's shape: a detector that structurally cannot see a class of site,
    reporting a confident count of what it could see.

      74  dict literals only. `marketplace/service.py` writes
          `listing["status"] = "flagged"` and returns `{**listing}`.
     115  + subscript assignment and `status=` keywords. Scope was
          `services/<pkg>/` for attested services only, so the shared helpers in
          `runtime/blockchain/*.py` that services return THROUGH were invisible.
     129  + the whole `runtime/blockchain` tree. Still Constant-only, and
          `smart_contracts.py` writes
          `"status": "success" if receipt["status"] == 1 else "failed"` — a
          ternary, not a constant.
     147  + IfExp and BoolOp. Eighteen more, including "success" ITSELF, which
          was therefore missing from the set whose only job is naming successes.

    Each count looked authoritative. The lesson is not "walk more node types" but
    that a census reports the intersection of what exists and what the instrument
    can see, and only the second half is knowable from the inside — which is why
    `test_the_walker_sees_every_form_it_has_been_blind_to` exists below.

    Scope is the whole tree, not the precisely reachable subset. Reachability
    needs a call-graph walk, and one that under-approximates would hand back
    exactly the false assurance this test exists to prevent. A superset costs one
    classification when a service adds a word, and it cannot be quietly wrong.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "runtime/blockchain"
    found: dict[str, str] = {}

    def record(value, path, lineno):
        """A status can be an EXPRESSION, not only a literal."""
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            found.setdefault(value.value, f"{path.name}:{lineno}")
        elif isinstance(value, ast.IfExp):
            record(value.body, path, lineno)
            record(value.orelse, path, lineno)
        elif isinstance(value, ast.BoolOp):
            for operand in value.values:
                record(operand, path, lineno)

    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value == "status":
                        record(v, path, getattr(v, "lineno", node.lineno))
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if (isinstance(t, ast.Subscript)
                            and isinstance(t.slice, ast.Constant)
                            and t.slice.value == "status"):
                        record(node.value, path, node.lineno)
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "status":
                        record(kw.value, path, node.lineno)
    return found


def test_the_walker_sees_every_form_it_has_been_blind_to():
    """CONTROL FOR THE RATCHET BELOW — an instrument test, not a code test.

    `test_the_status_vocabulary_is_fully_classified` is exactly as good as the
    walk that feeds it, and that walk was blind three separate times while this
    fix was being written. A ratchet whose instrument silently narrows does not
    fail; it passes, and reports full coverage of a shrinking world.

    One canary per blindness, each naming a real site. If any of these fails the
    ratchet is measuring less than it claims and its green means nothing.
    """
    censused = _censused_statuses()

    assert "flagged" in censused, (
        "blind to SUBSCRIPT ASSIGNMENT: `listing['status'] = 'flagged'` "
        "(services/marketplace/service.py)"
    )
    assert "success" in censused, (
        "blind to TERNARIES: `'status': 'success' if receipt['status'] == 1 "
        "else 'failed'` (smart_contracts.py) — or the scope narrowed back to "
        "services/ and no longer sees the shared helpers services return through"
    )
    assert "payment_attested" in censused, (
        "SCOPE narrowed: runtime/blockchain/crossborder.py is no longer walked"
    )
    assert len(censused) >= 147, (
        f"census collapsed to {len(censused)} statuses, was 147 — the walker is "
        f"seeing less than it did, which makes the classification ratchet pass "
        f"for the wrong reason"
    )


def test_the_status_vocabulary_is_fully_classified():
    """THE ASSERTION THAT WOULD HAVE CAUGHT 16-N AT AUTHORING TIME.

    Not "these fourteen strings are refusals" — that is a list of the things
    already found, and it is stale the moment a service adds a word. This walks
    what the services actually emit and requires every status to have been
    classified DELIBERATELY, in one direction or the other. Falling through is
    no longer a thing the predicate can do quietly.
    """
    from runtime.blockchain.services.service_dispatcher import (
        _NON_OUTCOME_STATUSES,
        _REAL_OUTCOME_STATUSES,
    )

    censused = _censused_statuses()
    classified = _NON_OUTCOME_STATUSES | _REAL_OUTCOME_STATUSES
    unclassified = {s: loc for s, loc in censused.items()
                    if s.strip().lower() not in classified}

    assert not unclassified, (
        f"{len(unclassified)} status string(s) reach _outcome_is_real without a "
        f"deliberate classification, so they are treated as non-outcomes and the "
        f"actions returning them are never attested: {unclassified}. Add each to "
        f"_REAL_OUTCOME_STATUSES (the state genuinely changed) or to "
        f"_NON_OUTCOME_STATUSES (it did not) — do not leave it to the default."
    )

    overlap = _NON_OUTCOME_STATUSES & _REAL_OUTCOME_STATUSES
    assert not overlap, f"a status classified BOTH ways: {sorted(overlap)}"
