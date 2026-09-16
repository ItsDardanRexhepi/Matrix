"""A durable record must be derived from what happened, not from reaching the
next line.

CLUSTER attest-money. Twelve places where the platform writes something that
OUTLIVES the call — an EAS attestation, a public-feed entry, a claimable
balance, a billing counter, a sponsorship ledger row, a job invoice — and
derives the content of that record from control flow rather than from the
verdict the thing it called actually returned.

``runtime/protocols/outcome_truth.py`` already reads a tool's own verdict from
the structure it returned, and ``ProtocolStack.post_action`` already refuses to
learn from an unlabelled outcome. That fix governs LEARNING. It does not reach
the records below, because each of these is written by the service itself,
before any dispatcher sees it, and several of them are written with no call to
check at all: the record is the only evidence that ever existed.

THE SHAPE, in the four forms it takes here:

  1. A STRUCTURED FAILURE READ AS A SUCCESS. The callee returned
     ``{"status": "failed"}`` or ``{"status": "not_configured"}`` and the caller
     wrote its record from the fact that nothing was raised.
     (batch_processor, crossborder, social scheduler, a2a coordinator)

  2. A RECORD OF AN ACTION THAT WAS NEVER ATTEMPTED. No call is made at all and
     the record says the thing was done.
     (gaming.attest_achievement, rwa.fractional_buy, rwa.claim_income,
      nft.royalty_claim, cashback.claim_cashback, subscriptions billing)

  3. A BROADCAST READ AS A SETTLEMENT. A node accepted a raw transaction and the
     record says value moved. 19-C and 21-C fixed this in restaking and in
     creator_platforms; ``NeoSafeRouter.route_revenue`` is the third instance,
     and it also writes an on-chain attestation from it.

  4. A COUNTER SPENT ON THE WRONG EVENT. The sponsorship ledger marked budget
     spent when a SIGNATURE was produced, which is not when gas is paid.

NONE OF THIS IS A STRING SNIFF (§NEW-27). Every assertion below reads named
fields of structures the platform itself emitted, or observes state the platform
itself wrote.

THE THIRD ANSWER IS USED THROUGHOUT. Where the truth is not established — a
broadcast with no receipt, a renewal with no payment gateway, a job whose tool
calls disagree — the record says so and the platform does not learn from it,
attest it, publish it or bill for it. A mislabelled record is worse than an
unlabelled one, and every fix below chooses the unlabelled one.
"""

from __future__ import annotations

import json
import time
import types

import pytest

from runtime.protocols.outcome_truth import FAILURE, SUCCESS, UNKNOWN, report_of


# ── helpers ───────────────────────────────────────────────────────────────


class _DeployedWeb3:
    """A Web3Manager stand-in that reports a deployed, reachable contract, so a
    service's own not-deployed guard is passed and the path under test runs."""

    available = True

    @staticmethod
    def is_placeholder(_address: str) -> bool:
        return False

    @staticmethod
    def explorer_url(tx_hash: str) -> str:
        return f"https://basescan.org/tx/{tx_hash}"


def _nothing_moved(record: dict, label: str) -> None:
    """The house idiom for "a record exists and nothing settled", asserted the
    way `_outcome_is_real` and `report_of` actually read it."""
    from runtime.blockchain.services.service_dispatcher import _outcome_is_real

    assert _outcome_is_real(record) is False, (
        f"{label}: the dispatcher would EAS-attest this and publish it to the "
        f"public feed as an action that happened: {record}"
    )
    assert report_of(record) is not SUCCESS, (
        f"{label}: outcome learning would record this as a success: {record}"
    )


# ── 1. the EAS batch: a structured failure is not a submission ────────────


class _AttestStub:
    """Stands in for EASClient. Returns what the real one returns when the
    chain is not configured — a RETURNED refusal, never a raised one."""

    def __init__(self, result: dict) -> None:
        self._result = result
        self.calls = 0

    async def attest(self, **_kwargs) -> dict:
        self.calls += 1
        return dict(self._result)


def _batch_processor(monkeypatch, attest_result: dict):
    from runtime.blockchain.services.attestation import batch_processor as bp

    stub = _AttestStub(attest_result)
    monkeypatch.setattr(bp, "_eas_client_for", lambda _cfg: stub, raising=False)
    proc = bp.BatchProcessor({}, batch_size=1000, flush_interval_seconds=3600)
    return proc, stub


async def test_a_batch_whose_attestations_refused_is_not_reported_submitted(monkeypatch):
    """DEFECT-PROVER. ``EASClient.attest`` returns ``{"status": "skipped"}``
    when the chain is not configured and ``{"status": "failed", "error": ...}``
    when the transaction reverts. Neither raises, so the ``except`` in
    ``flush()`` never fired and the log said "submitted successfully"."""
    proc, _stub = _batch_processor(
        monkeypatch, {"status": "skipped", "reason": "blockchain not configured"})
    await proc.add({"schema_uid": "0x1", "data": {"action": "a"}, "recipient": "0xA"})

    results = await proc.flush()

    assert results, "the flush returned nothing at all"
    assert all(report_of(r) is not SUCCESS for r in results), (
        f"a skipped attestation was reported as a landed one: {results}"
    )


