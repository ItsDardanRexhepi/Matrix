"""NEW-67 / NEW-68 — two-item triage, queue-jumped on stakes.

Both were surfaced by the D6 detector's 50-instance inventory. They were
pulled ahead of their domains' censuses because of what they claim, not
because they were convenient to fix while the detector was open. The other 48
wait for their domains, where the surrounding routing, twins and callers are
in view.

NEW-67 — insurance.auto_settle_claim: a denial wearing a payment's name
    status "settled", payout_amount hardcoded 0.0, oracle_data accepted and
    never read, no payout computation, no transfer. It CLOSED a claim and paid
    nothing. Same severity class as a GDPR-erasure misrepresentation: the user
    is told the thing happened and what happened is the opposite.

    THE TWIN CHECK CONTRADICTED THE EXPECTED DISPOSITION. The expectation
    going in was that no payout mechanism existed, so the honest options were
    honest-unavailable or removal. There IS one, it is real, and it was
    already constructed in InsuranceService.__init__ and already used by the
    sibling file_claim: ClaimsProcessor.process_claim verifies the parametric
    trigger against the policy, computes the payout from the policy's coverage
    amount, debits a reserve that REFUSES on insufficiency, and DENIES with a
    stated reason when the trigger is not met. So this is shadow-over-real —
    a delegation, not a removal.

    AND the custody rule from NEW-64 applies to the delegate itself:
    ReserveFund.withdraw is `self._balance -= amount` plus a ledger append.
    Real as computation, false as custody. So the delegation ALSO discloses
    value_moved=False rather than letting "approved" read as "paid".

NEW-68 — fundraising process_refunds: real arithmetic, false claim, and it
poisoned its own correction
    The pro-rata computation is genuine: it reads each contribution, computes
    the share against (total_raised - total_released), and deducts the fee.
    Real-local-defective. But it stamped "completed" and reported
    total_refunded / contributors_refunded — asserting money was returned.

    The part that makes it worse than misreporting: TWO separate places
    skipped or refused work when a prior record said "completed" — the
    process_refunds loop and request_refund. Since this module stamped
    "completed" without paying anyone, a fabricated completion would make a
    REAL refund run pass the contributor over, and would refuse their new
    request outright. The false record did not just lie; it locked in the lie.
"""

from __future__ import annotations

import inspect

from runtime.blockchain.services.fundraising.refunds import RefundManager
from runtime.blockchain.services.insurance.service import InsuranceService


# ── NEW-67 ────────────────────────────────────────────────────────────────


def _armed(svc):
    """Arm the deployment gate the way configuring a contract address does."""
    svc._web3.available = True
    svc._web3.is_placeholder = lambda _addr: False
    return svc


async def _funded_policy(svc, holder):
    """Create a policy against a funded reserve.

    The reserve starts at 0 and create_policy's solvency check correctly
    REFUSES to write coverage it cannot back — a real guard, verified in
    passing — so the reserve is funded first.
    """
    await svc._reserve_fund.deposit(10_000.0)
    policy = await svc.create_policy(
        holder=holder, policy_type="flight_delay",
        coverage={"amount": 500.0, "delay_threshold_minutes": 120},
        premium=25.0,
    )
    assert policy.get("status") != "rejected", policy
    return policy["policy_id"]


async def test_auto_settle_no_longer_settles_for_zero():
    """The reproduction: a claim whose trigger is NOT met must be DENIED with
    a reason, never 'settled' with payout 0.0."""
    svc = _armed(InsuranceService({}))
    pid = await _funded_policy(svc, "alice")

    result = await svc.auto_settle_claim(pid, {"delay_minutes": 0})

    assert result["status"] != "settled", (
        "auto_settle_claim still reports 'settled' — the vocabulary that "
        "made a non-payment look like a payment"
    )
    assert result.get("payout_amount", 0.0) != 0.0 or result["status"] != "approved", (
        "a claim was approved with a zero payout"
    )


async def test_auto_settle_delegates_to_the_real_processor():
    """Positive proof of delegation: the decision must come from the claims
    processor, not from a hardcoded record. Asserted by observing that the
    processor is actually invoked."""
    svc = _armed(InsuranceService({}))
    pid = await _funded_policy(svc, "bob")

    calls = []
    real = svc._claims_processor.process_claim

    async def spy(claim_id, claim, pol):
        calls.append((claim_id, dict(claim), pol))
        return await real(claim_id, claim, pol)

    svc._claims_processor.process_claim = spy
    await svc.auto_settle_claim(pid, {"delay_minutes": 240})

    assert calls, "the real claims processor was never invoked"
    # the oracle payload must actually reach the decision as trigger_data
    assert calls[0][1]["trigger_data"] == {"delay_minutes": 240}, (
        "oracle_data was accepted and not passed to the decision — the "
        "original defect"
    )


