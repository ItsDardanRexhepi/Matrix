"""CLUSTER B — four methods that reported an authoritative act and kept no
record that could make it so, plus one store corruption fixed alongside.

THE DISCRIMINATOR WAS APPLIED, NOT INHERITED. Cluster A's members were
DEFECTIVE (category 6): real work happened and the vocabulary overstated it, so
they were repaired. Each of Cluster B's was tested separately by stripping the
outcome claim and asking what work remained:

    treasury_transfer  strip "transferred" -> a uuid and an echo.        NOTHING
    approve_multisig   strip "approved"    -> a uuid and an echo.        NOTHING
    snapshot_vote      strip "cast"        -> a uuid and an echo.        NOTHING
    migrate_members    strip "migrated": N -> a count of the input list. NOTHING
    queue_timelock     strip "queued"      -> a real record, a real delay,
                                              a real proposal lookup.    WORK

So four are fabrications and the fifth is not. `queue_timelock` is CATEGORY 6
and was repaired; the other four never did the thing they reported, and no
amount of rewording makes an unwritten record exist.

THE FOUR DID NOT GET THE SAME TREATMENT, because the right disposition depends
on what is already there to build against:

    approve_multisig  refuses  — `propose_multisig` writes a real record with
                                 signers/threshold/approvals. An honest version
                                 is buildable local work; the refusal names it.
    snapshot_vote     refuses  — Snapshot is an EXTERNAL hub. No client, no
                                 signer, no space. Nothing local could be the
                                 artifact, so the condition names externals.
    treasury_transfer disabled — kept as an honest error rather than removed,
                                 because the gated branch above it is real and
                                 the method is referenced across five surfaces.
    migrate_members   REMOVED  — no substrate, no callers, and the cheapest of
                                 the four to arm later. A refusal for something
                                 nothing calls is dead code with a comment.

THE REFUSAL'S EXCEPTION TYPE IS A CORRECTNESS PROPERTY, not a style choice, and
this was got wrong first. `raise ValueError` fell through the dispatcher's
generic `except Exception`, producing `error_category: "service_error"` with a
full `logger.exception` stack trace on every call — a deliberate unavailability
reported to the caller as the service malfunctioning. `NotImplementedError`
lands one clause earlier: `not_implemented`, `logger.warning`, no stack trace.
Both are refusals; only one is classified honestly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.blockchain.services.dao_management.service import DAOService
from runtime.blockchain.services.governance.service import GovernanceService
from runtime.blockchain.services.service_dispatcher import (
    ACTION_MAP,
    _STATE_MODIFYING_ACTIONS,
    ServiceDispatcher,
)

ROOT = Path(__file__).resolve().parents[1]


# ── treasury_transfer: FIVE doors, each asserted separately ──────────────
#
# The count was wrong twice. "The gateway route is deleted" was door 1 of 5;
# "available=False in the catalog" did not close door 3 at all. Each surface
# gets its own test so a future reopening names WHICH door.


def test_door_2_the_dispatcher_cannot_route_it():
    """ACTION_MAP is the choke point all four dispatch entry points share."""
    assert "treasury_transfer" not in ACTION_MAP
    assert "treasury_transfer" not in _STATE_MODIFYING_ACTIONS


def test_door_3_the_capability_catalog_does_not_carry_it():
    """`available=False` WAS NOT ENOUGH and that is the finding.

    `install_action_map` iterates every capability and never consults
    `available`, so a row marked unavailable is installed into ACTION_MAP
    exactly like an available one. The row had to be removed.
    """
    from runtime.capabilities import catalog

    assert catalog.get_by_id("treasury_transfer") is None


def test_door_4_the_ios_registry_does_not_advertise_it():
    """extensions/registry.json is served live and UserDefaults-cached by the
    client, so a stale advertisement outlives a server-side removal."""
    registry = json.loads((ROOT / "extensions" / "registry.json").read_text())
    components = registry["components"] if isinstance(registry, dict) else registry
    advertising = [
        c["id"] for c in components if "treasury_transfer" in (c.get("gateway_actions") or [])
    ]
    assert not advertising, f"still advertised by: {advertising}"


def test_door_5_the_model_is_not_taught_to_call_it():
    """THE WORST DOOR. The removed guide handed Trinity a line to speak —
    "Initiating a 50,000 USDC transfer from the Uniswap DAO treasury to
    0xrecipient. This will go through the governance approval flow." There is no
    governance approval flow and no transfer was ever initiated.

    Keywords are KEPT deliberately: the request must still MATCH so the answer
    is "not available" rather than a failure to recognise the request at all.
    """
    from runtime.chat.intent_actions import INTENT_ACTION_MAP

    guide = INTENT_ACTION_MAP["treasury_transfer"]
    assert guide.get("unavailable") is True
    assert "action_name" not in guide, "the model can still dispatch it"
    assert "NOT AVAILABLE" in guide["description"]
    assert guide["keywords"], "keywords dropped — the request now matches nothing"


def test_the_registry_capability_count_matches_what_is_advertised():
    """Removing an action from `gateway_actions` without decrementing
    `capability_count` leaves the client advertising a number it cannot list.
    19 of 20 components satisfy this; the invariant was found by measuring."""
    registry = json.loads((ROOT / "extensions" / "registry.json").read_text())
    components = registry["components"] if isinstance(registry, dict) else registry
    wrong = [
        (c["id"], len(c.get("gateway_actions") or []), c["capability_count"])
        for c in components
        if c.get("capability_count") is not None
        and len(c.get("gateway_actions") or []) != c["capability_count"]
    ]
    assert not wrong, f"capability_count != len(gateway_actions): {wrong}"


async def test_the_deployment_gate_above_it_still_answers_first():
    """SCOPE PIN. The gated branch is REAL and is not what was disabled — with
    no web3 the honest not-deployed refusal answers, as it always did."""
    result = await DAOService({}).treasury_transfer("dao_1", "0xr", 50_000.0, "USDC")

    assert result["status"] == "not_deployed"
    assert result["requested"]["amount"] == 50_000.0


async def test_it_moves_nothing_and_says_so():
    """The direct call is still honest for any caller holding the service."""
    svc = DAOService({})
    svc._web3.available = True
    svc._dao_factory_address = "0x" + "ab" * 20
    svc._web3.is_placeholder = lambda _addr: False

    result = await svc.treasury_transfer("dao_1", "0xr", 50_000.0, "USDC")

    assert result["status"] == "error"
    assert result["error_category"] == "not_implemented"
    assert result["value_moved"] is False
    assert result["settled"] is False

    # THE DISCLOSURE IS THE DELIVERABLE, so it is asserted rather than assumed.
    # An adversarial pass deleted this entire string and all 18 tests in this
    # file stayed green: the honest text was unpinned and the next refactor
    # would have dropped it silently. Content, not just the key — an empty
    # disclosure satisfies `"disclosure" in result`.
    assert "DISABLED" in result["disclosure"]
    assert "moving nothing and recording" in result["disclosure"]


# ── The two refusals ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "action,params",
    [
        ("multisig_approve", {"multisig_id": "m1", "signer": "0xa"}),
        ("snapshot_vote", {"proposal_id": "p1", "voter": "0xa", "choice": "yes"}),
    ],
)
async def test_a_refusal_is_classified_as_unavailable_not_as_a_malfunction(action, params):
    """THE EXCEPTION TYPE IS LOAD-BEARING — this is the test that would have
    caught my own first attempt. `ValueError` reached the dispatcher's generic
    handler and came back `service_error` + `degraded` with a stack trace: a
    deliberate refusal reported as the service breaking. A caller cannot tell
    "this will never work" from "try again later" out of that.
    """
    envelope = json.loads(await ServiceDispatcher({}).execute(action=action, params=params))

    assert envelope["status"] == "error"
    assert envelope["error_category"] == "not_implemented", (
        f"a deliberate refusal is being reported as {envelope['error_category']!r}"
    )


@pytest.mark.parametrize(
    "method,params,must_mention",
    [
        ("approve_multisig", {"multisig_id": "m1", "signer": "0xa"}, ("threshold", "approvals")),
        ("snapshot_vote", {"proposal_id": "p1", "voter": "0xa", "choice": "yes"}, ("hub", "signature")),
    ],
)
async def test_each_refusal_names_what_would_lift_it(method, params, must_mention):
    """A refusal that does not say what an honest implementation requires is a
    dead end. The two conditions DIFFER because the substrates differ: one is
    buildable local work, the other needs an external hub this platform has no
    client for."""
    with pytest.raises(NotImplementedError) as exc:
        await getattr(GovernanceService({}), method)(**params)

    msg = str(exc.value).lower()
    for token in must_mention:
        assert token in msg, f"{method} refusal does not mention {token!r}: {msg}"


async def test_neither_refusal_leaves_a_record_behind():
    """The point of the refusal is that nothing is written. A refusal that
    still stored something would be the original defect with an exception."""
    svc = GovernanceService({})
    before = {k: len(v) for k, v in vars(svc).items() if isinstance(v, (dict, list))}

    for method, params in (
        ("approve_multisig", {"multisig_id": "m1", "signer": "0xa"}),
        ("snapshot_vote", {"proposal_id": "p1", "voter": "0xa", "choice": "yes"}),
    ):
        with pytest.raises(NotImplementedError):
            await getattr(svc, method)(**params)

    after = {k: len(v) for k, v in vars(svc).items() if isinstance(v, (dict, list))}
    assert before == after


# ── migrate_members: removed rather than refused ─────────────────────────


def test_migrate_members_is_gone_rather_than_refusing():
    """REMOVAL, not a refusal, and the reason is stated so a future reader does
    not "restore" it. It had no substrate to record into and NO CALLERS — not
    in ACTION_MAP, not in the catalog, not routed. A refusal stub for something
    nothing calls is dead code carrying a comment."""
    from runtime.blockchain.services.dao_management.conversion_wizard import ConversionWizard

    assert not hasattr(ConversionWizard, "migrate_members")
    assert "migrate_members" not in ACTION_MAP


# ── queue_timelock: category 6, repaired — and a store corruption with it ──


async def test_queue_timelock_does_not_claim_to_have_queued_anything():
    """Nothing in this repo executes a timelock, so `executable_at` was a date
    on which nothing would happen. Recorded, not queued."""
    svc = GovernanceService({})
    p = await svc.create_proposal("0xp", "T", "d", "one_person_one_vote", ["yes", "no"])

    record = await svc.queue_timelock(p["proposal_id"], delay_seconds=3600)

    assert record["status"] == "recorded_unqueued"
    assert record["executed"] is False
    assert record["settled"] is False

    # THIS ASSERTION WAS PINNING A FALSE CLAIM. It required the disclosure to
    # say "no timelock executor" — which was untrue: runtime/blockchain/
    # governance.py schedules and executes against a real TimelockController.
    # Adjudicated before changing (the standing rule): this was not a fixture
    # and not correct behaviour being protected, it was a test written to match
    # an unverified sentence. Inverted to the narrow, grepped claim.
    assert "nothing reads this record" in record["disclosure"].lower()
    assert "runtime/blockchain/governance.py" in record["disclosure"]


async def test_the_queued_proposals_status_is_untouched_and_the_record_says_so():
    """It never looked the proposal up, let alone advanced it. The record now
    discloses that rather than implying otherwise."""
    svc = GovernanceService({})
    p = await svc.create_proposal("0xp", "T", "d", "one_person_one_vote", ["yes", "no"])
    pid = p["proposal_id"]
    before = svc._proposals[pid]["status"]

    await svc.queue_timelock(pid)

    assert svc._proposals[pid]["status"] == before


async def test_the_timelock_record_no_longer_pollutes_the_proposal_store():
    """THE SECOND DEFECT, fixed with the first because removing only the claim
    would have left listing broken.

    The record went into `self._proposals` under a `_timelock_` key. Every
    reader of that store assumes its values are proposals, so `list_proposals()`
    raised `KeyError: 'title'` once any timelock existed. The pollution is the
    STORE CHOICE, not the claim — a fabrication that also broke a real read.
    """
    svc = GovernanceService({})
    p = await svc.create_proposal("0xp", "T", "d", "one_person_one_vote", ["yes", "no"])

    record = await svc.queue_timelock(p["proposal_id"])

    assert record["id"] in svc._timelocks
    assert record["id"] not in svc._proposals
    assert not [k for k in svc._proposals if k.startswith("tl_") or "timelock" in k]

    listed = await svc.list_proposals()
    assert len(listed) == 1
    assert listed[0]["proposal_id"] == p["proposal_id"]


async def test_the_corrupting_shape_would_still_break_listing():
    """PROOF THE MECHANISM IS REAL, not just that today's code avoids it.

    This reproduces the old shape directly: a non-proposal value in
    `_proposals` still breaks `list_proposals`. So the fix is the store choice,
    and a future writer putting anything else in there reintroduces the bug —
    this test says so out loud rather than leaving it to be rediscovered.
    """
    svc = GovernanceService({})
    svc._proposals["_timelock_x"] = {"id": "_timelock_x", "status": "queued"}

    with pytest.raises(KeyError):
        await svc.list_proposals()


# ── Condition-pin: what was deliberately NOT removed ─────────────────────


def test_the_morpheus_risk_classification_is_retained():
    """INVERTED PIN. `morpheus_triggers` keeps `treasury_transfer ->
    governance`. It is a risk CLASSIFIER, not a caller-facing surface: it
    advertises nothing and can make nothing reachable, so it is not a sixth
    door. Keeping it means a future real implementation inherits the guard it
    should have. A "delete dead entries" cleanup must not take it."""
    from runtime.protocols.morpheus_triggers import _ACTION_CATEGORY_MAP

    assert _ACTION_CATEGORY_MAP.get("treasury_transfer") == "governance"