async def test_an_attestation_that_did_not_land_is_not_dropped(monkeypatch):
    """THE DURABLE HALF, and the worse one. ``flush()`` CLEARS the queue before
    submitting, and the only re-queue sits under an ``except`` that a returned
    refusal never reaches. Every attestation in the batch was silently lost."""
    proc, _stub = _batch_processor(
        monkeypatch, {"status": "failed", "error": "reverted"})
    await proc.add({"schema_uid": "0x1", "data": {"action": "a"}, "recipient": "0xA"})
    await proc.add({"schema_uid": "0x2", "data": {"action": "b"}, "recipient": "0xB"})

    await proc.flush()

    assert proc.pending_count == 2, (
        f"two attestations that never landed were dropped; queue holds "
        f"{proc.pending_count}"
    )


async def test_an_attestation_that_landed_is_not_re_queued(monkeypatch):
    """SCOPE PIN. A flush that never clears anything is the mirror defect: the
    same attestation would be written to the chain on every interval."""
    proc, _stub = _batch_processor(
        monkeypatch, {"status": "attested", "attestation_tx": "0xdead"})
    await proc.add({"schema_uid": "0x1", "data": {"action": "a"}, "recipient": "0xA"})

    results = await proc.flush()

    assert proc.pending_count == 0, "a landed attestation was queued for a second write"
    assert all(report_of(r) is SUCCESS for r in results), results


async def test_one_attestation_raising_does_not_lose_the_others(monkeypatch):
    """A raise inside the per-attestation loop unwound past every result already
    collected, and ``flush``'s handler then re-queued the WHOLE batch — losing
    the record of the ones that landed and queueing them to be written twice."""
    from runtime.blockchain.services.attestation import batch_processor as bp

    class _Flaky:
        def __init__(self) -> None:
            self.n = 0

        async def attest(self, **_kwargs):
            self.n += 1
            if self.n == 2:
                raise RuntimeError("rpc dropped the connection")
            return {"status": "attested", "attestation_tx": f"0x{self.n:02x}"}

    flaky = _Flaky()
    monkeypatch.setattr(bp, "_eas_client_for", lambda _cfg: flaky, raising=False)
    proc = bp.BatchProcessor({}, batch_size=1000, flush_interval_seconds=3600)
    for i in range(3):
        await proc.add({"schema_uid": f"0x{i}", "data": {"action": "a"}, "recipient": "0xA"})

    results = await proc.flush()

    assert len(results) == 3, f"results were lost by the raise: {results}"
    assert proc.pending_count == 1, (
        f"exactly the one that raised should be waiting; queue holds {proc.pending_count}"
    )


# ── 2. crossborder: 'payment_attested' with no attestation and no payment ──


async def test_a_crossborder_send_does_not_claim_an_attestation_it_did_not_get(monkeypatch):
    """DEFECT-PROVER. ``_send`` returned ``status: "payment_attested"`` on a
    fixed string, having never looked at the attestation it holds in hand."""
    from runtime.blockchain import crossborder as cb

    class _Client:
        def __init__(self, _cfg): pass
        async def attest(self, **_k):
            return {"status": "skipped", "reason": "blockchain not configured"}

    monkeypatch.setattr("runtime.blockchain.eas_client.EASClient", _Client)

    svc = cb.CrossBorderPayments({})
    body = json.loads(await svc._send({"token": "USDC", "amount": "5000", "to": "0xA"}))

    assert body["status"] != "payment_attested", (
        f"the attestation was skipped and the record says it happened: {body}"
    )
    _nothing_moved(body, "crossborder.send with no attestation")


async def test_a_crossborder_send_never_claims_value_moved(monkeypatch):
    """The second half, true on EVERY path: ``_send`` makes no transfer at all —
    its own ``next_step`` says the transfer is a different call. A record of a
    $5,000 cross-border payment must not read as one that was sent."""
    from runtime.blockchain import crossborder as cb

    class _Client:
        def __init__(self, _cfg): pass
        async def attest(self, **_k):
            return {"status": "attested", "attestation_tx": "0xfeed"}

    monkeypatch.setattr("runtime.blockchain.eas_client.EASClient", _Client)

    svc = cb.CrossBorderPayments({})
    body = json.loads(await svc._send({"token": "USDC", "amount": "5000", "to": "0xA"}))

    assert body.get("value_moved") is False, (
        f"no transfer is made on this path and the record does not say so: {body}"
    )
    _nothing_moved(body, "crossborder.send that attested but sent nothing")


# ── 3..5, 9. a record of an action that was never attempted ───────────────


async def test_an_achievement_is_not_attested_by_saying_attested():
    """DEFECT-PROVER. ``GamingService.attest_achievement`` wrote
    ``status: "attested"`` into a durable record and made no attestation call of
    any kind — no EAS client, no contract, no transaction."""
    from runtime.blockchain.services.gaming.service import GamingService

    record = await GamingService({}).attest_achievement(
        game_id="g1", player="0xA", achievement="first_blood")

    assert record["status"] != "attested", (
        f"nothing was attested and the record says it was: {record}"
    )
    _nothing_moved(record, "gaming.attest_achievement")


