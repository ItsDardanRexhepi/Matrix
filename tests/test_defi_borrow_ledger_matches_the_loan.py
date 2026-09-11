"""Two ledgers of one debt, and the safety check read the wrong one.

DOMAIN 16-C. The most consequential finding in this domain, and the one that
needs NO malformed input at all — no NaN, no overflow, no crafted request. An
ordinary partial repayment, made after ordinary interest accrual.

THE MECHANISM, driven end to end:

    create_loan(0xA, ETH 10.0, USDC 1000.0)
      -> collateral ledger: {'ETH': 10.0}
      -> borrow ledger:     {'USDC': 1000.0}      <- records PRINCIPAL
    ... one year of interest accrues -> 20.19 USDC
    repay_loan(loan_id, 1000.0)                   <- an ordinary partial payment
      -> loan:   ACTIVE, 20.19 still owed         (CORRECT — payment goes to
                                                   interest first, so principal
                                                   is not fully retired)
      -> ledger: max(0, 1000 - 1000) = 0          (WRONG — decremented by the
                                                   PAYMENT, not the principal)
      -> health: "no_borrows", factor Infinity, total_borrows_usd 0.0
      -> withdraw_collateral(0xA, ETH, 10.0) SUCCEEDS

    Result: the borrower holds 100% of their collateral back while still owing
    20.19 USDC. Fully unsecured debt, produced by arithmetic alone.

THE ROOT IS NOT THE SUBTRACTION. It is that the same debt was recorded in two
places, updated with two different quantities — `record_borrow` took the
PRINCIPAL, the repayment path passed the PAYMENT — and the control that decides
whether collateral may leave reads the one that can drift. Fixed by SETTING the
position from `repay_loan`'s own `remaining_principal` rather than computing a
delta: an assignment cannot drift from its source.

THE TERMINAL STATE WAS ALREADY KNOWN, BY A DIFFERENT ROUTE. `collateral.py`
records that NEW-55 closed a fail-open price path with exactly this ending: "a
0.0 price on the DEBT side drove total_borrows_usd to zero -> the 'no_borrows'
branch -> the 'inf' health factor -> withdraw's collateral-destruction path."
Same destination, reached by ordinary arithmetic instead of a bad price. Worth
stating plainly: **the `no_borrows` -> Infinity -> release-everything chain
converts ANY under-recording of debt into total collateral release.** That
fragility is registered separately; this file fixes one road into it, not the
junction itself.

ARMED BY DEPLOYMENT, and the enumeration that establishes it — per L.2, an
absence claim is settled by enumerating writers and reading their gate
conditions, never by sampling. `record_borrow` has EXACTLY ONE caller
(`service.py`, inside `create_loan`), and `create_loan`'s gate reads only
`self._web3.available` and whether the pool address is a placeholder — no
argument reaches it. So no borrow position can exist under the shipped config,
and this cannot fire until contracts are deployed. It needs no malformed input,
which makes it worse than 16-A on the day that happens.
"""

from __future__ import annotations

import time

import pytest

from runtime.blockchain.services.defi import DeFiService

CONFIG = {"defi": {"fallback_prices": {"ETH": 2000.0, "USDC": 1.0}}}


@pytest.fixture
def service(monkeypatch) -> DeFiService:
    """Deployed-install simulation.

    monkeypatch, NOT assignment: `Web3Manager.get_shared()` is a process-wide
    singleton and a direct write leaks into every later test in the run (L.3).
    """
    svc = DeFiService(CONFIG)
    monkeypatch.setattr(svc._web3, "available", True)
    monkeypatch.setattr(svc._web3, "is_placeholder", lambda _a: False)
    return svc


async def _aged_loan(svc: DeFiService, user: str = "0xA") -> str:
    loan = await svc.create_loan(user, "ETH", 10.0, "USDC", 1000.0)
    loan_id = loan["loan_id"]
    svc._loan_manager._loans[loan_id]["last_interest_update"] = (
        time.time() - 365 * 24 * 3600
    )
    await svc._loan_manager.get_loan(loan_id)
    return loan_id


# ── the load-bearing assertion ───────────────────────────────────────────


