"""NEW-61 — the defi exotics cull (domain 5, commit 2).

Ten fabricated methods removed from DeFiService. Every one had the same body:
behind a deployment gate, mint a uuid, set a hardcoded success status, write
the dict into the LOAN store, return it. No external call, no chain
interaction, no state-dependent arithmetic.

THE PLAN SAID THIRTEEN; THE CODE SAYS TEN. The count was re-derived by reading
the service rather than trusting the census number, and an independent AST
sweep confirmed the partition is exact: in DeFiService the ten are precisely
the methods with zero await expressions that mint a uuid and write to
_loan_manager._loans. No eleventh, and none of the ten does real work.

THEY WERE NOT INERT — they were ARMED-ON-DEPLOYMENT. Undeployed (today) all
ten return honest not_deployed responses, which is what made them look
harmless. Configure a lending-pool address and the same code silently returns
fabricated successes, with no further change: a $100k flash_loan reporting
fee 90.0 on a loan that was never made. This is the mirror of the
dead-safety-machinery rule: dead FABRICATION machinery becomes live
fabrication the moment config lands.

PER-METHOD TWIN CHECK (whole service layer, bodies not names, every absence
adversarially refuted by an independent agent that was told to find a twin):

  twin-path NONE, removed:
    flash_loan, yield_optimize, perp_trade, options_trade, synthetic_asset,
    leverage_position, vault_deposit

  twin-path REAL, fabrication removed, real capability preserved:
    liquidity_provide -> dex/service.py:217 -> dex/pools.py:151
    liquidity_remove  -> dex/service.py:265 -> dex/pools.py:228
        A real constant-product AMM. Already registered as the actions
        add_liquidity / remove_liquidity, so these two were DUPLICATE action
        names shadowing a real capability. Nothing to delegate: the real
        actions are untouched.
    collateral_manage -> defi/collateral.py:65 / :109
        CollateralManager.deposit / withdraw, real, and reached through
        DeFiService.deposit_collateral / withdraw_collateral — which were
        exposed on NO surface while the fabrication was exposed on all of
        them. Repointed rather than deleted (see below).

ONE CLAIMED TWIN REJECTED. An analyst returned vault_deposit ->
restaking/service.py:370 (restake_karak) as a real twin, on the strength of a
shared ERC-4626-style _VAULT_DEPOSIT_ABI. Rejected: it is a protocol-specific
Karak/Symbiotic restake with no vault selector — you cannot deposit into an
arbitrary yield vault through it — and its own docstring flags the ABI as
UNVERIFIED for that deployment. A matching interface shape is not an
equivalent economic operation. Accepting it would have repeated the
publish_mirror_post error: calling an adjacent real thing a twin.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from runtime.blockchain.services.defi.service import DeFiService

REPO = Path(__file__).resolve().parent.parent

REMOVED = [
    "flash_loan",
    "yield_optimize",
    "liquidity_provide",
    "liquidity_remove",
    "perp_trade",
    "options_trade",
    "synthetic_asset",
    "vault_deposit",
    "leverage_position",
    "collateral_manage",
]


# ── The methods are gone ───────────────────────────────────────────────────


@pytest.mark.parametrize("name", REMOVED)
def test_the_fabricated_method_no_longer_exists(name):
    assert not hasattr(DeFiService, name), (
        f"DeFiService.{name} is back — it fabricated a success record without "
        "performing the operation"
    )


def test_no_surviving_method_matches_the_fabrication_shape():
    """The shape, not the names — so a NEW fabrication of the same kind fails
    this test even though its name is not on the removed list."""
    import ast

    src = (REPO / "runtime/blockchain/services/defi/service.py").read_text()
    tree = ast.parse(src)
    cls = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "DeFiService"
    )

    offenders = []
    for fn in cls.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body_src = ast.dump(fn)
        mints_uuid = "uuid" in body_src
        writes_loan_store = "_loans" in body_src
        has_await = any(isinstance(n, ast.Await) for n in ast.walk(fn))
        if mints_uuid and writes_loan_store and not has_await:
            offenders.append(fn.name)

    assert offenders == [], (
        f"methods matching the fabrication shape (mint uuid + write loan "
        f"store + no await): {offenders}"
    )


# ── Gone from every caller-facing surface ─────────────────────────────────


@pytest.mark.parametrize("name", REMOVED)
def test_action_is_not_dispatchable(name):
    """SURFACE 1 — ACTION_MAP is what actually resolves a dispatch."""
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP

    assert name not in ACTION_MAP, f"{name} is still dispatchable"


@pytest.mark.parametrize("name", REMOVED)
def test_action_is_not_in_the_state_modifying_or_feed_tables(name):
    from runtime.blockchain.services.service_dispatcher import (
        ACTION_TO_FEED_EVENT,
        _STATE_MODIFYING_ACTIONS,
    )

    assert name not in _STATE_MODIFYING_ACTIONS
    assert name not in ACTION_TO_FEED_EVENT, (
        f"{name} still emits a feed event — a public claim that an operation "
        "happened, for an operation that cannot happen"
    )


@pytest.mark.parametrize("name", REMOVED)
def test_action_is_not_in_the_capability_catalog(name):
    from runtime.capabilities.catalog import CAPABILITIES

    ids = {c["id"] for c in CAPABILITIES}
    assert name not in ids, f"{name} is still advertised in the catalog"


@pytest.mark.parametrize("name", REMOVED)
def test_action_is_not_in_the_served_extension_registry(name):
    """The registry json is served live and cached by the iOS client, so a
    stale entry keeps advertising the capability after the code is gone."""
    reg = json.loads((REPO / "extensions/registry.json").read_text())
    for comp in reg["components"]:
        assert name not in comp.get("gateway_actions", []), (
            f"{name} still advertised by component {comp.get('id')}"
        )


@pytest.mark.parametrize("name", REMOVED)
def test_action_has_no_intent_description(name):
    """SURFACE 3 — the intent table was the ONLY description of four of these
    actions, so it is where a removed capability most easily survives."""
    from runtime.chat.intent_actions import INTENT_ACTION_MAP

    assert name not in INTENT_ACTION_MAP, (
        f"{name} still has an intent description — Trinity would still "
        "construct calls for it"
    )


# ── Both route registration tables (the domain-4 trap) ────────────────────


REMOVED_ROUTES = [
    "/api/v1/defi/flash-loan/execute",
    "/api/v1/defi/vault/deposit",
    "/api/v1/defi/liquidity/provide",
    "/api/v1/defi/perp/trade",
    "/api/v1/defi/collateral/manage",
]


@pytest.mark.parametrize("path", REMOVED_ROUTES)
def test_route_is_gone_from_both_registration_tables(path):
    """Domain 4 removed handlers from the add_post table only and left
    dangling references in the second (tuple-spec) table, which crashed the
    router at construction. Assert the path is absent from the whole file, so
    neither table can retain it."""
    src = (REPO / "gateway/service_routes.py").read_text()
    live = [
        ln for ln in src.splitlines()
        if path in ln and not ln.strip().startswith("#")
    ]
    assert live == [], f"{path} still registered: {live}"


def test_no_dangling_handler_references_remain():
    """The failure mode that crashed the router: a registration table naming
    a handler that no longer exists."""
    src = (REPO / "gateway/service_routes.py").read_text()
    for handler in (
        "_handle_flash_loan",
        "_handle_vault_deposit",
        "_handle_liquidity_provide",
        "_handle_perp_trade",
        "_handle_collateral_manage",
    ):
        live = [
            ln for ln in src.splitlines()
            if handler in ln and not ln.strip().startswith("#")
        ]
        assert live == [], f"dangling reference to {handler}: {live}"


def test_the_route_module_still_constructs():
    """Presence of a definition is not execution — import and build the router
    to prove the removal did not break construction."""
    import importlib

    mod = importlib.import_module("gateway.service_routes")
    assert mod is not None


# ── The real capabilities survived ────────────────────────────────────────


def test_the_real_amm_actions_are_untouched():
    """liquidity_provide/remove were duplicate names over this real twin.
    Removing the duplicates must not touch the real capability."""
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP

    assert ACTION_MAP["add_liquidity"] == ("dex", "add_liquidity")
    assert ACTION_MAP["remove_liquidity"] == ("dex", "remove_liquidity")

    from runtime.blockchain.services.dex.pools import LiquidityPoolManager

    assert hasattr(LiquidityPoolManager, "add_liquidity")
    assert hasattr(LiquidityPoolManager, "remove_liquidity")


def test_the_repoint_was_reversed_by_new_64():
    """THE REPOINT WAS WRONG AND IS GONE.

    This test previously asserted that deposit_collateral /
    withdraw_collateral / get_health_factor were registered in ACTION_MAP,
    replacing the fabricated collateral_manage. NEW-64 reversed that: the twin
    is real as COMPUTATION but false as CUSTODY (an in-process dict — no
    escrow, no chain, no persistence), and registering it also enrolled it in
    _STATE_MODIFYING_ACTIONS, which mints an attestation and publishes a
    public feed event.

    Inverted rather than deleted, so the reversal is visible at the exact spot
    that once asserted the opposite. Full coverage lives in
    tests/test_collateral_actions_unexposed.py.
    """
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP

    for action in ("deposit_collateral", "withdraw_collateral",
                   "get_health_factor"):
        assert action not in ACTION_MAP, (
            f"{action} is registered again — see the NEW-64 lifting condition"
        )
        # the METHOD survives; only the public surface is withdrawn
        assert hasattr(DeFiService, action)


async def test_the_repointed_collateral_actions_actually_work():
    """Positive proof, not absence: dispatch-shaped calls do real work.

    A delegation test must assert the delegate DID something, not merely that
    the fabrication is gone.
    """
    svc = DeFiService({"defi": {"fallback_prices": {"ETH": 2000.0}}})

    deposited = await svc.deposit_collateral("alice", "ETH", 5)
    assert deposited["status"] == "deposited"
    assert deposited["new_balance"] == 5

    health = await svc.get_health_factor("alice")
    assert health["total_collateral_usd"] == 10000.0, (
        "the repointed action returned no real valuation"
    )

    withdrawn = await svc.withdraw_collateral("alice", "ETH", 2)
    assert withdrawn["remaining_balance"] == 3, (
        "the repointed withdrawal did not move the real ledger"
    )


def test_the_repointed_withdrawal_still_carries_the_health_check():
    """The capability being exposed is the FIXED one from commit 1, not a
    bypass around it."""
    src = inspect.getsource(DeFiService.withdraw_collateral)
    assert "_collateral_manager.withdraw" in src, (
        "withdraw_collateral no longer routes through CollateralManager, "
        "which is where the health-factor guard lives"
    )


# ── The risk classifications were deliberately kept ───────────────────────


def test_the_morpheus_risk_classifications_are_retained():
    """CONDITION-PIN, inverted: this asserts something was deliberately NOT
    removed, so a future 'delete dead entries' cleanup cannot silently drop a
    safety classification.

    morpheus_triggers is a risk classifier, not a caller-facing surface — it
    advertises nothing and cannot make an action reachable. Keeping the
    classifications means a future real implementation inherits the guard it
    should have had. If any of these operations is genuinely implemented, this
    test should stay green, not be deleted.
    """
    from runtime.protocols.morpheus_triggers import (
        _ACTION_CATEGORY_MAP,
        _IRREVERSIBLE_ACTIONS,
    )

    for name in ("flash_loan", "leverage_position", "perp_trade"):
        assert name in _IRREVERSIBLE_ACTIONS, (
            f"{name} lost its irreversible-action classification"
        )
    for name in ("flash_loan", "yield_optimize", "perp_trade", "options_trade"):
        assert _ACTION_CATEGORY_MAP.get(name) == "defi"


def test_the_governance_flash_loan_detector_is_untouched():
    """anti_manipulation flags 'flash_loan_suspected' when a voter's weight
    exceeds their snapshot balance. It is a DIFFERENT concept that merely
    shares a word with the removed action — a grep-hit, not a reference. It
    must survive the cull."""
    src = (
        REPO / "runtime/blockchain/services/governance/anti_manipulation.py"
    ).read_text()
    assert "flash_loan_suspected" in src, (
        "the governance flash-loan-attack detector was removed by name "
        "collision with the unrelated defi action"
    )