async def test_a_fractional_buy_that_transfers_nothing_does_not_say_purchased():
    """DEFECT-PROVER. Past the not-deployed guard the method touches no
    contract, moves no token and takes no payment — and returns "purchased"."""
    from runtime.blockchain.services.rwa_tokenization.service import RWAService

    svc = RWAService({})
    svc._web3 = _DeployedWeb3()

    record = await svc.fractional_buy(
        token_id="t1", buyer="0xA", fraction_pct=10.0, amount=25_000.0)

    assert record["status"] != "purchased", record
    _nothing_moved(record, "rwa.fractional_buy")


async def test_an_income_claim_that_pays_nothing_does_not_say_claimed():
    """The sibling one method below, identical shape, and it even reports the
    amount it did not pay: ``amount_claimed: 0.0``."""
    from runtime.blockchain.services.rwa_tokenization.service import RWAService

    svc = RWAService({})
    svc._web3 = _DeployedWeb3()

    record = await svc.claim_income(token_id="t1", holder="0xA")

    assert record["status"] != "claimed", record
    _nothing_moved(record, "rwa.claim_income")


async def test_a_royalty_claim_that_touches_no_contract_does_not_say_claimed():
    """The same shape again, in the NFT service. ``buy_nft`` and
    ``royalty_claim`` are both in `_STATE_MODIFYING_ACTIONS`."""
    from runtime.blockchain.services.nft_services.service import NFTService

    svc = NFTService({})
    svc._web3 = _DeployedWeb3()

    record = await svc.royalty_claim(collection="0xC", token_id=1, claimer="0xA")

    assert record["status"] != "claimed", record
    _nothing_moved(record, "nft_services.royalty_claim")


# ── 5. cashback: the balance was zeroed and nothing was paid ──────────────


def _qualified_cashback():
    from runtime.blockchain.services.cashback.service import CashbackService

    svc = CashbackService({})
    data = svc._get_user_data("0xA")
    data.update(qualified=True, total_spending=20_000.0,
                cashback_accrued=200.0, cashback_claimed=0.0)
    return svc


async def test_a_cashback_claim_does_not_report_a_payment_that_was_not_made():
    """DEFECT-PROVER. ``claim_cashback`` names the wallet the money came from
    (``paid_from``) and the balance left behind (``cashback_remaining: 0.0``)
    for a payment no code in this service ever makes."""
    svc = _qualified_cashback()

    record = await svc.claim_cashback("0xA")

    _nothing_moved(record, "cashback.claim_cashback")
    assert record.get("value_moved") is False, (
        f"no payment rail exists on this path and the record does not say so: "
        f"{record}"
    )


async def test_an_unpaid_cashback_claim_does_not_zero_the_balance():
    """THE DURABLE HALF. The claim wrote ``cashback_claimed += available``, so
    the user's claimable balance went to zero and there is no record anywhere of
    money owed. The balance IS the liability; discharging it without paying is
    the whole loss."""
    svc = _qualified_cashback()

    await svc.claim_cashback("0xA")
    summary = await svc.get_cashback_balance("0xA")

    assert summary["cashback_available"] == 200.0, (
        f"$200 of claimable cashback was discharged by a claim that paid "
        f"nothing: {summary}"
    )


# ── 6. subscriptions: billing counters with no charge ─────────────────────


def _subscribed():
    from runtime.blockchain.services.subscriptions.service import SubscriptionService

    svc = SubscriptionService({})
    return svc


async def _plan_and_sub(svc):
    plan = await svc.create_plan(
        provider="0xP", name="Pro", price=30.0, interval="monthly",
        rewards={})
    sub = await svc.subscribe("0xA", plan["plan_id"], payment_token="tok-1")
    return plan, sub


async def test_a_subscription_does_not_record_a_payment_it_never_took():
    """DEFECT-PROVER. ``subscribe`` writes ``total_paid: plan["price"]`` and
    ``billing_count: 1`` having taken nothing. ``payment_token`` is a string the
    caller supplies and nothing validates."""
    svc = _subscribed()
    _plan, sub = await _plan_and_sub(svc)

    assert sub["total_paid"] == 0.0, (
        f"the subscription records $30 paid and no charge was attempted: {sub}"
    )
    assert sub["billing_count"] == 0, sub


async def test_a_renewal_with_no_payment_gateway_does_not_advance_the_billing():
    """DEFECT-PROVER, the recurring half. ``_attempt_payment`` is
    ``bool(sub.get("payment_token"))`` — a truthiness test on a string the
    subscriber wrote — and every tick it returns True the counters advance and
    the period rolls forward as though money changed hands."""
    svc = _subscribed()
    _plan, sub = await _plan_and_sub(svc)
    sub["next_renewal_at"] = time.time() - 1
    before = dict(sub)

    results = await svc.process_renewals()

    assert sub["total_paid"] == before["total_paid"], (
        f"a billing counter advanced with no charge attempted: {sub}"
    )
    assert sub["billing_count"] == before["billing_count"], sub
    assert results and all(r.get("action") != "renewed" for r in results), (
        f"the renewal reported itself renewed: {results}"
    )


