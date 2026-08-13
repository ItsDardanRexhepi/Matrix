"""DOMAIN 20 — a retirement must name a credit that exists, and spend it.

20-A. `retire_carbon_credit` read NO field of any credit record and
decremented nothing. MEASURED at pin e6cbc018, before the fix:

    never purchased  -> status "retired", tonnes_retired=None
    same id twice    -> status "retired" both times
    negative tonnage -> status "retired"

A retired carbon credit is a claim someone OUTSIDE the platform relies on —
an offset registry, a disclosure, a regulator. That is what separates this
from a wrong internal balance: the counterparty is not us.

20-B. All four green fundraising actions omitted `settled`/`value_moved`, so
`_outcome_is_real`'s highest-priority override never fired and the dispatcher
EAS-attested them to the durable public feed as real outcomes.
"""

from __future__ import annotations

import math

import pytest

from runtime.blockchain.services.fundraising.service import FundraisingService
from runtime.blockchain.services.service_dispatcher import _outcome_is_real


@pytest.fixture
def svc() -> FundraisingService:
    return FundraisingService({})


async def _bought(svc: FundraisingService, tonnes: float = 100.0) -> str:
    return (await svc.buy_carbon_credit(buyer="0xA", amount=tonnes))["id"]


@pytest.mark.asyncio
async def test_retiring_a_credit_that_was_never_purchased_is_refused(svc):
    with pytest.raises(ValueError, match="not in the registry"):
        await svc.retire_carbon_credit(holder="0xA", credit_id="ghost", tonnes=1.0)


@pytest.mark.asyncio
async def test_retirement_decrements_the_credit_it_names(svc):
    cid = await _bought(svc, 100.0)
    out = await svc.retire_carbon_credit(holder="0xA", credit_id=cid, tonnes=60.0)
    assert out["tonnes_retired"] == 60.0
    assert out["tonnes_remaining"] == 40.0
    assert svc._campaigns[f"_carbon_{cid}"]["tonnes_remaining"] == 40.0


@pytest.mark.asyncio
async def test_the_same_credit_cannot_be_retired_twice(svc):
    """Double-retirement is a double-count of one physical offset."""
    cid = await _bought(svc, 100.0)
    await svc.retire_carbon_credit(holder="0xA", credit_id=cid, tonnes=100.0)
    with pytest.raises(ValueError, match="only 0.0 remain"):
        await svc.retire_carbon_credit(holder="0xA", credit_id=cid, tonnes=100.0)


@pytest.mark.asyncio
async def test_retiring_more_than_was_bought_is_refused(svc):
    cid = await _bought(svc, 10.0)
    with pytest.raises(ValueError, match="only 10.0 remain"):
        await svc.retire_carbon_credit(holder="0xA", credit_id=cid, tonnes=11.0)


@pytest.mark.asyncio
async def test_a_non_holder_cannot_retire_someone_elses_credit(svc):
    cid = await _bought(svc, 10.0)
    with pytest.raises(PermissionError, match="does not hold"):
        await svc.retire_carbon_credit(holder="0xMALLORY", credit_id=cid, tonnes=1.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -5.0, 0.0, "abc", None])
@pytest.mark.asyncio
async def test_a_tonnage_that_is_not_a_quantity_is_refused(svc, bad):
    """`nan <= 0` is False and `nan > remaining` is False — an ordered guard
    admits a NaN through BOTH bounds. On a durable environmental claim that is
    not a small amount; it is not an amount."""
    cid = await _bought(svc, 100.0)
    with pytest.raises((ValueError, TypeError)):
        await svc.retire_carbon_credit(holder="0xA", credit_id=cid, tonnes=bad)
    assert svc._campaigns[f"_carbon_{cid}"]["tonnes_remaining"] == 100.0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, 0.0])
@pytest.mark.asyncio
async def test_a_purchase_of_a_non_quantity_is_refused(svc, bad):
    with pytest.raises((ValueError, TypeError)):
        await svc.buy_carbon_credit(buyer="0xA", amount=bad)


@pytest.mark.asyncio
async def test_neither_carbon_action_is_attested_as_a_real_outcome(svc):
    """20-B. `_outcome_is_real` gates EAS attestation and publication to the
    public feed. Both records must answer its highest-priority question."""
    buy = await svc.buy_carbon_credit(buyer="0xA", amount=100.0)
    ret = await svc.retire_carbon_credit(holder="0xA", credit_id=buy["id"], tonnes=1.0)
    for name, rec in (("buy", buy), ("retire", ret)):
        assert rec["settled"] is False, name
        assert rec["value_moved"] is False, name
        assert rec.get("disclosure"), name
        assert _outcome_is_real(rec) is False, name


@pytest.mark.asyncio
async def test_the_harness_reaches_the_code_under_test(svc):
    """A guard proven by a harness that never called the method proves nothing.
    Three domain-19 harness deaths returned output byte-identical to a broken
    fix."""
    out = await svc.retire_carbon_credit(
        holder="0xA", credit_id=await _bought(svc, 5.0), tonnes=5.0
    )
    assert out["status"] == "retired" and out["tonnes_remaining"] == 0.0
