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
    assert svc._green[f"_carbon_{cid}"]["tonnes_remaining"] == 40.0


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
    assert svc._green[f"_carbon_{cid}"]["tonnes_remaining"] == 100.0


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


# ---------------------------------------------------------------- 20-C ------
# Every ordered guard in this service admits a NaN. `nan < floor` is False,
# `nan <= 0` is False, `nan > cap` is False — a NaN satisfies NEITHER bound of
# a range check and so passes BOTH. §AK.4: 7 paths enumerated, 7 through the
# one guard, shown equal.

_NAN_PATHS = [
    ("create_campaign.goal", "goal"),
    ("create_campaign.deadline_days", "deadline_days"),
    ("contribute.amount", "amount"),
    ("buy_carbon_credit.amount", "amount"),
    ("retire_carbon_credit.tonnes", "tonnes"),
    ("buy_renewable_cert.energy_mwh", "energy_mwh"),
    ("invest_green_bond.amount", "amount"),
]

_MS = [{"title": "m", "description": "d", "release_pct": 100}]


async def _drive(svc: FundraisingService, path: str, value):
    cid = (await svc.create_campaign(
        creator="0xA", title="t", goal=1000.0, deadline_days=30, milestones=_MS,
    ))["campaign_id"]
    # `return {...}[path]()` returns the COROUTINE. `await _drive(...)` then
    # awaits _drive, gets a coroutine back, and never runs it — 21 tests that
    # exercised nothing. It failed loud only because these assert a REFUSAL;
    # a test asserting acceptance would have passed silently. Hence the
    # reached-the-code control below.
    return await {
        "create_campaign.goal": lambda: svc.create_campaign(
            creator="0xA", title="t", goal=value, deadline_days=30, milestones=_MS),
        "create_campaign.deadline_days": lambda: svc.create_campaign(
            creator="0xA", title="t", goal=10.0, deadline_days=value, milestones=_MS),
        "contribute.amount": lambda: svc.contribute(
            campaign_id=cid, contributor="0xB", amount=value),
        "buy_carbon_credit.amount": lambda: svc.buy_carbon_credit(
            buyer="0xA", amount=value),
        "retire_carbon_credit.tonnes": lambda: svc.retire_carbon_credit(
            holder="0xA", credit_id="x", tonnes=value),
        "buy_renewable_cert.energy_mwh": lambda: svc.buy_renewable_cert(
            buyer="0xA", energy_mwh=value),
        "invest_green_bond.amount": lambda: svc.invest_green_bond(
            investor="0xA", amount=value),
    }[path]()


@pytest.mark.parametrize("path,_arg", _NAN_PATHS)
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.asyncio
async def test_no_entry_point_admits_a_non_finite_quantity(svc, path, _arg, bad):
    with pytest.raises(ValueError, match="finite"):
        await _drive(svc, path, bad)


@pytest.mark.asyncio
async def test_a_nan_contribution_cannot_permanently_unfund_a_campaign(svc):
    """MEASURED before the fix: ONE NaN contribution set `raised` to NaN, and
    since `nan >= goal` is False the campaign could NEVER reach "funded" —
    a later honest contribution of 999999 left `raised=nan`, `status=active`,
    and told THAT contributor `progress_pct=nan`. Denial of funding by any
    caller, on a campaign they do not own, for the price of one contribution.
    """
    cid = (await svc.create_campaign(
        creator="0xA", title="t", goal=1000.0, deadline_days=30, milestones=_MS,
    ))["campaign_id"]
    with pytest.raises(ValueError, match="finite"):
        await svc.contribute(campaign_id=cid, contributor="0xATK", amount=float("nan"))

    out = await svc.contribute(campaign_id=cid, contributor="0xHONEST", amount=1500.0)
    assert not math.isnan(out["progress_pct"])
    assert svc._campaigns[cid]["raised"] == 1500.0
    assert svc._campaigns[cid]["status"] == "funded"


@pytest.mark.asyncio
async def test_all_four_green_actions_answer_the_attestation_predicate(svc):
    """20-B named FOUR actions. Fixing the two carbon ones and leaving the
    other two would be §AK.2's half-fix inside the remediation itself."""
    cid = (await svc.buy_carbon_credit(buyer="0xA", amount=10.0))["id"]
    records = [
        await svc.buy_carbon_credit(buyer="0xA", amount=10.0),
        await svc.retire_carbon_credit(holder="0xA", credit_id=cid, tonnes=1.0),
        await svc.buy_renewable_cert(buyer="0xA", energy_mwh=5.0),
        await svc.invest_green_bond(investor="0xA", amount=5.0),
    ]
    assert len(records) == 4
    for rec in records:
        assert rec["settled"] is False
        assert rec["value_moved"] is False
        assert rec.get("disclosure")
        assert _outcome_is_real(rec) is False


@pytest.mark.parametrize("path,_arg", _NAN_PATHS)
@pytest.mark.asyncio
async def test_the_nan_harness_reaches_the_code_under_test(svc, path, _arg):
    """Every path in `_NAN_PATHS` must actually execute under `_drive`.

    Proven by passing a value the guard REJECTS FOR A DIFFERENT REASON
    (negative, not non-finite): if the driver never ran the method, no error
    arrives at all and this goes red. A refusal-only assertion cannot tell
    "the guard fired" from "the harness never called it".
    """
    with pytest.raises((ValueError, PermissionError)) as caught:
        await _drive(svc, path, -1.0)
    assert "finite" not in str(caught.value)
