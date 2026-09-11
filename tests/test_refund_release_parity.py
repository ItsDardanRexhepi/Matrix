"""NEW-74 — the orphaned refund engine reaches parity with the release path.

THE ASYMMETRY. `release_milestone_funds` fires on verification.
`RefundManager.process_refunds` — a complete, correct pro-rata engine — had
NO caller on the campaign-failure path: failure detection set
`status = "failed"` and stopped. So refund was neither missing nor fake, it
was an ORPHANED REAL MECHANISM. An outflow that triggers plus a return path
that never does is the fund-trap.

This wires failure -> refund computation, symmetric with verification ->
release.

ASSUME-MULTIPLICITY. Failure is detected in FOUR places: `contribute`,
`get_campaign`, `list_campaigns`, and `trigger_refunds`' own check. A
contributor's entitlement must not depend on which method noticed the
deadline first, so all of them route through `_fail_campaign`.
`trigger_refunds` keeps its explicit call because it must RETURN the bulk
result; `process_refunds` writes by (campaign_id, contributor) key, so a
later recomputation overwrites rather than duplicates.

STILL DICT-CUSTODY. This computes and records refunds over the in-process
ledger and initiates no transfer — asserted below, because a wiring commit on
a money path is exactly where an accidental live-custody call could sneak in.
Records carry settled=False / value_moved=False from NEW-68, so wiring the
trigger does not silently upgrade a calculation into a payment claim.
"""

from __future__ import annotations

import time
from pathlib import Path

from runtime.blockchain.services.fundraising.service import FundraisingService

PROOF = {"description": "done", "documents": ["d"], "metrics": {"m": 1}}


async def _expired_campaign(svc, *, goal=1000.0, contribution=400.0):
    """A campaign past its deadline with the goal unmet."""
    campaign = await svc.create_campaign(
        creator="alice", title="Solar", goal=goal, deadline_days=30,
        milestones=[{"description": "p1", "release_pct": 100}],
    )
    cid = campaign["campaign_id"]
    await svc.contribute(campaign_id=cid, contributor="bob", amount=contribution)
    await svc.contribute(campaign_id=cid, contributor="carol", amount=contribution)
    svc._campaigns[cid]["deadline"] = int(time.time()) - 1
    return cid


# ── Failure now computes refunds, at every detection site ────────────────


async def test_failure_detected_by_get_campaign_computes_refunds():
    svc = FundraisingService({})
    cid = await _expired_campaign(svc)

    await svc.get_campaign(cid)

    assert svc._campaigns[cid]["status"] == "failed"
    for contributor in ("bob", "carol"):
        record = await svc.refund_manager.get_refund_status(cid, contributor)
        assert record["status"] == "calculated_unpaid", (
            f"no refund was computed for {contributor} when the campaign "
            "failed — the orphaned engine is still unwired here"
        )


async def test_failure_detected_by_list_campaigns_computes_refunds():
    """The second site. A single-site fix would leave this one silent."""
    svc = FundraisingService({})
    cid = await _expired_campaign(svc)

    await svc.list_campaigns()

    assert svc._campaigns[cid]["status"] == "failed"
    record = await svc.refund_manager.get_refund_status(cid, "bob")
    assert record["status"] == "calculated_unpaid"


async def test_failure_detected_by_contribute_computes_refunds():
    """The third site — reached when a late contribution trips the deadline."""
    svc = FundraisingService({})
    cid = await _expired_campaign(svc)

    try:
        await svc.contribute(campaign_id=cid, contributor="dave", amount=10.0)
    except ValueError:
        pass  # the late contribution is correctly refused

    assert svc._campaigns[cid]["status"] == "failed"
    record = await svc.refund_manager.get_refund_status(cid, "bob")
    assert record["status"] == "calculated_unpaid"


async def test_the_refund_amounts_are_the_real_pro_rata_ones():
    """POSITIVE PROOF — the wiring must invoke the REAL engine, not a stub.

    800 raised, 0 released -> pool 800; bob and carol contributed 400 each,
    so each share is 0.5 -> 400.0.
    """
    svc = FundraisingService({})
    cid = await _expired_campaign(svc)
    await svc.get_campaign(cid)

    bob = await svc.refund_manager.get_refund_status(cid, "bob")
    assert bob["refund_amount"] == 400.0
    assert bob["pro_rata_share"] == 0.5
    assert bob["original_contribution"] == 400.0


async def test_a_campaign_with_no_contributors_does_not_fabricate_refunds():
    """The boundary case: failure with nothing contributed must produce no
    records rather than an empty-but-present refund claim."""
    svc = FundraisingService({})
    campaign = await svc.create_campaign(
        creator="alice", title="Empty", goal=1000.0, deadline_days=30,
        milestones=[{"description": "p1", "release_pct": 100}],
    )
    cid = campaign["campaign_id"]
    svc._campaigns[cid]["deadline"] = int(time.time()) - 1

    await svc.get_campaign(cid)

    assert svc._campaigns[cid]["status"] == "failed"
    record = await svc.refund_manager.get_refund_status(cid, "nobody")
    assert record["status"] == "none"


