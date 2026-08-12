"""`self._proposals` holds proposals. Three methods used to write other things.

THE FINDING IS THE TEST THAT MISSED IT. `list_proposals()` iterates
`self._proposals` and reads `["title"]` from every value. THREE methods wrote
non-proposal records into it under prefixed keys:

    queue_timelock     -> "_timelock_<id>"
    propose_multisig   -> "_multisig_<id>"
    parameter_change   -> "_param_<id>"

The Cluster B commit fixed ONE of them and shipped a test asserting that
listing survives — which it did, because the test called `queue_timelock` and
nothing else. One instance fixed reads as a class closed when the test only
covers the instance. The other two writers still corrupted the store, and the
suite said 2000 passed.

So every writer is triggered INDIVIDUALLY below, and then all three together,
because "I fixed the one my test happened to call" is the exact shape of the
defect this file exists to prevent recurring.

NO READER WAS BROKEN BY THE MOVE. Grepped before changing: `_multisig_` and
`_param_` appeared only at their write sites and in prose. `_timelocks` is read
by nothing but its tests. The repoint rule says a move is not free even when the
target is clean — here the target had no readers at all, which is why the
records were safe to relocate and also why nothing noticed they were corrupt.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.governance.service import GovernanceService


async def _a_real_proposal(svc: GovernanceService) -> str:
    p = await svc.create_proposal("0xp", "T", "d", "one_person_one_vote", ["yes", "no"])
    return p["proposal_id"]


# ── Each writer, on its own ──────────────────────────────────────────────


async def test_queue_timelock_keeps_its_record_out_of_the_proposal_store():
    svc = GovernanceService({})
    pid = await _a_real_proposal(svc)

    record = await svc.queue_timelock(pid)

    assert record["id"] in svc._timelocks
    assert record["id"] not in svc._proposals
    assert len(await svc.list_proposals()) == 1


async def test_propose_multisig_keeps_its_record_out_of_the_proposal_store():
    """SECOND WRITER — invisible to the first fix's test, which never called it."""
    svc = GovernanceService({})
    await _a_real_proposal(svc)

    record = await svc.propose_multisig(
        proposer="0xp", signers=["0xp", "0xq"], threshold=2,
        action="transfer", params={},
    )

    assert record["id"] in svc._multisigs
    assert record["id"] not in svc._proposals
    assert len(await svc.list_proposals()) == 1


async def test_parameter_change_keeps_its_record_out_of_the_proposal_store():
    """THIRD WRITER — same."""
    svc = GovernanceService({})
    await _a_real_proposal(svc)

    record = await svc.parameter_change(
        parameter="quorum", old_value=0.1, new_value=0.2, proposer="0xp",
    )

    assert record["id"] in svc._parameter_changes
    assert record["id"] not in svc._proposals
    assert len(await svc.list_proposals()) == 1


# ── All three at once, which is what a real service does ─────────────────


async def test_listing_survives_all_three_writers_together():
    """THE ASSERTION THE FIRST PASS SHOULD HAVE MADE. Any one of these three
    was individually sufficient to break `list_proposals()`."""
    svc = GovernanceService({})
    pid = await _a_real_proposal(svc)

    await svc.queue_timelock(pid)
    await svc.propose_multisig(
        proposer="0xp", signers=["0xp", "0xq"], threshold=2, action="x", params={},
    )
    await svc.parameter_change(
        parameter="quorum", old_value=0.1, new_value=0.2, proposer="0xp",
    )

    listed = await svc.list_proposals()
    assert len(listed) == 1
    assert listed[0]["proposal_id"] == pid
    assert all("title" in row for row in listed)


async def test_the_proposal_store_holds_only_proposals():
    """THE INVARIANT ITSELF, stated once so a fourth writer fails here rather
    than in whatever reads the store next."""
    svc = GovernanceService({})
    await _a_real_proposal(svc)
    await svc.queue_timelock(await _a_real_proposal(svc))
    await svc.propose_multisig(
        proposer="0xp", signers=["0xp"], threshold=1, action="x", params={},
    )
    await svc.parameter_change(
        parameter="q", old_value=1, new_value=2, proposer="0xp",
    )

    for key, value in svc._proposals.items():
        assert not key.startswith("_"), f"non-proposal record in _proposals: {key}"
        assert "title" in value, f"value under {key} is not a proposal: {value!r}"


async def test_each_record_is_still_returned_to_its_caller():
    """SCOPE PIN. Moving the records must not change what callers receive —
    only where the service keeps them."""
    svc = GovernanceService({})

    ms = await svc.propose_multisig(
        proposer="0xp", signers=["0xp", "0xq"], threshold=2, action="x", params={},
    )
    assert ms["signers"] == ["0xp", "0xq"] and ms["threshold"] == 2
    assert ms["approvals"] == ["0xp"]

    pc = await svc.parameter_change(
        parameter="quorum", old_value=0.1, new_value=0.2, proposer="0xp",
    )
    assert pc["parameter"] == "quorum" and pc["new_value"] == 0.2


