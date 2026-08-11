"""NEW-73 (+ NEW-59 fundraising instance) — milestone verification cannot
self-approve.

THE HOLE. `verify_milestone` is the RELEASE TRIGGER: `release_milestone_funds`
refuses unless the milestone's status is "verified". Both routes to that
status were self-grantable by the party who benefits.

  oracle path — with no oracle configured (the DEFAULT, see NEW-59 below) it
      fell back to reading the SUBMITTER'S OWN proof dict and approving on
      `description and (documents or metrics)`. The submitter writes that
      dict, so {"description": "done", "documents": ["x"]} self-approved.

  community_vote path — `cast_community_vote` takes `voter` as a
      caller-supplied STRING: no signature, no eligibility check against
      contributors, no exclusion of the campaign creator, and double-voting
      prevented only by string equality. Five invocations with five invented
      addresses cleared the default quorum of 5 at 100% approval.

So a fix covering only the oracle path would have left the other open. Both
fail closed now.

WHY THIS IS WORSE THAN AN UNGATED RELEASE, and the reason it reads as safe:
a reviewer sees `if ms_status["status"] != "verified": raise` in
release_milestone_funds and concludes the release is authority-gated. It is —
gated on an authority that is the beneficiary. The gate's existence is what
made the hole invisible.

NEW-59 IS THE CAUSE, NOT A NEIGHBOUR. ServiceRegistry.get() does
`cls(self._config)` — one positional arg — so FundraisingService's
`oracle_service` parameter was never supplied and the self-attesting branch
was not an edge case but the ONLY branch that ever ran. In defi the same
registry gap made prices fake; here it made verification self-granted. Same
root, different severity class: correctness there, authorization here.

REACHABILITY (why this was a fix and not an emergency disable): traced before
building. `verify_milestone` is on NO surface — not ACTION_MAP, catalog,
intent table, routes, bridge, or extensions registry — and has no production
caller. `release_milestone_funds` moves no value: no send_transaction, no
transfer, no chain call anywhere in the fundraising package; it mutates
`campaign["released"]`, a dict field. So the harm is armed-on-deployment, not
live, and the domain stays up.

WHAT IS DELIBERATELY *NOT* DECIDED HERE: who is entitled to vote.
MilestoneVerification has no access to the contributor set, and whether
voters are contributors, weighted by contribution, or exclude the creator is
a governance design decision. Choosing one inside a security fix would be
inventing policy under cover of a defect fix. The tally logic is preserved
intact and re-opens the moment an eligibility source is supplied.
"""

from __future__ import annotations

import inspect

from runtime.blockchain.services.fundraising.milestone_verification import (
    MilestoneVerification,
)
from runtime.blockchain.services.fundraising.service import FundraisingService

PROOF = {"description": "done", "documents": ["self-written"], "metrics": {"x": 1}}


# ── NEW-59: the oracle is resolvable ─────────────────────────────────────


def test_the_oracle_resolves_instead_of_staying_none():
    """Built the way the registry builds it — one positional arg."""
    from runtime.blockchain.services.oracle_gateway import OracleGateway

    svc = FundraisingService({})
    assert isinstance(svc._milestones._oracle_service, OracleGateway), (
        "milestone verification still has no authority — the self-attesting "
        "branch would be the only path that ever runs"
    )


def test_the_registry_builds_this_service_with_config_only():
    """Pins the constraint that makes NEW-59 real, so a future reader does not
    'simplify' the lazy resolution away believing DI exists."""
    params = inspect.signature(FundraisingService.__init__).parameters
    assert params["oracle_service"].default is None, (
        "oracle_service is no longer optional-and-unsupplied; if real DI was "
        "added, the lazy resolution can be revisited"
    )


# ── The oracle path fails closed ─────────────────────────────────────────


async def test_self_written_proof_cannot_verify_a_milestone():
    """THE REPRODUCTION. The submitter's own proof must not approve."""
    mv = MilestoneVerification({}, None)
    await mv.submit_milestone("c", 0, PROOF)

    result = await mv.verify_milestone("c", 0, "oracle")

    assert result["status"] != "verified", (
        "a milestone was verified from the submitter's own proof dict — this "
        "is the release trigger, so this is self-granted fund release"
    )
    assert result["result"]["authority_available"] is False
    assert "authority unavailable" in result["result"]["reason"].lower()


