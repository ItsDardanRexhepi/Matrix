"""20-H / 20-I — also found by the adversarial pass, not the census.

20-H  §AK.2 INSIDE THE REMEDIATION. 20-B gave settled/value_moved to the four
      GREEN actions and left `contribute` — the action that actually takes a
      contributor's money, and is dispatcher-exposed. It returned no
      `settled`, no `value_moved` and no `status`, so `_outcome_is_real` took
      its `status is None -> True` branch and attested every contribution to
      the public feed as a real outcome.

20-I  `vesting.py` was never routed through 20-C's guard. `total_amount <= 0`
      admitted a NaN and minted a durable grant with total_amount=nan, and
      `cliff_pct` had NO bound: 100000 made cliff_amount 1_000_000 for a 1_000
      grant. Worse, the RETURN VALUE and the LEDGER then disagreed by 1000x —
      the clamp corrected the stored `claimed_amount` to 1000 while the
      returned `claimed` kept 1_000_000. A caller was told a million tokens
      were released.
"""

from __future__ import annotations

import time

import pytest

from runtime.blockchain.services.fundraising.service import FundraisingService
from runtime.blockchain.services.service_dispatcher import _outcome_is_real

_MS = [{"title": "a", "description": "d", "release_pct": 100}]
_LINEAR = {"type": "linear", "duration_days": 30}


@pytest.fixture
def svc():
    return FundraisingService({})


@pytest.mark.asyncio
async def test_a_contribution_is_not_attested_as_a_real_outcome(svc):
    cid = (await svc.create_campaign(creator="0xA", title="t", goal=1000.0,
                                     deadline_days=30, milestones=_MS))["campaign_id"]
    out = await svc.contribute(campaign_id=cid, contributor="0xB", amount=100.0)
    assert out["settled"] is False
    assert out["value_moved"] is False
    assert out.get("disclosure")
    assert _outcome_is_real(out) is False


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, 0.0, "5", True])
@pytest.mark.asyncio
async def test_a_vesting_grant_requires_a_real_quantity(svc, bad):
    with pytest.raises(ValueError):
        await svc.vesting.create_vesting(beneficiary="0xB", token="TKN",
                                         total_amount=bad, schedule=_LINEAR)


@pytest.mark.parametrize("pct", [100000.0, 101.0, float("nan"), -1.0])
@pytest.mark.asyncio
async def test_a_cliff_cannot_exceed_the_grant(svc, pct):
    """A cliff is a SHARE of the grant, not a multiple of it."""
    with pytest.raises(ValueError):
        await svc.vesting.create_vesting(
            beneficiary="0xB", token="TKN", total_amount=1000.0,
            schedule={"type": "cliff", "cliff_pct": pct, "duration_days": 30})


@pytest.mark.asyncio
async def test_the_claim_return_agrees_with_the_ledger(svc):
    """The clamp corrected the STORED value and left the RETURNED one
    inflated. Whatever the arithmetic does, the number handed to the caller
    must be the number that was credited."""
    v = svc.vesting
    rec = await v.create_vesting(beneficiary="0xB", token="TKN", total_amount=1000.0,
                                 schedule={"type": "cliff", "cliff_pct": 100.0,
                                           "duration_days": 30})
    g = v._vestings[rec["vesting_id"]]
    g["start_at"] = int(time.time()) - 10
    g["cliff_at"] = int(time.time()) - 5

    out = await v.claim_vested(rec["vesting_id"])
    assert out["claimed"] == out["total_claimed"]
    assert out["claimed"] <= out["total_amount"]


@pytest.mark.asyncio
async def test_the_harness_reaches_the_vesting_code(svc):
    rec = await svc.vesting.create_vesting(beneficiary="0xB", token="TKN",
                                           total_amount=1000.0, schedule=_LINEAR)
    assert rec["vesting_id"]
    assert svc.vesting._vestings[rec["vesting_id"]]["total_amount"] == 1000.0