async def test_a_partial_repayment_does_not_zero_the_borrow_ledger(service):
    """THE DEFECT. Pre-fix the ledger read {'USDC': 0} while 20.19 was owed."""
    loan_id = await _aged_loan(service)

    await service.repay_loan(loan_id, 1000.0)

    loan = await service._loan_manager.get_loan(loan_id)
    still_owed = loan["borrow_amount"] + loan.get("accrued_interest", 0)
    recorded = service._collateral_manager._borrows["0xA"]["USDC"]

    assert still_owed > 0, "the fixture must leave a real balance outstanding"
    assert recorded > 0, "the borrow ledger says the debt is gone"
    assert recorded == pytest.approx(loan["borrow_amount"]), (
        "the ledger must equal the loan's own remaining principal"
    )


async def test_the_health_factor_does_not_report_no_borrows_while_debt_exists(service):
    """THE SURFACE THE CONTROL READS. `no_borrows` is not a cosmetic label — it
    is the branch that yields an infinite health factor."""
    loan_id = await _aged_loan(service)

    await service.repay_loan(loan_id, 1000.0)
    health = await service.get_health_factor("0xA")

    assert health["status"] != "no_borrows"
    assert health["total_borrows_usd"] > 0


async def test_collateral_cannot_be_fully_withdrawn_while_debt_remains(service):
    """THE MONEY IMPACT, asserted directly. Pre-fix this returned
    {"status": "withdrawn", "remaining_balance": 0.0} with 20.19 USDC still
    owed — the borrower recovered 100% of collateral on unsecured debt."""
    loan_id = await _aged_loan(service)
    await service.repay_loan(loan_id, 1000.0)

    with pytest.raises(ValueError) as exc:
        await service.withdraw_collateral("0xA", "ETH", 10.0)

    assert "health factor" in str(exc.value).lower()
    assert service._collateral_manager._balances["0xA"]["ETH"] == 10.0


# ── scope pins: the fix must not break repayment ─────────────────────────


async def test_a_full_repayment_still_clears_the_ledger_and_releases_collateral(service):
    """SCOPE PIN, and the one that matters most — an over-strict fix here would
    trap collateral forever, which is a worse failure than the one being fixed."""
    loan = await service.create_loan("0xB", "ETH", 10.0, "USDC", 1000.0)

    await service.repay_loan(loan["loan_id"], 1000.0)

    assert service._collateral_manager._borrows["0xB"]["USDC"] == 0.0
    result = await service.withdraw_collateral("0xB", "ETH", 10.0)
    assert result["status"] == "withdrawn"


async def test_a_small_repayment_reduces_the_ledger_proportionally(service):
    """The ledger must TRACK, not merely refuse to zero. A fix that pinned the
    position at its opening value would pass the assertions above while making
    repayment meaningless."""
    loan_id = await _aged_loan(service, "0xC")
    before = service._collateral_manager._borrows["0xC"]["USDC"]

    await service.repay_loan(loan_id, 520.19)

    after = service._collateral_manager._borrows["0xC"]["USDC"]
    loan = await service._loan_manager.get_loan(loan_id)

    assert after < before, "the ledger did not move on a real repayment"
    assert after == pytest.approx(loan["borrow_amount"])


async def test_the_position_is_set_from_the_loan_not_computed_by_delta(service):
    """THE STRUCTURAL PROPERTY, pinned. After ANY sequence of repayments the
    ledger must equal the loan's remaining principal exactly. A delta-based
    implementation can pass a single-repayment test and still drift over
    several; this asserts agreement after three."""
    loan_id = await _aged_loan(service, "0xD")

    for payment in (100.0, 250.5, 33.33):
        await service.repay_loan(loan_id, payment)
        loan = await service._loan_manager.get_loan(loan_id)
        recorded = service._collateral_manager._borrows["0xD"]["USDC"]
        assert recorded == pytest.approx(loan["borrow_amount"]), (
            f"ledgers diverged after a {payment} repayment: "
            f"loan={loan['borrow_amount']} ledger={recorded}"
        )


def test_the_delta_based_recorder_is_gone_not_merely_bypassed():
    """`record_repayment` was RENAMED, not left beside its replacement. Leaving
    the wrong one in place would be the `set_balance` / `migrate_members` shape:
    an unattended primitive one line from live, and the dangerous one carrying
    the friendlier name."""
    from runtime.blockchain.services.defi.collateral import CollateralManager

    assert not hasattr(CollateralManager, "record_repayment")
    assert hasattr(CollateralManager, "set_borrow_position")
