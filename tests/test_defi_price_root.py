"""NEW-55b/55c/59 — the defi price root fix (domain 5, commit 1).

The root: DeFiService.__init__ accepts oracle_gateway=None, but the only
production construction path is ServiceRegistry.get() -> cls(self._config),
one positional arg, so an oracle could never be injected. Every price fell
through to a config constant or hardcoded 1.0. 40 of 71 methods were
real-local-defective for this one reason — genuine arithmetic over a
fabricated input.

Three coupled fixes, all in this commit because splitting them re-opens the
collateral-destruction path:

  1. NEW-59 — oracle lazy resolution (the registry-DI-gap fix, shared shape
     with fundraising and dashboard).
  2. NEW-55b — CollateralManager._get_price FAILS CLOSED on a missing price.
     It was the fail-open half: it returned 0.0, which on the debt side drove
     total_borrows_usd to 0 -> "no_borrows" -> the "inf" health factor.
  3. NEW-55c — the health factor is returned as a FLOAT (was the string
     "inf"), and withdraw checks health on a SIMULATED balance BEFORE
     committing the debit. Together these remove the collateral-destruction
     path; fixing only (2) would MOVE the destruction to a new trigger (the
     fail-closed ValueError), which is why they ship together.

CONDITION-PIN: the stale-fallback hazard. A configured-but-wrong
fallback_prices entry can still silently price an origination. That is the
latent risk the disable ruling weighed; commit 1 does not eliminate it (a
configured value is indistinguishable from a correct one at read time), so a
test NAMES it as the known residual, the way a security disable names its
lifting condition.
"""

from __future__ import annotations

import inspect

import pytest

from runtime.blockchain.services.defi.collateral import CollateralManager
from runtime.blockchain.services.defi.service import DeFiService


# ── NEW-59: oracle is resolvable, not structurally None ────────────────────


def test_oracle_resolves_lazily_instead_of_staying_none():
    """Built the way the registry builds it — one positional arg."""
    svc = DeFiService({})
    assert svc._oracle is None, "precondition: no oracle injected at construction"

    resolved = svc._resolve_oracle()
    from runtime.blockchain.services.oracle_gateway import OracleGateway

    assert isinstance(resolved, OracleGateway), (
        "the oracle must resolve to a real gateway, not stay None — otherwise "
        "every price is a config constant or hardcoded 1.0"
    )


def test_the_collateral_manager_oracle_is_kept_in_lockstep():
    """The health-factor prices must come from the same live source as loans."""
    svc = DeFiService({})
    svc._resolve_oracle()
    from runtime.blockchain.services.oracle_gateway import OracleGateway

    assert isinstance(svc._collateral_manager._oracle, OracleGateway)


def test_collateral_manager_resolves_its_own_oracle_when_standalone():
    cm = CollateralManager({})
    assert cm._oracle is None
    from runtime.blockchain.services.oracle_gateway import OracleGateway

    assert isinstance(cm._resolve_oracle(), OracleGateway)


# ── NEW-55b: _get_price fails CLOSED, matching its sibling ─────────────────


async def test_get_price_raises_on_unknown_token_instead_of_returning_zero():
    """The fail-open 0.0 was the trigger of the collateral-destruction path."""
    cm = CollateralManager({})  # no fallback_prices, WETH unpriceable

    with pytest.raises(ValueError, match="No price available"):
        await cm._get_price("WETH")


async def test_get_price_still_returns_par_for_stablecoins():
    """A stablecoin at 1.0 is accurate, not fabricated — must not regress."""
    cm = CollateralManager({})
    assert await cm._get_price("USDC") == 1.0
    assert await cm._get_price("DAI") == 1.0


async def test_the_two_price_methods_now_agree_on_a_missing_price():
    """The fail-open/fail-closed DIVERGENCE was the root's sharpest expression.

    DeFiService._get_token_price already raised; CollateralManager._get_price
    returned 0.0. The same missing input handled two opposite ways in two
    files of one service, and only the fail-open one touched a money path.
    Both must now raise.
    """
    svc = DeFiService({})
    cm = CollateralManager({})

    with pytest.raises(ValueError):
        await svc._get_token_price("WETH")
    with pytest.raises(ValueError):
        await cm._get_price("WETH")


# ── NEW-55c: the health factor is a FLOAT; withdraw does not destroy ───────


async def test_health_factor_is_a_float_not_the_string_inf():
    cm = CollateralManager({"defi": {"fallback_prices": {"ETH": 2000.0}}})
    await cm.deposit("dave", "ETH", 10)  # no borrows -> the old "inf" case

    health = await cm._compute_health_factor("dave")

    assert isinstance(health["health_factor"], float), (
        "health_factor is a string again — withdraw compares it numerically "
        "and will raise TypeError, re-opening the destruction path"
    )
    assert health["health_factor"] == float("inf")
    # A human label lives in its own key, so no consumer special-cases a
    # string in the numeric field.
    assert health["health_factor_display"] == "∞"


async def test_safe_withdrawal_of_a_no_borrow_position_succeeds_and_debits_correctly():
    """The exact reproduction: deposit 10, withdraw 4 -> USED to leave 6 by
    DESTRUCTION (TypeError with the balance already debited). Now it leaves 6
    by a REAL withdrawal."""
    cm = CollateralManager({"defi": {"fallback_prices": {"ETH": 2000.0}}})
    await cm.deposit("dave", "ETH", 10)

    result = await cm.withdraw("dave", "ETH", 4)

    assert result["status"] == "withdrawn"
    assert result["remaining_balance"] == 6
    assert (await cm.get_balances("dave"))["ETH"] == 6