async def test_a_renewal_that_cannot_be_charged_is_not_reported_as_a_failure():
    """THE THIRD ANSWER, and the reason this is not fixed by flipping the
    truthiness test. "No payment gateway is configured" is not a declined card:
    recording it as one would enter a grace period, and 48 hours later cancel a
    subscription for a payment that was never requested."""
    svc = _subscribed()
    _plan, sub = await _plan_and_sub(svc)
    sub["next_renewal_at"] = time.time() - 1

    await svc.process_renewals()

    assert sub["status"] == "active", (
        f"a subscription was pushed toward cancellation by a charge nobody "
        f"attempted: {sub}"
    )


#: The shapes a FOREIGN gateway can deliver a decline in that carry no field
#: this tree's measured default reads as a refusal. Not invented — these are the
#: four `foreign_report_of` names in its own docstring.
_FOREIGN_DECLINES = [
    pytest.param(None, id="none"),
    pytest.param("DECLINED", id="plain-string"),
    pytest.param(object(), id="http-response-object"),
    pytest.param({"result": "declined", "reason": "insufficient funds"},
                 id="foreign-dict-no-known-field"),
]


class _DecliningGateway:
    """A gateway that refuses, in a shape this tree never measured."""

    def __init__(self, answer):
        self._answer = answer
        self.charges = 0

    async def charge(self, **_kwargs):
        self.charges += 1
        return self._answer


@pytest.mark.parametrize("answer", _FOREIGN_DECLINES)
async def test_a_foreign_gateway_that_did_not_say_yes_is_not_a_settled_charge(answer):
    """DEFECT-PROVER, AND THE FIX INSIDE THE FIX.

    ``report_of``'s default — no report means success — is MEASURED, and it is
    measured over 182 attested actions OF THIS TREE, where every refusal idiom
    is explicit. It is a fact about code we wrote. A payment gateway is not code
    we wrote, and a party whose failure idiom we have never measured is exactly
    the party whose silence must not be read as a yes.

    ``outcome_truth.foreign_report_of`` exists for this and names this caller in
    its own docstring. ``_attempt_payment`` called ``report_of``, so a decline
    delivered in any of these shapes became ``{"status": "paid", "settled":
    True, "value_moved": True}`` — and ``process_renewals`` then advanced
    ``total_paid``, set ``charges_settled`` and rolled the billing period
    forward for money nobody took.

    UNKNOWN costs a human. SUCCESS costs a customer a charge that
    was refused.
    """
    svc = _subscribed()
    gateway = _DecliningGateway(answer)
    svc.config["payment_gateway"] = gateway
    _plan, sub = await _plan_and_sub(svc)
    sub["next_renewal_at"] = time.time() - 1
    before = dict(sub)

    results = await svc.process_renewals()

    assert gateway.charges == 1, "premise changed — the gateway was not called"
    # "charge_unconfirmed", not "not_charged": this charge WAS presented, so the
    # renewal is held for reconciliation rather than left due to be presented
    # again (see test_a_charge_whose_outcome_nobody_established_is_not_attempted_again).
    assert all(r.get("action") == "charge_unconfirmed" for r in results), (
        "an outcome nobody established was filed as settled or as refused; it "
        f"is neither: {results}")
    assert sub["charges_settled"] is False, (
        f"the platform recorded a settled charge the gateway never confirmed: {sub}")
    assert sub["total_paid"] == before["total_paid"], (
        f"a billing counter advanced on an outcome nobody established: {sub}")
    assert sub["current_period_end"] == before["current_period_end"], (
        f"the billing period rolled forward for money nobody took: {sub}")


async def test_a_foreign_gateway_that_SAYS_yes_is_still_a_settled_charge():
    """The scope pin. Refusing to read silence as a yes must not turn an
    explicit yes into a maybe — a platform that never books a payment is the
    same defect facing the other way."""
    svc = _subscribed()
    gateway = _DecliningGateway({"ok": True, "captured": "38.00"})
    svc.config["payment_gateway"] = gateway
    plan, sub = await _plan_and_sub(svc)
    sub["next_renewal_at"] = time.time() - 1

    await svc.process_renewals()

    assert sub["charges_settled"] is True, sub
    assert sub["total_paid"] == plan["price"], sub


async def test_a_foreign_gateway_that_SAYS_no_is_a_decline_not_an_unknown():
    """The other pin: an explicit refusal must stay a refusal, because a
    decline and an unestablished outcome lead to different places — one to a
    grace period, the other to a human."""
    svc = _subscribed()
    gateway = _DecliningGateway({"ok": False, "error": "card declined"})
    svc.config["payment_gateway"] = gateway
    _plan, sub = await _plan_and_sub(svc)
    sub["next_renewal_at"] = time.time() - 1

    results = await svc.process_renewals()

    assert sub["charges_settled"] is False, sub
    assert any(r.get("action") == "grace_period"
               and r.get("reason") == "payment_failed" for r in results), (
        "an explicit decline must enter the grace period that ends in "
        f"cancellation — the path an unestablished outcome must never take: {results}")


