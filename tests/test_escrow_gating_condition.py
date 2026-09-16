"""NEW-75 — the compound escrow gating condition, and the guards behind it.

Domain 6's safety converges on one place: the moment fundraising is wired to
real custody. Three conditions must ALL hold, and each partial state is a
distinct failure mode rather than a partial improvement:

  1. verification is authority-gated on both paths          (NEW-73)
  2. release stays gated on it, refund is wired to failure  (NEW-74)
  3. contribute + release + refund migrate together         (NEW-75)

This file makes the checklist load-bearing rather than decorative. It fails
if the condition text is removed, if any clause silently regresses, or if a
money path starts touching real value while the clauses are unmet.

The NEW-62 precedent attached a condition to a config line. This is that
pattern at three clauses, where the coupling is the point: a developer who
satisfies two is not two-thirds safe.
"""

from __future__ import annotations

import time
from pathlib import Path

from runtime.blockchain.services.fundraising.service import FundraisingService

SERVICE = (
    Path(__file__).resolve().parent.parent
    / "runtime/blockchain/services/fundraising/service.py"
)
PROOF = {"description": "done", "documents": ["d"], "metrics": {"m": 1}}


# ── The condition exists where a developer would wire custody ────────────


def test_the_escrow_gating_condition_is_present_and_names_all_three_clauses():
    """A condition a future developer never sees is not a control.

    It lives at module level in the service they would edit to add custody,
    not in a doc they would have to think to open.
    """
    text = SERVICE.read_text()
    assert "ESCROW GATING CONDITION" in text
    for clause in (
        "VERIFICATION IS AUTHORITY-GATED ON BOTH PATHS",
        "REFUND IS\n#          WIRED TO REAL FAILURE",
        "MIGRATE TO REAL CUSTODY IN ONE",
    ):
        assert clause in text, f"clause missing from the checklist: {clause}"


def test_each_clause_names_its_own_partial_state_failure_mode():
    """The coupling is the point. A checklist that lists three requirements
    without saying what breaks when you satisfy only two invites exactly the
    incremental migration it is meant to prevent."""
    text = SERVICE.read_text()
    assert text.count("PARTIAL-STATE FAILURE MODE") >= 3, (
        "not every clause states what specifically breaks if it alone is unmet"
    )
    for mode in (
        "real money in, dict money out",
        "pays out against",
        "repays money it",
    ):
        assert mode in text, f"missing partial-state failure mode: {mode}"


def test_no_escrow_config_key_exists_yet():
    """The absence of a custody config key is load-bearing, not an oversight.

    If someone adds one, this fails — which is the intended moment for the
    checklist above to be read.
    """
    import json

    example = Path(__file__).resolve().parent.parent / "matrix.config.json.example"
    cfg = json.loads(example.read_text()).get("fundraising", {})
    for key in ("escrow_address", "escrow_contract", "custody_address", "treasury"):
        assert key not in cfg, (
            f"a custody config key ({key}) was added to fundraising — read the "
            "ESCROW GATING CONDITION in service.py before proceeding"
        )


# ── Clause 1 still holds ─────────────────────────────────────────────────


async def test_clause_1_verification_cannot_self_approve():
    svc = FundraisingService({})
    mv = svc.milestone_verification
    await mv.submit_milestone("c", 0, PROOF)
    assert (await mv.verify_milestone("c", 0, "oracle"))["status"] != "verified"

    await mv.submit_milestone("c2", 0, PROOF)
    for i in range(mv._min_voters):
        mv.cast_community_vote("c2", 0, voter=f"0xsock{i}", approve=True)
    assert (
        await mv.verify_milestone("c2", 0, "community_vote")
    )["status"] != "verified"


# ── Clause 2 still holds, including the replay leg ───────────────────────


async def test_clause_2_refund_fires_on_failure_and_is_replay_safe():
    """REPLAY LEG. Wiring the refund path created the surface for it.

    Replay-safety currently holds because both ledgers are dicts keyed by
    (campaign_id[, contributor]) and recomputation OVERWRITES. That is a
    property of the data structure, not a guarded invariant — if
    `_bulk_refunds` ever became a list, or the key changed, a retried failure
    path would silently double-count. This pins it.
    """
    svc = FundraisingService({})
    campaign = await svc.create_campaign(
        creator="alice", title="S", goal=5000.0, deadline_days=30,
        milestones=[{"description": "p", "release_pct": 100}],
    )
    cid = campaign["campaign_id"]
    await svc.contribute(campaign_id=cid, contributor="bob", amount=400.0)
    svc._campaigns[cid]["deadline"] = int(time.time()) - 1

    await svc.get_campaign(cid)
    for _ in range(3):
        await svc.trigger_refunds(cid)

    rm = svc.refund_manager
    assert len([k for k in rm._bulk_refunds if k == cid]) == 1
    assert len([k for k in rm._refunds if k == (cid, "bob")]) == 1

    record = await rm.get_refund_status(cid, "bob")
    assert record["refund_amount"] == 400.0, (
        "a replayed failure path changed the refund owed — recomputation is "
        "no longer idempotent"
    )
    assert rm._bulk_refunds[cid]["total_calculated"] == 400.0, (
        "the bulk ledger accumulated across replays"
    )


# ── Clause 3: nothing has migrated to real custody ───────────────────────


def test_clause_3_no_money_path_touches_real_value():
    """The clause that must not be satisfied incrementally. If ANY of the
    three paths starts moving value, this fails — which forces the other two
    to be considered in the same change."""
    pkg = SERVICE.parent
    banned = (
        "send_transaction", "build_transaction", "_send_eth",
        "web3", "private_key", "signer", "eth_sendRaw",
    )
    for path in pkg.glob("*.py"):
        live = "\n".join(
            ln for ln in path.read_text().splitlines()
            if not ln.strip().startswith("#")
        )
        for token in banned:
            assert token not in live, (
                f"{path.name} touches real value ({token}) — clause 3 requires "
                "contribute, release AND refund to migrate together; verify "
                "clauses 1 and 2 before this lands"
            )


async def test_the_whole_chain_is_still_dict_custody_end_to_end():
    """contribute records, verify authorises, release computes, refund
    computes — and nothing transfers. Asserted as one sequence, because the
    no-disable ruling rests on the chain as a whole, not on any single link."""
    svc = FundraisingService({})
    campaign = await svc.create_campaign(
        creator="alice", title="S", goal=5000.0, deadline_days=30,
        milestones=[{"description": "p", "release_pct": 100}],
    )
    cid = campaign["campaign_id"]

    await svc.contribute(campaign_id=cid, contributor="bob", amount=1000.0)
    assert svc._campaigns[cid]["raised"] == 1000.0
    assert isinstance(svc._contributions[cid], dict)

    eligible = {"v1", "v2", "v3", "v4", "v5"}
    svc._milestones._voter_eligibility = lambda _cid: eligible
    await svc.milestone_verification.submit_milestone(cid, 0, PROOF)
    for v in eligible:
        svc.milestone_verification.cast_community_vote(cid, 0, voter=v, approve=True)
    await svc.milestone_verification.verify_milestone(cid, 0, "community_vote")

    released = await svc.release_milestone_funds(cid, 0)
    assert released["release_amount"] == 1000.0
    assert "tx_hash" not in released, "a release produced a transaction hash"

    assert isinstance(svc._campaigns, dict) and isinstance(svc._contributions, dict)