async def test_auto_settle_discloses_that_no_value_moved():
    """The custody half. ReserveFund.withdraw is a ledger decrement, so an
    approval must not be readable as a payment to the claimant."""
    svc = _armed(InsuranceService({}))
    pid = await _funded_policy(svc, "carol")

    result = await svc.auto_settle_claim(pid, {"delay_minutes": 240})

    assert result["value_moved"] is False
    assert "NOT a transfer" in result["disclosure"]


async def test_auto_settle_refuses_an_unknown_policy():
    """A boundary's unenumerated case fails closed rather than inventing a
    settlement for a policy that does not exist."""
    svc = _armed(InsuranceService({}))
    result = await svc.auto_settle_claim("nope", {"delay_minutes": 240})
    assert result["status"] == "error"
    assert result["error_category"] == "not_found"


def test_the_reserve_is_a_ledger_not_custody():
    """Pins WHY the disclosure is required, so a future reader does not remove
    it believing the reserve holds real funds."""
    from runtime.blockchain.services.insurance.reserve_fund import ReserveFund

    src = inspect.getsource(ReserveFund.withdraw)
    assert "self._balance -= amount" in src
    assert "send_transaction" not in src and "build_transaction" not in src


# ── NEW-68 ────────────────────────────────────────────────────────────────


async def test_refunds_are_not_reported_as_paid():
    mgr = RefundManager({})
    result = await mgr.process_refunds(
        "camp1", contributions={"alice": 60.0, "bob": 40.0},
        total_raised=100.0, total_released=20.0,
    )

    assert result["settled"] is False
    assert result["value_moved"] is False
    assert "NO refunds have been paid" in result["disclosure"]
    assert "total_refunded" not in result, (
        "the summary still names money as refunded"
    )
    assert "contributors_refunded" not in result

    for rec in result["refunds"]:
        assert rec["status"] == "calculated_unpaid"
        assert rec["settled"] is False


async def test_the_pro_rata_arithmetic_is_preserved():
    """The computation was REAL and must survive the vocabulary change — this
    is a correction of a false claim, not a removal of working logic.

    refundable pool = 100 - 20 = 80; alice's share = 60/100 -> 48.0.
    """
    mgr = RefundManager({})
    result = await mgr.process_refunds(
        "camp2", contributions={"alice": 60.0, "bob": 40.0},
        total_raised=100.0, total_released=20.0,
    )
    by_contributor = {r["contributor"]: r for r in result["refunds"]}

    assert by_contributor["alice"]["refund_amount"] == 48.0
    assert by_contributor["bob"]["refund_amount"] == 32.0
    assert result["refundable_pool"] == 80.0
    assert result["total_calculated"] == 80.0


async def test_a_calculated_refund_does_not_block_a_later_real_one():
    """THE POISONING, in the bulk path. A calculated-but-unpaid record must
    not cause a subsequent run to skip the contributor."""
    mgr = RefundManager({})
    contribs = {"alice": 60.0, "bob": 40.0}
    await mgr.process_refunds(
        "camp3", contributions=contribs, total_raised=100.0, total_released=20.0,
    )
    second = await mgr.process_refunds(
        "camp3", contributions=contribs, total_raised=100.0, total_released=20.0,
    )

    assert second["contributors_calculated"] == 2, (
        "a contributor was skipped because an unpaid record claimed to be "
        "completed — the false record blocking its own correction"
    )


async def test_a_calculated_refund_does_not_refuse_a_new_request():
    """THE POISONING, in the request path — the second instance, which a
    single-site fix would have missed."""
    mgr = RefundManager({})
    await mgr.process_refunds(
        "camp4", contributions={"alice": 60.0},
        total_raised=100.0, total_released=20.0,
    )

    record = await mgr.request_refund(
        "camp4", "alice", contribution=60.0,
        campaign={"status": "failed"},
    )
    assert record["eligible"] is True, (
        "request_refund refused because an unpaid record claimed completion"
    )


async def test_a_genuinely_settled_refund_still_suppresses_a_rerun():
    """The skip must still work for its real purpose — otherwise the fix
    would remove idempotence along with the lie."""
    mgr = RefundManager({})
    contribs = {"alice": 60.0}
    await mgr.process_refunds(
        "camp5", contributions=contribs, total_raised=100.0, total_released=20.0,
    )
    # simulate a real settlement having occurred
    mgr._refunds[("camp5", "alice")]["settled"] = True

    again = await mgr.process_refunds(
        "camp5", contributions=contribs, total_raised=100.0, total_released=20.0,
    )
    assert again["contributors_calculated"] == 0


async def test_get_refund_status_relays_the_honest_record():
    """The read-back surface must not re-launder the record into sounding
    paid."""
    mgr = RefundManager({})
    await mgr.process_refunds(
        "camp6", contributions={"alice": 60.0},
        total_raised=100.0, total_released=20.0,
    )
    status = await mgr.get_refund_status("camp6", "alice")

    assert status["status"] == "calculated_unpaid"
    assert status["value_moved"] is False