#: A FOREIGN STATUS WORD IS NOT A YES. An independent review drove these through
#: `process_renewals` after the fix above and every one was booked as a settled
#: renewal: `foreign_report_of` still handed any object with a `status` to
#: `report_of`, which reads `created: True` as success before it reads the
#: status, and reads any of the platform's 101 real-outcome words — measured
#: over THIS tree — as success. "cancelled", "processing", "refunded" and
#: "requested" are words a payment gateway uses for a charge that did not settle.
_FOREIGN_WORDS_THAT_ARE_NOT_A_SETTLED_CHARGE = [
    pytest.param({"status": "cancelled"}, id="cancelled"),
    pytest.param({"status": "processing"}, id="processing"),
    pytest.param({"status": "refunded"}, id="refunded"),
    pytest.param({"status": "requested"}, id="requested"),
    pytest.param({"status": "declined", "created": True}, id="declined-but-created"),
    pytest.param({"status": "paid"}, id="a-word-we-never-measured-for-this-party"),
    pytest.param({"ok": True, "status": "refunded"}, id="ok-contradicted-by-its-status"),
    pytest.param({"ok": True, "error": "card declined"}, id="ok-contradicted-by-its-error"),
]


@pytest.mark.parametrize("answer", _FOREIGN_WORDS_THAT_ARE_NOT_A_SETTLED_CHARGE)
async def test_a_foreign_status_word_is_not_a_settled_charge(answer):
    """DEFECT-PROVER. Only an explicit verdict the gateway adapter states is
    believed, and when the reply speaks in more than one field every field has
    to agree. A status word from a party whose vocabulary was never measured is
    not agreement."""
    svc = _subscribed()
    gateway = _DecliningGateway(answer)
    svc.config["payment_gateway"] = gateway
    _plan, sub = await _plan_and_sub(svc)
    sub["next_renewal_at"] = time.time() - 1
    before = dict(sub)

    results = await svc.process_renewals()

    assert gateway.charges == 1, "premise changed — the gateway was not called"
    assert all(r.get("action") != "renewed" for r in results), (
        f"a gateway reply of {answer!r} was booked as a settled renewal: {results}")
    assert sub["charges_settled"] is False, sub
    assert sub["total_paid"] == before["total_paid"], sub
    assert sub["current_period_end"] == before["current_period_end"], sub


class _RaisingGateway:
    def __init__(self):
        self.charges = 0

    async def charge(self, **_kwargs):
        self.charges += 1
        raise ConnectionError("reset by peer after the request was written")


@pytest.mark.parametrize("gateway", [
    pytest.param(lambda: _DecliningGateway(object()), id="an-answer-nobody-can-read"),
    pytest.param(lambda: _DecliningGateway({"status": "processing"}), id="processing"),
    pytest.param(_RaisingGateway, id="the-charge-raised-after-it-was-sent"),
])
async def test_a_charge_whose_outcome_nobody_established_is_not_attempted_again(gateway):
    """DEFECT-PROVER. The unestablished outcome was described as costing "a
    retry or a human", and the retry was a second charge: the renewal stayed
    due, so every run of `process_renewals` presented the same card again while
    `total_paid` stayed at zero. If the first charge went through, the customer
    paid once per run. A charge that was ATTEMPTED and not confirmed is held
    until someone has checked it; it is not presented again."""
    svc = _subscribed()
    gw = gateway()
    svc.config["payment_gateway"] = gw
    _plan, sub = await _plan_and_sub(svc)
    sub["next_renewal_at"] = time.time() - 1
    before = dict(sub)

    first = await svc.process_renewals()
    second = await svc.process_renewals()
    third = await svc.process_renewals()

    assert gw.charges == 1, (
        f"a charge whose outcome nobody established was presented {gw.charges} "
        f"times in three renewal runs")
    for results in (second, third):
        assert [r.get("action") for r in results] == ["charge_unconfirmed"], results
        assert results[0]["value_moved"] is None and results[0]["settled"] is False
    assert first[0]["action"] == "charge_unconfirmed", first
    assert sub["status"] == "active", "an unestablished charge pushed toward cancellation"
    assert sub["total_paid"] == before["total_paid"], sub
    assert sub["charges_settled"] is False, sub


async def test_a_renewal_nobody_tried_to_charge_is_still_retried_every_run():
    """SCOPE PIN. No gateway means no charge was attempted, so trying again
    costs nothing and must keep happening: the hold is for an ATTEMPT, not for
    every renewal that did not settle."""
    svc = _subscribed()
    _plan, sub = await _plan_and_sub(svc)
    sub["next_renewal_at"] = time.time() - 1

    await svc.process_renewals()
    assert "unconfirmed_charge" not in sub, sub

    gateway = _DecliningGateway({"ok": True})
    svc.config["payment_gateway"] = gateway
    await svc.process_renewals()
    assert gateway.charges == 1 and sub["charges_settled"] is True, sub


