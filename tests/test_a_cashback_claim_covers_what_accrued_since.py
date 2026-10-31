"""No dollar of unpaid cashback is covered by two open claims, and cashback
earned since a claim gets a claim of its own once it reaches the minimum.

Not every dollar has a claim. Cashback nobody has pressed claim for has none,
and neither has a remainder under `min_claim_amount` earned after the last
claim: a press then returns the open claim, whose `cashback_remaining` states
the whole balance outstanding. So open claims never add up to MORE than the
balance, and right after a press they fall short of it by less than the
minimum claim.

attest-money F18. `claim_cashback` stopped discharging the balance it never
paid, and made a second press return the SAME open claim so one balance could
not be claimed twice. It then returned that first open claim FOREVER: nothing
sets a claim `settled`, so `_open_claim` always found it. Measured before the
fix, through `track_spending`: after 20,000 of spending, claim 1 = 200.0; after
a further 50,000 the balance says `cashback_available` 700.0, and claim 2
returned claim 1's id with `amount_requested` 200.0 and `cashback_remaining`
200.0. The $500 that accrued later never got a claim record.

Driven through the service's own `track_spending`, so the accrual is the
service's, not a hand-set field.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.cashback.service import CashbackService


async def _spend(svc, amount):
    await svc.track_spending("0xA", amount, "retail")


async def test_cashback_accrued_after_an_open_claim_gets_its_own_claim():
    """DEFECT-PROVER."""
    svc = CashbackService({})
    await _spend(svc, 20_000.0)
    first = await svc.claim_cashback("0xA")
    assert first["amount_requested"] == pytest.approx(200.0)

    await _spend(svc, 50_000.0)
    balance = await svc.get_cashback_balance("0xA")
    assert balance["cashback_available"] == pytest.approx(700.0)

    second = await svc.claim_cashback("0xA")

    assert second["claim_id"] != first["claim_id"], (
        "later cashback was answered with the first claim, and never got a "
        "claim record of its own"
    )
    assert second["amount_requested"] == pytest.approx(500.0)
    assert second["cashback_remaining"] == pytest.approx(700.0)


async def test_open_claims_together_cover_the_balance_exactly():
    """When every accrual since a claim reaches the minimum and is claimed,
    paying every open claim pays the liability once — not less, not twice.
    (A remainder under the minimum has no claim yet; the next test.)"""
    svc = CashbackService({})
    await _spend(svc, 20_000.0)
    await svc.claim_cashback("0xA")
    await _spend(svc, 50_000.0)
    await svc.claim_cashback("0xA")
    await _spend(svc, 1_000.0)
    await svc.claim_cashback("0xA")

    data = svc._get_user_data("0xA")
    open_total = sum(c["amount_requested"] for c in data["claims"] if not c["settled"])
    balance = await svc.get_cashback_balance("0xA")
    assert open_total == pytest.approx(balance["cashback_available"])
    assert len({c["claim_id"] for c in data["claims"]}) == len(data["claims"])


async def test_a_second_press_with_nothing_new_is_the_same_claim():
    """SCOPE PIN — the property the first fix was for. Nothing new accrued, so
    no new id for the same money."""
    svc = CashbackService({})
    await _spend(svc, 20_000.0)

    first = await svc.claim_cashback("0xA")
    again = await svc.claim_cashback("0xA")

    assert again["claim_id"] == first["claim_id"]
    assert len(svc._get_user_data("0xA")["claims"]) == 1


async def test_a_returned_claim_states_todays_outstanding_balance():
    """A claim returned again carries the balance outstanding now, so it cannot
    be read as the whole of what is owed when more is owed."""
    svc = CashbackService({})
    await _spend(svc, 20_000.0)
    first = await svc.claim_cashback("0xA")
    await _spend(svc, 50.0)  # accrues 0.50: under the minimum claim, no new tranche

    again = await svc.claim_cashback("0xA")

    assert again["claim_id"] == first["claim_id"]
    assert again["cashback_remaining"] == pytest.approx(200.5)
    assert again["settled"] is False and again["value_moved"] is False


async def test_open_claims_never_exceed_the_balance_and_miss_less_than_the_minimum():
    """What holds after EVERY press, whatever accrued in between: no dollar is
    claimed twice (open claims add up to no more than the balance), and what no
    open claim covers is under the minimum claim. Accruals here include ones
    under the minimum, so this is the invariant the README states, not the
    exact-cover case above."""
    svc = CashbackService({})
    minimum = svc.config["min_claim_amount"]
    for spend in (20_000.0, 50.0, 30.0, 50_000.0, 10.0, 1_000.0, 70.0):
        await _spend(svc, spend)
        await svc.claim_cashback("0xA")

        data = svc._get_user_data("0xA")
        open_total = sum(c["amount_requested"] for c in data["claims"] if not c["settled"])
        balance = (await svc.get_cashback_balance("0xA"))["cashback_available"]
        assert open_total <= balance + 1e-9, (spend, open_total, balance)
        assert balance - open_total < minimum, (
            f"after spending {spend}, {balance - open_total:.2f} of cashback has "
            f"no open claim though a press was made"
        )