# ── The symmetry assertion — the pair that closes the fund-trap ──────────


async def test_a_creator_cannot_both_self_trigger_release_and_deny_refund():
    """THE PAIR. Release fires only on real verification (NEW-73); refund
    fires on real failure (NEW-74). Neither is self-triggerable, so the
    creator cannot take the outflow while withholding the return."""
    svc = FundraisingService({})
    campaign = await svc.create_campaign(
        creator="mallory", title="Self Fund", goal=5000.0, deadline_days=30,
        milestones=[{"description": "p1", "release_pct": 100}],
    )
    cid = campaign["campaign_id"]
    # below goal, so the campaign stays "active" and can fail at the deadline
    # (a campaign that MET its goal becomes "funded" and correctly does not
    # auto-fail — verified while writing this test)
    await svc.contribute(campaign_id=cid, contributor="victim", amount=1000.0)

    # (a) the creator self-attests a milestone and tries to release
    await svc.milestone_verification.submit_milestone(cid, 0, PROOF)
    await svc.milestone_verification.verify_milestone(cid, 0, "oracle")
    try:
        await svc.release_milestone_funds(cid, 0)
        raise AssertionError("self-approved milestone released funds")
    except ValueError as exc:
        assert "must be verified" in str(exc)

    # (b) and the contributor's refund still computes on failure
    svc._campaigns[cid]["deadline"] = int(time.time()) - 1
    await svc.get_campaign(cid)

    assert svc._campaigns[cid]["released"] == 0.0, "funds left via self-approval"
    record = await svc.refund_manager.get_refund_status(cid, "victim")
    assert record["status"] == "calculated_unpaid"
    assert record["refund_amount"] == 1000.0


async def test_released_funds_are_excluded_from_the_refundable_pool():
    """Parity does not mean double-paying. A legitimately released milestone
    must reduce what is refundable — the engine's release-awareness must
    survive the wiring."""
    svc = FundraisingService({})
    campaign = await svc.create_campaign(
        creator="alice", title="Solar", goal=5000.0, deadline_days=30,
        milestones=[{"description": "p1", "release_pct": 50},
                    {"description": "p2", "release_pct": 50}],
    )
    cid = campaign["campaign_id"]
    # below goal so the campaign can still fail at its deadline after a
    # legitimate release
    await svc.contribute(campaign_id=cid, contributor="bob", amount=1000.0)

    # a genuinely verified milestone releases half
    eligible = {"v1", "v2", "v3", "v4", "v5"}
    svc._milestones._voter_eligibility = lambda _cid: eligible
    await svc.milestone_verification.submit_milestone(cid, 0, PROOF)
    for v in eligible:
        svc.milestone_verification.cast_community_vote(cid, 0, voter=v, approve=True)
    await svc.milestone_verification.verify_milestone(cid, 0, "community_vote")
    await svc.release_milestone_funds(cid, 0)
    assert svc._campaigns[cid]["released"] == 500.0

    svc._campaigns[cid]["deadline"] = int(time.time()) - 1
    await svc.get_campaign(cid)

    record = await svc.refund_manager.get_refund_status(cid, "bob")
    assert record["refund_amount"] == 500.0, (
        "the refundable pool ignored the released half — releases and refunds "
        "would together exceed contributions"
    )


# ── The wiring did not cross into live transfer ─────────────────────────


def test_wiring_the_refund_path_did_not_introduce_real_custody():
    """A wiring commit on a money path is exactly where an accidental live
    transfer could sneak in. Assert the package still moves nothing."""
    pkg = Path(__file__).resolve().parent.parent / (
        "runtime/blockchain/services/fundraising"
    )
    banned = (
        "send_transaction", "build_transaction", "_send_eth",
        "web3", "private_key", "signer",
    )
    for path in pkg.glob("*.py"):
        live = "\n".join(
            ln for ln in path.read_text().splitlines()
            if not ln.strip().startswith("#")
        )
        for token in banned:
            assert token not in live, f"{path.name} now moves value ({token})"


async def test_computed_refunds_still_disclose_that_nothing_was_paid():
    """Wiring the trigger must not upgrade a calculation into a payment
    claim — the NEW-68 disclosure has to survive."""
    svc = FundraisingService({})
    cid = await _expired_campaign(svc)
    await svc.get_campaign(cid)

    record = await svc.refund_manager.get_refund_status(cid, "bob")
    assert record["settled"] is False
    assert record["value_moved"] is False
    assert "No funds have been returned" in record["disclosure"]