async def test_a_settled_renewal_does_not_hold_the_next_one():
    """SCOPE PIN. Each period is charged once; the hold must not become a
    subscription that is only ever charged once."""
    svc = _subscribed()
    gateway = _DecliningGateway({"ok": True})
    svc.config["payment_gateway"] = gateway
    plan, sub = await _plan_and_sub(svc)

    sub["next_renewal_at"] = time.time() - 1
    await svc.process_renewals()
    sub["next_renewal_at"] = time.time() - 1
    await svc.process_renewals()

    assert gateway.charges == 2, gateway.charges
    assert sub["total_paid"] == 2 * plan["price"], sub


# ── 7. the public feed's value_usd came from the request ──────────────────


def test_the_feed_value_is_read_from_the_result_not_the_request():
    """DEFECT-PROVER. The ingest block read an amount-like key out of ``params``
    — the REQUEST — so the public feed announced the figure the caller asked
    for, which is not necessarily the figure the service acted on. A partial
    fill, a capped amount, a fee-adjusted total and a refusal-then-retry all
    publish the request's number."""
    from runtime.blockchain.services.service_dispatcher import _feed_value_of

    assert _feed_value_of({"amount": 5.0}) == 5.0, (
        "the caller's number won over the service's"
    )


def test_a_result_that_names_no_value_publishes_none():
    """The third answer on the feed. Falling back to the request is exactly the
    move that made the figure untrue; an event with no value is honest."""
    from runtime.blockchain.services.service_dispatcher import _feed_value_of

    assert _feed_value_of({"status": "created", "id": "x"}) is None


def test_the_feed_value_prefers_the_settled_figure():
    from runtime.blockchain.services.service_dispatcher import _feed_value_of

    assert _feed_value_of({"value_usd": 7.5, "amount": 9.0}) == 7.5


# ── 8. neosafe: a broadcast is not a settlement ───────────────────────────


class _BroadcastWeb3:
    """Accepts a raw transaction and then cannot produce a receipt — the exact
    window 19-C named: NOT a refusal and NOT a success."""

    available = True

    def __init__(self, receipt=None, raises=True) -> None:
        self._receipt = receipt
        self._raises = raises
        self.w3 = types.SimpleNamespace(
            to_wei=lambda v, _u: int(float(v) * 10 ** 18),
            to_checksum_address=lambda a: a,
        )

    async def send_transaction(self, _tx) -> str:
        return "0x" + "ab" * 32

    async def wait_for_receipt(self, _tx_hash, timeout=120):
        if self._raises:
            raise TimeoutError("no receipt within the wait window")
        return self._receipt

    @staticmethod
    def explorer_url(tx_hash: str) -> str:
        return f"https://basescan.org/tx/{tx_hash}"


async def test_revenue_routing_does_not_report_routed_from_a_broadcast():
    """DEFECT-PROVER, third instance of 19-C. ``send_transaction`` returns when
    a NODE ACCEPTED the bytes. ``route_revenue`` returned ``status: "routed"``
    from that, and "routed" was read as a real outcome — so the dispatcher
    attested it and the public feed announced platform revenue that may have
    reverted."""
    from runtime.blockchain.services.neosafe import NeoSafeRouter

    router = NeoSafeRouter({})
    router._web3 = _BroadcastWeb3()

    record = await router.route_revenue(0.5, "swap_fee")

    assert record["status"] != "routed", record
    assert record.get("settled") is False, record
    assert record.get("tx_hash"), (
        "the under-claim half: a broadcast transaction must stay traceable"
    )
    _nothing_moved(record, "neosafe.route_revenue with no receipt")


async def test_revenue_routing_does_not_attest_an_unconfirmed_transfer():
    """The attestation is the durable part. It was written from the same
    unconfirmed broadcast, putting a claim about platform revenue on a public
    chain before anything was mined."""
    from runtime.blockchain.services import neosafe as ns

    attested: list = []

    class _Client:
        def __init__(self, _cfg): pass
        async def attest(self, **kwargs):
            attested.append(kwargs)
            return {"status": "attested", "attestation_tx": "0xfeed"}

    import runtime.blockchain.eas_client as eas_mod
    original = eas_mod.EASClient
    eas_mod.EASClient = _Client
    try:
        router = ns.NeoSafeRouter({})
        router._web3 = _BroadcastWeb3()
        await router.route_revenue(0.5, "swap_fee")
    finally:
        eas_mod.EASClient = original

    assert attested == [], (
        f"an unconfirmed transfer was attested on-chain as routed revenue: "
        f"{attested}"
    )


async def test_a_reverted_transfer_is_reported_as_reverted():
    """The chain mined it and it FAILED. Nothing moved, and the record must not
    read the same as a transfer still waiting for a block."""
    from runtime.blockchain.services.neosafe import NeoSafeRouter

    router = NeoSafeRouter({})
    router._web3 = _BroadcastWeb3(
        receipt=types.SimpleNamespace(status=0, blockNumber=99), raises=False)

    record = await router.route_revenue(0.5, "swap_fee")

    assert record["status"] == "failed", record
    assert record.get("value_moved") is False, record