def test_the_self_attesting_fallback_is_gone_from_the_source():
    """Proves the FALLBACK PATH is removed, not merely unreachable.

    An unreachable-but-present fallback is one refactor away from being the
    live path again, which is exactly how it became the live path the first
    time.
    """
    src = inspect.getsource(MilestoneVerification._verify_via_oracle)
    live = [
        ln for ln in src.splitlines()
        if not ln.strip().startswith("#") and '"""' not in ln
    ]
    body = "\n".join(live)
    assert '"approved": True' not in body, (
        "_verify_via_oracle can still return approved=True without consulting "
        "an authority"
    )
    assert "has_docs" not in body and "has_metrics" not in body, (
        "the proof-sniffing fallback is still present in the live body"
    )


# ── The community-vote path fails closed too ─────────────────────────────


async def test_invented_voters_cannot_clear_the_quorum():
    """THE SECOND REPRODUCTION — the one a single-path fix would have missed.

    Five caller-supplied strings met the default quorum of 5 at 100%
    approval. They must no longer be counted at all.
    """
    mv = MilestoneVerification({}, None)
    await mv.submit_milestone("c", 0, PROOF)
    for i in range(mv._min_voters):
        mv.cast_community_vote("c", 0, voter=f"0xsockpuppet{i}", approve=True)

    result = await mv.verify_milestone("c", 0, "community_vote")

    assert result["status"] != "verified", (
        "invented voter strings still verify a milestone"
    )
    assert result["result"]["authority_available"] is False


async def test_the_real_tally_survives_when_eligibility_exists():
    """POSITIVE PROOF, not absence. The fix must not have removed working
    logic — quorum, approval rate and threshold are genuine computations. With
    an eligibility source supplied, verification works AND ineligible voters
    are excluded."""
    eligible = {"a", "b", "c", "d", "e", "f"}
    mv = MilestoneVerification({}, None, voter_eligibility=lambda _cid: eligible)
    await mv.submit_milestone("c", 0, PROOF)
    for who in ("a", "b", "c", "d", "e"):
        mv.cast_community_vote("c", 0, voter=who, approve=True)
    mv.cast_community_vote("c", 0, voter="0xoutsider", approve=True)

    result = await mv.verify_milestone("c", 0, "community_vote")

    assert result["status"] == "verified"
    assert result["result"]["total_votes"] == 5, (
        "the ineligible voter was counted — eligibility filtering is not "
        "actually applied"
    )


async def test_an_eligible_but_rejecting_majority_still_rejects():
    """The threshold is real, not a rubber stamp for anyone eligible."""
    eligible = {"a", "b", "c", "d", "e"}
    mv = MilestoneVerification({}, None, voter_eligibility=lambda _cid: eligible)
    await mv.submit_milestone("c", 0, PROOF)
    for who, ok in (("a", True), ("b", False), ("c", False), ("d", False), ("e", True)):
        mv.cast_community_vote("c", 0, voter=who, approve=ok)

    result = await mv.verify_milestone("c", 0, "community_vote")
    assert result["status"] == "rejected"


# ── The release trigger is closed end to end ─────────────────────────────


async def test_a_self_approved_milestone_cannot_release_funds():
    """THE WHOLE POINT, asserted through the real release path rather than at
    the verification unit alone."""
    svc = FundraisingService({})
    campaign = await svc.create_campaign(
        creator="mallory", title="Self Fund", goal=1000.0, deadline_days=30,
        milestones=[{"description": "p1", "release_pct": 100}],
    )
    cid = campaign["campaign_id"]
    await svc.contribute(campaign_id=cid, contributor="victim", amount=1000.0)

    await svc.milestone_verification.submit_milestone(cid, 0, PROOF)
    await svc.milestone_verification.verify_milestone(cid, 0, "oracle")

    try:
        await svc.release_milestone_funds(cid, 0)
        raise AssertionError(
            "funds were released on a self-approved milestone"
        )
    except ValueError as exc:
        assert "must be verified" in str(exc)

    assert svc._campaigns[cid]["released"] == 0.0


# ── Reachability facts that made this a fix, not a disable ───────────────


def test_release_moves_no_value():
    """Pins the fact that decided against an interim disable. If a real
    transfer is ever added here, this fails and the disable question reopens
    BEFORE the escrow lands."""
    from pathlib import Path

    pkg = Path(__file__).resolve().parent.parent / (
        "runtime/blockchain/services/fundraising"
    )
    banned = (
        "send_transaction", "build_transaction", "_send_eth",
        "web3", "private_key", "signer",
    )
    for path in pkg.glob("*.py"):
        text = path.read_text()
        live = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        for token in banned:
            assert token not in live, (
                f"{path.name} now touches real value ({token}) — the "
                "armed-on-deployment assessment for NEW-73 must be redone"
            )
