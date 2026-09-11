"""20-E — the conservation check and the release schedule read ONE value.

§I.13. `create_campaign` validated `sum(m.get("release_pct", 0))` and stored
`m.get("release_pct", 100 / len(milestones))`. Two different defaults for one
key: an ABSENT key contributed 0 to the conservation check and a FULL SHARE to
the schedule that spends the money.

MEASURED at pin e6cbc018 with two milestones, the second omitting the key:

    guard sees 100                 -> passes
    stored          [100, 50.0]    =  150%
    released        campaign["released"] = 1500.0 on raised 1000.0
    campaign status "completed"

150% of contributor money released by the campaign creator, using a field they
left out. Not malformed input — absent input.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.fundraising.service import FundraisingService


def _ms(*pcts):
    return [{"title": f"m{i}", "description": "d", "release_pct": p}
            for i, p in enumerate(pcts)]


@pytest.fixture
def svc():
    return FundraisingService({})


async def _campaign(svc, milestones, raised=1000.0):
    c = await svc.create_campaign(creator="0xA", title="t", goal=1000.0,
                                  deadline_days=30, milestones=milestones)
    cid = c["campaign_id"]
    await svc.contribute(campaign_id=cid, contributor="0xB", amount=raised)
    for i in range(len(milestones)):
        svc.milestone_verification._milestones[(cid, i)] = {
            "status": "verified", "campaign_id": cid, "milestone_idx": i}
    return c, cid


@pytest.mark.asyncio
async def test_a_milestone_omitting_release_pct_is_refused(svc):
    """THE REPRODUCTION. This exact input released 150% before the fix."""
    with pytest.raises(ValueError, match="does not declare"):
        await svc.create_campaign(
            creator="0xA", title="t", goal=1000.0, deadline_days=30,
            milestones=[{"title": "a", "description": "d", "release_pct": 100},
                        {"title": "b", "description": "d"}])


@pytest.mark.asyncio
async def test_released_can_never_exceed_raised(svc):
    """The invariant the disjunction broke, asserted on the campaign record —
    NOT on the return dict, whose amount key differs from the field that is
    actually spent."""
    c, cid = await _campaign(svc, _ms(60, 40))
    for i in range(2):
        await svc.release_milestone_funds(campaign_id=cid, milestone_idx=i)
    cam = svc._campaigns[cid]
    assert cam["released"] == pytest.approx(cam["raised"])
    assert cam["released"] <= cam["raised"]


@pytest.mark.asyncio
async def test_the_stored_schedule_is_the_list_that_was_summed(svc):
    """§T.4 — by construction, not by agreement. There is no second value for
    the check and the schedule to disagree about."""
    c = await svc.create_campaign(creator="0xA", title="t", goal=1000.0,
                                  deadline_days=30, milestones=_ms(25, 25, 50))
    stored = [m["release_pct"] for m in c["milestones"]]
    assert stored == [25.0, 25.0, 50.0]
    assert sum(stored) == pytest.approx(100.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -10.0, 0.0])
@pytest.mark.asyncio
async def test_a_release_pct_that_is_not_a_quantity_is_refused(svc, bad):
    """A NaN share passed the old `abs(total - 100) > 0.01` check: `abs(nan)
    > 0.01` is False, so a NaN sum SATISFIED the conservation guard."""
    with pytest.raises(ValueError):
        await svc.create_campaign(creator="0xA", title="t", goal=1000.0,
                                  deadline_days=30, milestones=_ms(bad))


@pytest.mark.asyncio
async def test_the_harness_reaches_the_release_path(svc):
    """Proven by driving the path with verification ABSENT: it must refuse for
    that reason, not silently do nothing."""
    c = await svc.create_campaign(creator="0xA", title="t", goal=1000.0,
                                  deadline_days=30, milestones=_ms(100))
    cid = c["campaign_id"]
    await svc.contribute(campaign_id=cid, contributor="0xB", amount=1000.0)
    with pytest.raises(ValueError, match="must be verified"):
        await svc.release_milestone_funds(campaign_id=cid, milestone_idx=0)