async def test_a_mined_transfer_is_still_reported_as_routed():
    """SCOPE PIN. The mirror defect — a router that never reports success —
    would leave every genuine fee unrecorded."""
    from runtime.blockchain.services.neosafe import NeoSafeRouter

    router = NeoSafeRouter({})
    router._web3 = _BroadcastWeb3(
        receipt=types.SimpleNamespace(status=1, blockNumber=99), raises=False)

    record = await router.route_revenue(0.5, "swap_fee")

    from runtime.blockchain.services.service_dispatcher import _outcome_is_real
    assert _outcome_is_real(record) is True, record
    assert record.get("settled") is True, record


# ── 10. the sponsorship ledger spends on the wrong event ──────────────────


def _policy(tmp_path):
    from runtime.blockchain.sponsorship import SponsorshipPolicy

    return SponsorshipPolicy.from_config({
        "paymaster": {"policy": {"daily_cap_usd": 100.0}},
        "database": {"path": str(tmp_path / "sponsor.db")},
    })


def test_the_ledger_records_a_signature_as_a_signature(tmp_path):
    """DEFECT-PROVER. ``commit()`` wrote state ``committed`` — "the spend is
    real" — the moment ``sign_transaction`` returned. A signed transaction that
    is never broadcast, or that the node rejects, costs no gas at all. The row
    is the platform's own record of money it spent."""
    from runtime.blockchain.sponsorship import SPEND_STATES

    policy = _policy(tmp_path)
    decision = policy.authorize_and_reserve("eas.attest", identity="0xA", est_usd=1.0)
    policy.commit(decision.reservation_id)

    assert policy.state_of(decision.reservation_id) == SPEND_STATES.SIGNED, (
        "a signature was filed as gas that was paid"
    )


def test_a_signature_still_counts_against_the_cap(tmp_path):
    """SCOPE PIN, and the reason this is a relabel rather than a release. A
    signature the platform issued MAY land, so the conservative accounting is
    unchanged: it holds budget until it is settled or abandoned."""
    policy = _policy(tmp_path)
    decision = policy.authorize_and_reserve("eas.attest", identity="0xA", est_usd=1.0)
    policy.commit(decision.reservation_id)

    assert policy.spent_today("0xA") == pytest.approx(1.0)


def test_a_settled_transaction_is_recorded_as_spent(tmp_path):
    from runtime.blockchain.sponsorship import SPEND_STATES

    policy = _policy(tmp_path)
    decision = policy.authorize_and_reserve("eas.attest", identity="0xA", est_usd=1.0)
    policy.commit(decision.reservation_id)
    policy.settle(decision.reservation_id)

    assert policy.state_of(decision.reservation_id) == SPEND_STATES.SPENT
    assert policy.spent_today("0xA") == pytest.approx(1.0)


def test_a_signature_that_never_reached_the_chain_gives_the_budget_back(tmp_path):
    """The other direction. An identity charged for gas nobody paid is capped
    out of sponsorship it is entitled to."""
    policy = _policy(tmp_path)
    decision = policy.authorize_and_reserve("eas.attest", identity="0xA", est_usd=1.0)
    policy.commit(decision.reservation_id)
    policy.abandon(decision.reservation_id)

    assert policy.spent_today("0xA") == pytest.approx(0.0)


def test_the_signer_hands_back_the_row_it_opened(tmp_path, monkeypatch):
    """Without a handle on the reservation, no caller that later SEES a receipt
    could ever correct the row — which is why the record could only ever be
    written at signing time."""
    from runtime.blockchain.sponsorship import MeteredSigner

    policy = _policy(tmp_path)

    class _Account:
        address = "0x" + "ab" * 20
        @staticmethod
        def sign_transaction(_tx):
            return types.SimpleNamespace(raw_transaction=b"\x01")

    signer = MeteredSigner(_Account(), policy, "eas.attest", "0xA", 3000.0)
    signer.sign_transaction({"gas": 21000, "gasPrice": 1_000_000_000})

    assert signer.last_reservation_id, "the signer kept the row id to itself"
    assert policy.state_of(signer.last_reservation_id) is not None


# ── 11. the scheduler published a post the platform refused to send ───────


class _Manager:
    def __init__(self, result: dict) -> None:
        self._result = result

    async def post(self, **_kwargs) -> dict:
        return dict(self._result)


def _scheduled_post():
    from runtime.social.scheduler import ScheduledPost

    return ScheduledPost(
        post_id="p1", content="hello", platform="all",
        scheduled_at=time.time() - 1)


