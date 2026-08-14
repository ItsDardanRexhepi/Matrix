"""20-F / 20-G — found by the ADVERSARIAL PASS against 20-A..20-E, not by the
census. Both are defects in the remediation itself.

20-G  Green-action records were stored in `self._campaigns` under prefixed
      keys. `list_campaigns` iterates that dict and reads
      `campaign["campaign_id"]` unconditionally, so ONE unauthenticated
      `carbon_credit_buy` (a free action, in ACTION_MAP) permanently turned the
      no-filter `list_campaigns` into `KeyError: 'campaign_id'`. The registry
      caches the service as a singleton, so the break was process-global.

      It also suppressed a refund path: `list_campaigns` is one of the four
      NEW-74 auto-fail detection sites. Pre-existing at the pin — and 20-A is
      what made it matter, by promoting `_campaigns` to the carbon registry of
      record. A heterogeneous store became security-load-bearing.

20-F  20-C's `float(value)` WIDENED the accepted input: `goal="500"` raised
      TypeError before the fix and was accepted after it. A guard added to
      refuse bad values must not, on the way, start admitting values the code
      previously rejected.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.fundraising.service import FundraisingService

_MS = [{"title": "a", "description": "d", "release_pct": 100}]


@pytest.fixture
def svc():
    return FundraisingService({})


async def _campaign(svc):
    return (await svc.create_campaign(creator="0xA", title="t", goal=1000.0,
                                      deadline_days=30, milestones=_MS))["campaign_id"]


@pytest.mark.asyncio
async def test_green_actions_do_not_break_list_campaigns(svc):
    """THE REPRODUCTION: one free unauthenticated action broke this call for
    the lifetime of the process."""
    await _campaign(svc)
    cid = (await svc.buy_carbon_credit(buyer="0xATK", amount=5.0))["id"]
    await svc.retire_carbon_credit(holder="0xATK", credit_id=cid, tonnes=1.0)
    await svc.buy_renewable_cert(buyer="0xATK", energy_mwh=1.0)
    await svc.invest_green_bond(investor="0xATK", amount=1.0)

    rows = await svc.list_campaigns()          # no filter — the natural call
    assert len(rows) == 1
    assert rows[0]["campaign_id"]


@pytest.mark.asyncio
async def test_campaigns_holds_only_campaigns(svc):
    """ONE DICT, ONE SHAPE — the invariant, stated where it is depended on."""
    await _campaign(svc)
    cid = (await svc.buy_carbon_credit(buyer="0xA", amount=5.0))["id"]
    await svc.retire_carbon_credit(holder="0xA", credit_id=cid, tonnes=1.0)
    await svc.buy_renewable_cert(buyer="0xA", energy_mwh=1.0)
    await svc.invest_green_bond(investor="0xA", amount=1.0)

    assert all("campaign_id" in r for r in svc._campaigns.values())
    assert len(svc._green) == 4
    assert not any(k.startswith("_") for k in svc._campaigns)


@pytest.mark.asyncio
async def test_a_stray_record_is_skipped_rather_than_fatal(svc):
    """§T.4 — the guard holds even if a future writer reintroduces the mix,
    which is the failure it could not anticipate."""
    await _campaign(svc)
    svc._campaigns["_stray_"] = {"id": "x", "status": "purchased"}
    rows = await svc.list_campaigns()
    assert len(rows) == 1


@pytest.mark.parametrize("bad", ["500", "1e999", True, False, None, [1], {"a": 1}])
@pytest.mark.asyncio
async def test_a_quantity_must_be_a_number_not_a_string_or_bool(svc, bad):
    """`float()` accepts str, and bool is an int subclass. The finiteness fix
    was not licensed to change the type contract in either direction."""
    with pytest.raises(ValueError, match="must be a number"):
        await svc.create_campaign(creator="0xA", title="t", goal=bad,
                                  deadline_days=30, milestones=_MS)


@pytest.mark.parametrize("good", [500, 500.0, 1e6])
@pytest.mark.asyncio
async def test_honest_numeric_quantities_still_pass(svc, good):
    """The other half: a type guard that refuses valid input is its own defect."""
    c = await svc.create_campaign(creator="0xA", title="t", goal=good,
                                  deadline_days=30, milestones=_MS)
    assert c["goal"] == float(good)