# ── The disclosure is the deliverable, so a test must observe it ─────────


async def test_the_timelock_disclosure_is_present_and_specific():
    """DELETING THE DISCLOSURE MUST NOT LEAVE THE SUITE GREEN.

    An adversarial pass removed the entire `disclosure` string from the disabled
    `treasury_transfer` return and all 18 Cluster B tests stayed green. The
    disclosure IS the deliverable of an honesty fix — if nothing observes it, the
    fix is unpinned and the next refactor drops it silently.

    This asserts the CONTENT, not merely the key: a disclosure that says nothing
    would satisfy `"disclosure" in record`.
    """
    svc = GovernanceService({})
    record = await svc.queue_timelock(await _a_real_proposal(svc))

    disclosure = record["disclosure"]
    assert "RECORDED, NOT QUEUED" in disclosure
    assert "nothing reads this record" in disclosure.lower()
    assert "runtime/blockchain/governance.py" in disclosure, (
        "the disclosure must name the on-chain path it is NOT connected to — "
        "the previous version claimed no executor existed anywhere, which was "
        "false"
    )
    assert "status is unchanged" in disclosure


async def test_the_disclosure_does_not_claim_no_executor_exists():
    """THE FALSE CLAIM, pinned so it cannot come back.

    `runtime/blockchain/governance.py` schedules and executes against a real
    TimelockController. Any disclosure asserting the platform has no timelock
    executor is false, however reasonable it sounds.
    """
    svc = GovernanceService({})
    record = await svc.queue_timelock(await _a_real_proposal(svc))

    lowered = record["disclosure"].lower()
    for false_claim in ("no timelock executor", "there is no executor",
                        "nothing executes a timelock"):
        assert false_claim not in lowered, (
            f"the disclosure asserts {false_claim!r}, which is FALSE — see "
            "runtime/blockchain/governance.py"
        )


def test_the_on_chain_executor_this_disclosure_refers_to_actually_exists():
    """GUARD THE GUARD, inverted. The narrowed disclosure names a file and
    claims a real executor lives there. If that stops being true the disclosure
    becomes wrong in the other direction, so the reference is verified rather
    than trusted."""
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parent.parent
        / "runtime" / "blockchain" / "governance.py"
    ).read_text()

    assert "timelock.functions.execute(" in source
    assert "timelock.functions.schedule(" in source


async def test_queue_timelock_still_refuses_to_claim_it_queued_anything():
    """The narrowing must not soften the refusal itself."""
    svc = GovernanceService({})
    record = await svc.queue_timelock(await _a_real_proposal(svc))

    assert record["status"] == "recorded_unqueued"
    assert record["executed"] is False
    assert record["settled"] is False


# ── Finding 5: the doctrine applied to my own refusals ───────────────────


@pytest.mark.parametrize("action", ["multisig_approve", "snapshot_vote"])
def test_a_method_that_always_refuses_is_not_advertised_as_available(action):
    """Both raise NotImplementedError unconditionally. Advertising them as
    available was the five-doors doctrine written into the catalog and then not
    walked in the same commit."""
    from runtime.capabilities import catalog

    cap = catalog.get_by_id(action)
    assert cap is not None, f"{action} should still be catalogued (it is routed)"
    assert cap["available"] is False, (
        f"{action} raises NotImplementedError on every call but advertises "
        "available=True"
    )


@pytest.mark.parametrize("action", ["multisig_approve", "snapshot_vote"])
async def test_but_it_is_still_routed_and_answers_honestly(action):
    """DELIBERATE DIFFERENCE FROM treasury_transfer, which was removed from
    routing entirely. These are intended to exist, so an honest 501 carrying a
    lifting condition beats "unknown action"."""
    import json

    from runtime.blockchain.services.service_dispatcher import ACTION_MAP, ServiceDispatcher

    assert action in ACTION_MAP
    params = ({"multisig_id": "m1", "signer": "0xa"} if action == "multisig_approve"
              else {"proposal_id": "p1", "voter": "0xa", "choice": "yes"})
    envelope = json.loads(await ServiceDispatcher({}).execute(action=action, params=params))

    assert envelope["error_category"] == "not_implemented"


def test_the_registry_total_matches_what_it_advertises():
    """Finding 6. A stale total is how the next reader inherits a wrong count —
    this engagement has now corrected seven of those."""
    import json
    import pathlib

    registry = json.loads(
        (pathlib.Path(__file__).resolve().parent.parent / "extensions" / "registry.json").read_text()
    )
    components = registry["components"] if isinstance(registry, dict) else registry
    advertised = sum(len(c.get("gateway_actions") or []) for c in components)

    assert registry["total_capabilities"] == advertised
