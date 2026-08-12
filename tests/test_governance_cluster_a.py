"""CLUSTER A — three mechanisms that together made the ballot irrelevant.

Caller-declared weight, unbounded by an empty snapshot, resolved by a tally that
passed anything quorate. Each is individually explicable as an oversight.
Together they are a voting system in which the votes cannot affect the outcome,
and any ONE fixed alone leaves the other two sufficient:

    fix the tally   -> weight is still forgeable
    bound the weight -> the snapshot is still empty
    fill the snapshot -> the tally still passes everything

THE FIX ORDER IS LOAD-BEARING, not a preference. Today the ballot cannot affect
the outcome, so forged weight changes nothing observable. REPAIRING THE TALLY
FIRST would convert a system where votes are ignored into one where FORGED votes
decide — strictly worse than the current state, and it would look like progress.
That is the repoint hazard (fixing a defect arms what the defect was hiding)
applied to a security property rather than a code path. Weight-binding lands
first or together; the tally lands last.

THE ARCHITECTURE WAS ALREADY CORRECT AND FED NOTHING. `check_vote` clamps a
declared weight DOWN to the snapshot balance — the intended design was sound.
The defect was that `create_proposal` called `take_snapshot(pid, {})`, and an
empty dict is falsy, so the clamp never ran. Third instance in this engagement
of correct machinery starved of its input, after the honest factory whose
refusal was discarded and the real oracle path with no callers.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.governance.service import GovernanceService

#: total_eligible 10 x standard threshold 0.1 => 1 participant meets quorum, so
#: the tally branch is REACHABLE. With the default 1000 it is not, and a test
#: that never reaches the branch it exists for is the trap this file guards.
_QUORATE = {"governance": {"total_eligible_voters": 10}}


async def _four_voters_three_against(svc: GovernanceService) -> dict:
    p = await svc.create_proposal("0xp", "T", "d", "one_person_one_vote", ["yes", "no"])
    pid = p["proposal_id"]
    for i in range(3):
        await svc.vote(pid, f"0xNO{i}", "no", weight=999_999.0)
    await svc.vote(pid, "0xYES", "yes", weight=1.0)
    return await svc.finalize(pid)


# ── THE LOAD-BEARING ASSERTION ───────────────────────────────────────────


async def test_a_proposal_that_loses_is_rejected():
    """THE ONE THAT PROVES THE CLUSTER. Three against, one for, quorum met.

    It asserts on `outcome_basis`, not only on the verdict. THE VERDICT ALONE
    IS NOT ENOUGH: an early run of this scenario returned "rejected" via the
    QUORUM branch, so the assertion passed without ever executing the tally
    line under repair. A test that reaches the right answer down the wrong path
    is indistinguishable from one that reaches it down the right path unless it
    asserts WHICH path ran.
    """
    result = await _four_voters_three_against(GovernanceService(_QUORATE))
    r = result["result"]

    assert r["quorum"]["quorum_met"] is True, (
        "the scenario is not quorate, so this test would pass down the quorum "
        "branch without exercising the tally fix at all"
    )
    assert r["tally"]["winner"] == "no"
    assert r["outcome"] == "rejected"
    assert "not an approval option" in r["outcome_basis"], (
        f"the verdict came from the wrong branch: {r['outcome_basis']!r}"
    )


async def test_a_proposal_that_wins_still_passes():
    """POSITIVE CONTROL. The fix must not hardcode rejection — that would be
    the same defect with the sign flipped."""
    svc = GovernanceService(_QUORATE)
    p = await svc.create_proposal("0xp", "T", "d", "one_person_one_vote", ["yes", "no"])
    pid = p["proposal_id"]
    for i in range(3):
        await svc.vote(pid, f"0xY{i}", "yes")
    await svc.vote(pid, "0xN", "no")

    r = (await svc.finalize(pid))["result"]
    assert r["tally"]["winner"] == "yes"
    assert r["outcome"] == "passed"
    assert "won with" in r["outcome_basis"]


# ── Step 1: the weight is no longer the caller's to declare ──────────────


async def test_a_weighted_vote_is_refused_while_no_balance_source_exists():
    svc = GovernanceService(_QUORATE)
    p = await svc.create_proposal("0xp", "T", "d", "token_weighted", ["yes", "no"])

    with pytest.raises(ValueError, match="Weighted voting is unavailable"):
        await svc.vote(p["proposal_id"], "0xA", "no", weight=999_999.0)


async def test_the_refusal_names_its_lifting_condition():
    """A refusal that does not say what would restore the capability is a dead
    end. This one names the balance source and the alternative model."""
    svc = GovernanceService(_QUORATE)
    p = await svc.create_proposal("0xp", "T", "d", "quadratic", ["yes", "no"])

    with pytest.raises(ValueError) as exc:
        await svc.vote(p["proposal_id"], "0xA", "no", weight=999_999.0)
    msg = str(exc.value)
    assert "balance source" in msg
    assert "one_person_one_vote" in msg


async def test_a_forged_weight_cannot_move_one_person_one_vote():
    """The model that survives does so because it discards the weight by
    construction — verified, not assumed."""
    svc = GovernanceService(_QUORATE)
    p = await svc.create_proposal("0xp", "T", "d", "one_person_one_vote", ["yes", "no"])
    v = await svc.vote(p["proposal_id"], "0xA", "no", weight=999_999.0)

    assert v["raw_weight"] == 999_999.0
    assert v["effective_weight"] == 1.0


# ── Step 2: no snapshot is fabricated ────────────────────────────────────


async def test_no_empty_snapshot_is_planted():
    """`take_snapshot(pid, {})` made the service LOOK protected: the empty dict
    is falsy, so check_vote's flash-loan branch was skipped entirely."""
    svc = GovernanceService(_QUORATE)
    p = await svc.create_proposal("0xp", "T", "d", "one_person_one_vote", ["yes", "no"])

    assert p["proposal_id"] not in svc.anti_manipulation._snapshots, (
        "an empty snapshot is being planted again — the protection reads as "
        "configured while doing nothing"
    )


