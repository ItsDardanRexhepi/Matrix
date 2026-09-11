"""NEW-64 — the collateral actions come back off every surface.

This reverses part of NEW-61 (commit 13e5e17). NEW-61 removed the fabricated
collateral_manage and, finding its twin real, registered
deposit_collateral / withdraw_collateral / get_health_factor in its place.
That registration was wrong.

THE ERROR: "real" is not one property. CollateralManager does genuine
arithmetic over prior state — real AS COMPUTATION — but it increments a
Python dict: no escrow, no chain interaction, no persistence across a
restart. That makes it false AS CUSTODY. The bar used to justify the
registration ("not a uuid-minting stub") was the NEW-61 culling bar. It is
the right standard for judging a calculation and the wrong standard for an
operation whose whole claim is that it holds your money.

THE AGGRAVATING FACTOR, and why this shipped ahead of everything else:
deposit_collateral / withdraw_collateral were also placed in
_STATE_MODIFYING_ACTIONS, and membership in that set is exactly what makes
ServiceDispatcher.execute() call _attest_action() and then fire-and-forget
publish to the public social feed. So a dict increment minted an attestation
and announced custody publicly — strictly worse than the fabrication it
replaced, which at least did not attest.

CONTEXT that makes the exposure sharper: every OTHER lending entry point on
this service is deployment-gated — create_loan (service.py) and its sole
writer LoanManager.create_loan (loans.py) both return not_deployed with the
shipped config. These three carried no gate at all, so they were the only
live lending surface in the service.

The methods survive as internal helpers (create_loan uses the manager
directly). They are pinned unexposed here, with the lifting condition
recorded beside ACTION_MAP.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

UNEXPOSED = ["deposit_collateral", "withdraw_collateral", "get_health_factor"]


# ── Off every surface ─────────────────────────────────────────────────────


@pytest.mark.parametrize("name", UNEXPOSED)
def test_action_is_not_dispatchable(name):
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP

    assert name not in ACTION_MAP, (
        f"{name} is dispatchable again — it reports custody of value that is "
        "only a dict entry"
    )


@pytest.mark.parametrize("name", UNEXPOSED)
def test_action_is_not_in_the_capability_catalog(name):
    from runtime.capabilities.catalog import CAPABILITIES

    assert name not in {c["id"] for c in CAPABILITIES}


@pytest.mark.parametrize("name", UNEXPOSED)
def test_action_is_not_in_the_served_extension_registry(name):
    reg = json.loads((REPO / "extensions/registry.json").read_text())
    for comp in reg["components"]:
        assert name not in comp.get("gateway_actions", [])


@pytest.mark.parametrize("name", UNEXPOSED)
def test_action_is_not_offered_to_the_model(name):
    """The tool-schema enum is derived from ACTION_MAP.keys(), so this is a
    consequence of the first test — asserted separately because it is the
    surface that actually puts the action in front of a user."""
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    schema = json.dumps(ServiceDispatcher.schema)
    assert f'"{name}"' not in schema, (
        f"{name} is still advertised to the model in the tool schema"
    )


# ── The attestation + feed pair cannot fire (the ruling's requirement) ────


@pytest.mark.parametrize("name", ["deposit_collateral", "withdraw_collateral"])
def test_action_cannot_mint_an_attestation_or_feed_event(name):
    """Assert the MECHANISM, not merely the absence of the action.

    ServiceDispatcher.execute() attests and publishes iff the action is in
    _STATE_MODIFYING_ACTIONS. Removing an action from ACTION_MAP while leaving
    it in the set that grants it authority is the same half-removal that left
    dangling handlers in domain 4 — so this is checked on its own.
    """
    from runtime.blockchain.services.service_dispatcher import (
        _STATE_MODIFYING_ACTIONS,
    )

    assert name not in _STATE_MODIFYING_ACTIONS, (
        f"{name} still grants attestation + public feed publication for an "
        "unescrowed dict increment"
    )


async def test_dispatching_the_action_is_refused_end_to_end():
    """Positive proof through the real dispatcher: the action does not
    execute, and the refusal is an unknown-action error rather than a
    success envelope."""
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    dispatcher = ServiceDispatcher(config={})
    raw = await dispatcher.execute(
        action="deposit_collateral",
        params={"user": "mallory", "token": "ETH", "amount": 5},
    )
    payload = json.loads(raw) if isinstance(raw, str) else raw

    assert payload.get("status") != "ok", (
        "deposit_collateral still returns a success envelope"
    )
    assert "deposit_collateral" not in payload.get("available_actions", [])


async def test_no_feed_event_is_emitted_for_a_collateral_call():
    """The feed publish is fire-and-forget, and the first version of this test
    could not see it.

    execute() publishes via asyncio.create_task(...), so the task is SCHEDULED
    but has not run when execute() returns. Asserting immediately therefore
    passed at pre-fix HEAD — where the publish was live — because the test was
    looking before the thing it tests had happened. Caught by the mandatory
    pre-fix run; it is the third time in this engagement that a
    correctly-shaped test aimed slightly off its subject.

    The fix is to drain the loop so any scheduled publish actually runs, and
    to prove the harness CAN observe a publish (positive control) before
    asserting that the collateral call produces none.
    """
    import asyncio

    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    ingested: list[dict] = []

    class _RecordingFeed:
        async def ingest(self, **kwargs):
            ingested.append(kwargs)

    dispatcher = ServiceDispatcher(config={})
    dispatcher._feed_engine = _RecordingFeed()

    async def _drain():
        # let create_task-scheduled coroutines actually execute
        for _ in range(5):
            await asyncio.sleep(0)

    # ORDER MATTERS. The real assertion runs FIRST, against pristine module
    # state. An earlier version put the positive control first, and its
    # teardown popped the action from ACTION_MAP — which, at pre-fix HEAD,
    # MANUFACTURED the very condition under test, so the test passed on both
    # sides. A control that mutates shared state must not run before the
    # assertion it is controlling for.
    await dispatcher.execute(
        action="deposit_collateral",
        params={"user": "mallory", "token": "ETH", "amount": 5},
    )
    await _drain()

    assert ingested == [], (
        f"a collateral call published to the public feed: {ingested}"
    )

    # POSITIVE CONTROL, run afterwards — the exact counterfactual. Register
    # the action back and confirm the harness DOES observe the publish, so
    # that the assertion above cannot be satisfied merely by a harness
    # incapable of seeing ingestion. (Other candidate control actions all
    # error under an empty config before execute() reaches the publish
    # branch, so they would prove nothing.)
    from runtime.blockchain.services import service_dispatcher as _sd

    # _STATE_MODIFYING_ACTIONS is a frozenset — it cannot be mutated at
    # runtime, which is a small safety property worth keeping — so the
    # control rebinds the module attribute instead of adding to the set.
    _orig_map = dict(_sd.ACTION_MAP)
    _orig_state_modifying = _sd._STATE_MODIFYING_ACTIONS
    _sd.ACTION_MAP["deposit_collateral"] = ("defi", "deposit_collateral")
    _sd._STATE_MODIFYING_ACTIONS = frozenset(
        _orig_state_modifying | {"deposit_collateral"}
    )
    try:
        await dispatcher.execute(
            action="deposit_collateral",
            params={"user": "control", "token": "ETH", "amount": 1},
        )
        await _drain()
        assert ingested, (
            "the harness observed no feed publish even with the action "
            "registered — it cannot detect the thing under test, so the "
            "assertion above proved nothing"
        )
    finally:
        _sd.ACTION_MAP.clear()
        _sd.ACTION_MAP.update(_orig_map)
        _sd._STATE_MODIFYING_ACTIONS = _orig_state_modifying


# ── The methods survive as internal helpers, and lending still works ──────


@pytest.mark.parametrize("name", UNEXPOSED)
def test_the_method_still_exists_for_internal_use(name):
    """Unexposing is not deleting. create_loan needs the collateral ledger;
    removing the methods would break real lending logic."""
    from runtime.blockchain.services.defi.service import DeFiService

    assert hasattr(DeFiService, name)


async def test_internal_collateral_bookkeeping_still_functions():
    """Positive proof that unexposure did not break the internals."""
    from runtime.blockchain.services.defi.service import DeFiService

    svc = DeFiService({"defi": {"fallback_prices": {"ETH": 2000.0}}})
    await svc.deposit_collateral("internal", "ETH", 4)
    health = await svc.get_health_factor("internal")
    assert health["total_collateral_usd"] == 8000.0


def test_the_lifting_condition_is_recorded_where_it_would_be_undone():
    """A security removal states what would license lifting it, next to the
    table someone would edit to lift it."""
    src = (
        REPO / "runtime/blockchain/services/service_dispatcher.py"
    ).read_text()
    assert "LIFTING CONDITION" in src
    assert "NEW-62" in src, (
        "the lifting condition must name the ledger defect, not only the "
        "custody one — re-exposing after fixing custody alone would still "
        "expose an unsound collateral guard"
    )


# ── Regression guard: the gated lending path is untouched ────────────────


async def test_core_lending_is_still_gated_shut():
    """This commit must not disturb the double gate that keeps NEW-62
    unreachable. Both create_loan and its sole writer refuse."""
    from runtime.blockchain.services.defi.service import DeFiService

    svc = DeFiService({})
    result = await svc.create_loan("bob", "ETH", 10, "USDC", 10000)
    assert result.get("status") == "not_deployed"
    assert svc._loan_manager._loans == {}
