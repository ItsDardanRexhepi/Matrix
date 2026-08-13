"""This exchange cannot settle — so it must not act as though it can.

THE STRUCTURAL FACT, established by reading the constructor: `ExchangeContract`
takes only `config` and holds `_order_books`, `_orders`, `_trades`. It has **no
reference to the service's `_balances`**. The matching engine is therefore
incapable of transferring what it matches — not "not yet wired", but structurally
unable. And a grep across all five files for payment/settle/escrow/debit/credit
returns only the word "accredited". **There is no consideration leg anywhere in
this domain**, which is what forecloses delegating to one.

Three defects followed from that, all reproduced before the fix:

  13-A  `buy()` delivered and collected nothing — issuer 1000 -> 900, buyer
        0 -> 100, and the trade record asserted `total_value=1000.0`. Worse than
        the NEW-57 payment stubs: those moved nothing in either direction, so the
        lie was symmetric. Here ONE SIDE REALLY EXECUTES and persists.
  13-B  `sell()` reserved nothing — a holder of 100 placed 3 x 100 = 300
        committed with the balance never moving. Independent of settlement: an
        order book that lets a holder promise more than they hold is wrong on its
        own terms.
  13-C  `match_orders()` reported trades EXECUTED and orders "filled" while
        touching no balances at all.

COUNSEL-RELEVANT (M3): a recorded transfer of REGULATED instruments asserting a
price was paid, with no consideration anywhere in the codebase.

CROSS-DOMAIN: the dashboard reads `_balances` directly for
`portfolio["securities"]`, so an unpaid credit rendered as a user-facing holding —
13-A fed domain 12's portfolio surface rather than staying inside the exchange.

THE COMPLIANCE CONTROL IS REAL AND MUST SURVIVE EVERY FIX. The first attempt to
reproduce 13-A was blocked by "Receiver is not whitelisted" until credentials
were supplied. That is a working control on a regulated surface; the tests below
assert it is still enforced after the changes, so a later settlement fix cannot
route around it.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.securities_exchange.service import (
    SecuritiesExchangeService,
)

CREDS = {
    "accredited": True,
    "jurisdiction": "US",
    "kyc_verified": True,
    "aml_verified": True,
}


async def _service_with_listed_security(*investors: str):
    service = SecuritiesExchangeService({})
    security = await service.create_security(
        issuer="0xISSUER", security_type="equity", total_supply=1000,
        metadata={"name": "ACME"},
    )
    security_id = security.get("security_id") or security.get("id")
    await service.list_security(security_id, price=10.0)
    for who in ("0xISSUER", *investors):
        await service._compliance.whitelist_investor(security_id, who, CREDS)
    return service, security_id


# ── 13-A: no one-sided transfer ──────────────────────────────────────────


async def test_buy_refuses_rather_than_delivering_without_payment():
    service, security_id = await _service_with_listed_security("0xBUYER")

    with pytest.raises(NotImplementedError) as exc:
        await service.buy(security_id, "0xBUYER", 100)

    message = str(exc.value).lower()
    assert "settlement" in message
    assert "without collecting payment" in message


async def test_a_refused_buy_moves_no_securities():
    """THE ASSERTION AGAINST THE STORE. The defect was a persistent balance
    change; a refusal that still mutated would be the same bug with an exception
    attached."""
    service, security_id = await _service_with_listed_security("0xBUYER")

    with pytest.raises(NotImplementedError):
        await service.buy(security_id, "0xBUYER", 100)

    assert service._balances.get((security_id, "0xISSUER")) == 1000
    assert service._balances.get((security_id, "0xBUYER"), 0) == 0


async def test_the_compliance_gate_still_fires_before_anything_else():
    """THE POSITIVE CONTROL, asserted intact. A non-whitelisted receiver must
    still be rejected BY COMPLIANCE — not swallowed by the new refusal. If the
    refusal shadowed the gate, a later settlement fix would be built on a check
    that had silently stopped running."""
    service = SecuritiesExchangeService({})
    security = await service.create_security(
        issuer="0xISSUER", security_type="equity", total_supply=1000,
        metadata={"name": "ACME"},
    )
    security_id = security.get("security_id") or security.get("id")
    await service.list_security(security_id, price=10.0)

    with pytest.raises(ValueError) as exc:
        await service.buy(security_id, "0xNOT_WHITELISTED", 10)

    assert "compliance" in str(exc.value).lower()


# ── 13-B: reservation ────────────────────────────────────────────────────


async def test_a_holder_cannot_commit_more_than_they_hold():
    """Measured before the fix: 3 x 100 accepted against a balance of 100."""
    service, security_id = await _service_with_listed_security("0xSELLER")
    service._balances[(security_id, "0xSELLER")] = 100

    await service.sell(security_id, "0xSELLER", 100, 12.0)

    with pytest.raises(ValueError) as exc:
        await service.sell(security_id, "0xSELLER", 100, 12.0)

    assert "committed" in str(exc.value).lower()


async def test_partial_commitment_still_allows_the_remainder():
    """SCOPE PIN. Reserving must not over-reserve — a holder of 100 with 40
    committed can still sell 60."""
    service, security_id = await _service_with_listed_security("0xSELLER")
    service._balances[(security_id, "0xSELLER")] = 100

    await service.sell(security_id, "0xSELLER", 40, 12.0)
    order = await service.sell(security_id, "0xSELLER", 60, 12.0)

    assert order["original_amount"] == 60


async def test_a_cancelled_order_releases_its_reservation():
    """Reservation counts OPEN orders only — otherwise cancelling would leave a
    holder permanently unable to sell what they still own."""
    service, security_id = await _service_with_listed_security("0xSELLER")
    service._balances[(security_id, "0xSELLER")] = 100

    order = await service.sell(security_id, "0xSELLER", 100, 12.0)
    await service._exchange.cancel_order(order["order_id"])

    reopened = await service.sell(security_id, "0xSELLER", 100, 12.0)
    assert reopened["original_amount"] == 100


# ── 13-C: honest match status ────────────────────────────────────────────


async def test_a_match_is_not_reported_as_executed():
    service, security_id = await _service_with_listed_security("0xS", "0xB")
    service._balances[(security_id, "0xS")] = 100

    await service.sell(security_id, "0xS", 100, 12.0)
    await service._exchange.place_order(security_id, "buy", 12.0, 100, "0xB")

    trades = await service._exchange.match_orders(security_id)

    assert trades, "the matching engine should still match — only the claim changes"
    trade = trades[0]
    assert trade["settled"] is False
    assert "executed_at" not in trade, (
        "the record still claims execution for a trade that moved nothing"
    )
    assert "matched_at" in trade
    assert "no settlement path" in trade["settlement"].lower()


async def test_a_matched_order_is_not_marked_filled():
    service, security_id = await _service_with_listed_security("0xS", "0xB")
    service._balances[(security_id, "0xS")] = 100

    sell_order = await service.sell(security_id, "0xS", 100, 12.0)
    await service._exchange.place_order(security_id, "buy", 12.0, 100, "0xB")
    await service._exchange.match_orders(security_id)

    status = service._exchange._orders[sell_order["order_id"]]["status"]
    assert status == "matched_unsettled", (
        f"an order that transferred nothing is marked {status!r}"
    )


async def test_matching_still_moves_no_balances_and_says_so():
    """THE HONEST STATE, pinned. The fix does NOT make matching settle — it makes
    matching stop claiming it did. If a real settlement leg ever lands, this test
    fails and should be replaced by one asserting the transfer."""
    service, security_id = await _service_with_listed_security("0xS", "0xB")
    service._balances[(security_id, "0xS")] = 100

    await service.sell(security_id, "0xS", 100, 12.0)
    await service._exchange.place_order(security_id, "buy", 12.0, 100, "0xB")

    before = dict(service._balances)
    await service._exchange.match_orders(security_id)

    assert service._balances == before
    assert service._balances.get((security_id, "0xB"), 0) == 0


def test_the_matching_engine_still_cannot_reach_balances():
    """THE STRUCTURAL FACT behind all three findings, pinned so it cannot change
    silently. If ExchangeContract ever gains a balances reference, settlement
    became possible and every disposition above should be revisited."""
    from runtime.blockchain.services.securities_exchange.exchange import (
        ExchangeContract,
    )

    contract = ExchangeContract({})

    assert not hasattr(contract, "_balances")
    assert not any("balance" in name for name in vars(contract))