def test_the_flash_loan_branch_works_when_it_is_actually_fed():
    """THE PRE-REPOINT CHECK, applied to this cluster.

    The flash-loan clamp has NEVER EXECUTED — the snapshot was always empty, so
    the branch was unreachable for the life of the defect. Wiring a balance
    source would run it for the first time, which is exactly how the APY
    overflow arrived. So it is exercised HERE, directly, with a populated
    snapshot, before anything depends on it.
    """
    svc = GovernanceService(_QUORATE)
    am = svc.anti_manipulation
    am.take_snapshot("p1", {"0xrich": 100.0, "0xpoor": 0.0})

    assert am.get_snapshot_balance("p1", "0xrich") == 100.0
    assert am.get_snapshot_balance("p1", "0xpoor") == 0.0
    assert am.get_snapshot_balance("p1", "0xunknown") == 0.0


async def test_the_clamp_actually_clamps_when_fed():
    """The design was sound and starved. Proven now, so the seam is known-good.

    AND THE PRE-REPOINT CHECK EARNED ITS PLACE HERE. I predicted the clamp
    would return the snapshot balance, 5.0. It returns 0.5, because the branch
    has TWO stages and only the first is the flash-loan clamp:

        check 2  flash-loan   999999 -> 5.0   (clamped to snapshot balance)
        check 5  weight cap   5.0    -> 0.5   (a sole holder is 100% of the
                                               snapshot, over max_weight_ratio)

    The code is right and my expectation was wrong. That is exactly the value
    of exercising a never-executed branch BEFORE wiring anything to it: had a
    balance source been plugged in on the assumption above, every weight would
    have come out an order of magnitude below what the author expected, and the
    cause would have been a cap nobody remembered.
    """
    svc = GovernanceService(_QUORATE)
    am = svc.anti_manipulation
    am.take_snapshot("p1", {"0xa": 5.0})

    result = await am.check_vote("p1", "0xa", 999_999.0, proposal_text="t")
    assert "flash_loan_suspected" in result["flags"], "the clamp did not fire"
    assert "weight_cap_exceeded" in result["flags"]
    assert result["adjusted_weight"] == pytest.approx(0.5)


async def test_the_clamp_is_visible_in_isolation_when_the_cap_does_not_bind():
    """The same clamp with several holders, so the cap is not the binding
    constraint and the flash-loan stage can be read on its own."""
    svc = GovernanceService(_QUORATE)
    am = svc.anti_manipulation
    am.take_snapshot("p1", {"0xa": 5.0, **{f"0x{i}": 20.0 for i in range(9)}})

    result = await am.check_vote("p1", "0xa", 999_999.0, proposal_text="t")
    assert "flash_loan_suspected" in result["flags"]
    assert result["adjusted_weight"] == 5.0, (
        "with the cap slack, a declared weight must be clamped to exactly the "
        "snapshot balance"
    )


async def test_a_voter_absent_from_a_populated_snapshot_is_refused():
    """The other half of the branch, also never executed: a voter who held
    nothing at snapshot time is not merely down-weighted, they are BLOCKED."""
    svc = GovernanceService(_QUORATE)
    am = svc.anti_manipulation
    am.take_snapshot("p1", {"0xrich": 100.0, "0xpoor": 0.0})

    result = await am.check_vote("p1", "0xpoor", 50.0, proposal_text="t")
    assert result["allowed"] is False
    assert "no_snapshot_balance" in result["flags"]
    assert result["adjusted_weight"] == 0.0


# ── Scope ────────────────────────────────────────────────────────────────


async def test_the_status_clobber_is_out_of_scope_and_still_present():
    """SCOPE PIN. `finalize` writes passed/rejected and then overwrites status
    with "finalized", so those remain unreachable STATUSES. That is a separate
    standalone item, not Cluster A, and it is pinned so the boundary is visible
    rather than assumed."""
    result = await _four_voters_three_against(GovernanceService(_QUORATE))

    assert result["status"] == "finalized"
    assert result["result"]["outcome"] == "rejected"