async def test_withdrawal_of_an_unpriceable_position_refuses_without_debiting():
    """The fail-closed price must not become a NEW destruction trigger.

    Before this commit, ANY exception from the health check left the balance
    debited (the except was a no-op that only looked like a revert). The
    fail-closed ValueError would have inherited that. The check now runs on a
    SIMULATED balance before the real debit, so a refusal leaves the ledger
    untouched.
    """
    cm = CollateralManager({})  # ETH unpriceable
    await cm.deposit("erin", "ETH", 10)

    with pytest.raises(ValueError):
        await cm.withdraw("erin", "ETH", 4)

    assert (await cm.get_balances("erin"))["ETH"] == 10, (
        "collateral was debited on a refused withdrawal — the destruction "
        "path moved to the fail-closed trigger instead of being removed"
    )


async def test_an_unsafe_withdrawal_is_still_blocked_with_the_ledger_intact():
    """The real guard must still fire — and leave the balance untouched."""
    cm = CollateralManager({"defi": {"fallback_prices": {"ETH": 2000.0}}})
    await cm.deposit("frank", "ETH", 1)
    cm.record_borrow("frank", "USDC", 1500)  # $2000 collateral vs $1500 debt

    with pytest.raises(ValueError, match="health factor"):
        await cm.withdraw("frank", "ETH", 0.9)  # would leave $200 vs $1500

    assert (await cm.get_balances("frank"))["ETH"] == 1


async def test_the_health_check_runs_on_a_simulation_not_the_real_ledger():
    """Structural guarantee behind the no-destruction property.

    First written as "refuse, then assert the ledger is intact" — which PASSED
    at pre-fix HEAD, because that particular case took the old explicit-revert
    branch. It asserted a true thing without looking at the mechanism, so it
    could not have caught the defect. Rewritten to assert the mechanism
    itself: _compute_health_factor must be able to evaluate a HYPOTHETICAL
    position without touching _balances. Pre-fix the parameter does not exist,
    so this fails there.
    """
    cm = CollateralManager({"defi": {"fallback_prices": {"ETH": 2000.0}}})
    await cm.deposit("gina", "ETH", 10)
    ledger_before = {u: dict(b) for u, b in cm._balances.items()}

    # Evaluate a position the ledger does NOT hold.
    hypothetical = await cm._compute_health_factor(
        "gina", balances_override={"gina": {"ETH": 1}}
    )

    assert hypothetical["total_collateral_usd"] == 2000.0, (
        "the override was ignored — the health check read the real balances, "
        "so a pre-check cannot be done without mutating the ledger"
    )
    assert cm._balances == ledger_before, "evaluating a hypothesis mutated the ledger"

    # And the real ledger still reads as itself.
    real = await cm._compute_health_factor("gina")
    assert real["total_collateral_usd"] == 20000.0


async def test_a_refused_withdrawal_leaves_the_ledger_intact():
    """The user-visible half of the same property (a regression guard: this
    case took the explicit-revert branch pre-fix, so it passes on both sides —
    it protects the behaviour, it does not prove the fix)."""
    cm = CollateralManager({"defi": {"fallback_prices": {"ETH": 2000.0}}})
    await cm.deposit("gina", "ETH", 1)
    cm.record_borrow("gina", "USDC", 1500)
    before = dict(cm._balances["gina"])

    with pytest.raises(ValueError):
        await cm.withdraw("gina", "ETH", 0.9)

    assert cm._balances["gina"] == before


# ── CONDITION-PIN: the stale-fallback hazard, named as the residual ────────


async def test_a_configured_fallback_is_still_trusted_the_known_residual():
    """CONDITION-PIN, not a passing feature.

    Commit 1 resolves the oracle and fails closed on an UNKNOWN price. It does
    NOT — and cannot at read time — tell a correct configured fallback from a
    stale one. This test documents that residual so a future reader knows the
    root fix did not close it: eliminating the stale-fallback path requires
    either removing fallback_prices as an origination price source, or marking
    fallbacks as non-authoritative for money decisions. That is the lifting
    condition for NEW-55's latent-mispricing note.

    If this behaviour ever changes — a fallback stops being trusted for
    valuation — this test should be updated to assert the stronger guarantee,
    not deleted.
    """
    cm = CollateralManager({"defi": {"fallback_prices": {"WETH": 9999.0}}})

    # A configured fallback is used verbatim, however wrong.
    assert await cm._get_price("WETH") == 9999.0, (
        "the stale-fallback residual changed — if fallbacks are no longer "
        "trusted for valuation, tighten this test to assert that"
    )


def test_the_registry_di_gap_is_shared_by_three_services():
    """NEW-59 is systemic: the same construction shape, three services.

    Named so the template travels. defi is fixed here; fundraising and
    dashboard carry the identical gap for their own future fixes.
    """
    import runtime.blockchain.services.fundraising.service as fundraising
    import runtime.blockchain.services.dashboard.service as dashboard

    for mod, cls_name, dep in [
        (fundraising, "FundraisingService", "oracle_service"),
        (dashboard, "DashboardService", "services"),
    ]:
        cls = getattr(mod, cls_name)
        params = inspect.signature(cls.__init__).parameters
        assert dep in params, f"{cls_name} no longer declares {dep}"
        assert params[dep].default is None, (
            f"{cls_name}.{dep} — the registry passes only config, so this "
            "optional dependency is still never supplied (NEW-59)"
        )
