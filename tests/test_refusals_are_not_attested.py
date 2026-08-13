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
    def __init__(self) -> None:
        self.published: list[dict] = []

    def ingest(self, **kwargs):  # noqa: D401 - test double
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