async def test_a_post_the_platform_could_not_send_is_not_marked_published():
    """DEFECT-PROVER. ``TwitterClient.post_tweet`` returns
    ``{"status": "not_configured"}`` when credentials are unset and
    ``{"status": "error", "message": ...}`` on a non-2xx — RETURNED, never
    raised. The scheduler's ``except`` never fired, so the row was written
    ``published`` with a timestamp, and the post is gone: nothing retries a row
    that says it was published."""
    from runtime.social.scheduler import PostScheduler

    sched = PostScheduler(social_manager=_Manager({
        "twitter": {"status": "not_configured", "message": "Twitter credentials not set."},
        "discord": {"status": "error", "message": "401"},
    }))
    post = _scheduled_post()
    sched.posts[post.post_id] = post

    await sched._publish(post)

    assert post.status != "published", (
        f"nothing was posted anywhere and the row says published: {post.status}"
    )
    assert post.published_at is None, post.published_at


async def test_a_partly_delivered_post_is_not_reported_as_delivered():
    """The third answer. One platform took it and one refused — the post is
    neither published nor failed, and calling it either loses information the
    row is the only record of."""
    from runtime.social.scheduler import PostScheduler

    sched = PostScheduler(social_manager=_Manager({
        "twitter": {"status": "ok", "tweet_id": "1"},
        "discord": {"status": "error", "message": "401"},
    }))
    post = _scheduled_post()
    sched.posts[post.post_id] = post

    await sched._publish(post)

    assert post.status == "partial", post.status


async def test_a_delivered_post_is_still_marked_published():
    """SCOPE PIN."""
    from runtime.social.scheduler import PostScheduler

    sched = PostScheduler(social_manager=_Manager({
        "twitter": {"status": "ok", "tweet_id": "1"},
        "discord": {"status": "ok", "channel": "default"},
    }))
    post = _scheduled_post()
    sched.posts[post.post_id] = post

    await sched._publish(post)

    assert post.status == "published" and post.published_at is not None


# ── 12. the A2A job billed because the loop returned ──────────────────────


class _Loop:
    def __init__(self, tool_calls: list[dict]) -> None:
        self._tool_calls = tool_calls

    async def run(self, _context):
        from runtime.react_loop import ReActResult

        return ReActResult(response="done", tool_calls=self._tool_calls,
                           iterations=1, provider="test")


async def _job_result(tool_calls):
    from runtime.a2a.coordinator import A2ACoordinator
    from runtime.a2a.marketplace import A2AMarketplace
    from runtime.a2a.protocol import JobRequest, ServiceListing

    market = A2AMarketplace({})
    listing = await market.register_service(ServiceListing(
        agent_id="trinity", name="analysis", description="d",
        category="analysis", price_usd=12.0))
    coordinator = A2ACoordinator(marketplace=market, react_loop=_Loop(tool_calls))
    job = JobRequest(service_id=listing.service_id, requester_agent_id="0xA",
                     input_data={"q": "x"})
    return await coordinator.execute_job(job)


async def test_a_job_whose_tools_all_refused_is_not_billed_as_a_success():
    """DEFECT-PROVER. ``success=True`` was written because ``react_loop.run``
    RETURNED. The loop returns whenever the model stops calling tools — a loop
    in which every tool refused returns exactly like one in which every tool
    worked, and the difference is in ``tool_calls``, which the coordinator held
    and did not read."""
    result = await _job_result([
        {"tool": "platform_action", "success": True, "reported": FAILURE},
        {"tool": "platform_action", "success": True, "reported": FAILURE},
    ])

    assert result.success is False, (
        "a job in which nothing the agent tried worked was completed and priced"
    )
    assert result.actual_price_usd == 0.0, (
        f"the requester was invoiced ${result.actual_price_usd} for it"
    )


async def test_a_job_with_an_unestablished_outcome_is_not_billed():
    """The third answer. Some tools refused and some worked: the job's outcome
    is not established, so it is not asserted in either direction and it is not
    invoiced."""
    result = await _job_result([
        {"tool": "platform_action", "success": True, "reported": SUCCESS},
        {"tool": "platform_action", "success": True, "reported": FAILURE},
    ])

    assert result.outcome == UNKNOWN, result.outcome
    assert result.actual_price_usd == 0.0, result.actual_price_usd


async def test_a_job_that_did_its_work_is_still_billed():
    """SCOPE PIN. A marketplace that never bills is not the fix."""
    result = await _job_result([
        {"tool": "platform_action", "success": True, "reported": SUCCESS},
    ])

    assert result.success is True and result.actual_price_usd == 12.0


async def test_a_job_with_no_tool_calls_is_still_a_success():
    """An agent that answered from what it already knew called nothing. There is
    no refusal to read, and "no evidence of trouble" is not evidence of
    trouble."""
    result = await _job_result([])

    assert result.success is True and result.outcome == SUCCESS


def test_the_loop_reports_each_tool_s_own_verdict():
    """The coordinator can only read a verdict the loop records. ``success`` in
    a tool_call entry is ``ToolOutcome.ok`` — "the dispatch completed" — which
    is True for every RETURNED refusal in the codebase."""
    import inspect

    from runtime import react_loop

    source = inspect.getsource(react_loop.ReActLoop.run)
    assert '"reported": outcome.reported' in source, (
        "the loop still records only whether the dispatch completed"
    )
