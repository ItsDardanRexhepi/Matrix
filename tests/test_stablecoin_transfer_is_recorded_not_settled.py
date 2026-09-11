"""A stablecoin transfer says what it did: recorded, not settled.

15-A. `transfer` returned `status: "completed"` with `transfer_id:
"tx_63db0c44..."` while moving numbers in a plain in-process dict. No signer, no
RPC, no chain write, no tx_hash anywhere in the service.

WHY VOCABULARY AND NOT REMOVAL — the NEW-85 test, applied. Strip the outcome
claim: is there work left? YES. Tiered fee arithmetic, a rate limiter that
genuinely blocks, a balance tracker recording inflow/outflow. Category 6
(real-local-defective): the custody claim was the only fabricated part, and
removing the method would destroy working machinery. Same disposition
`cross_border.send_payment` received under NEW-85.

AND THAT IS THE SECOND FINDING HERE. `tests/test_cross_border_send_honesty.py`
pins NEW-85 **by service name** — it could never have caught this instance. A
finding about a pattern closed by a test about an instance: the RUN-4 shape,
which is exactly why the envelope-inversion recurrence happened. Queued for the
Phase-6 sweep of pre-detector findings closed by instance-tests.

THE PREFIX WAS ITS OWN CLAIM, ON A THIRD AXIS. A uuid is opaque and asserts
nothing. `tx_63db0c44...` asserts provenance BY ITS FORM — it reads as a chain
transaction hash in a UI, a support ticket, or a screenshot, without anyone
reading the status field this audit has been auditing. D6 detects the METHOD
SHAPE (uuid-mint-no-await); D7 detects the CLAIM (what a method says it did).
**Neither looks at the FORMAT OF THE IDENTIFIER.** Measured repo-wide: 17
origin-asserting identifiers built from local randomness across 10 files — a
class, registered for Phase 6, not fixed here beyond this instance.
"""

from __future__ import annotations

import os

import pytest

from runtime.blockchain.services.stablecoin.service import StablecoinService


@pytest.fixture
def funded() -> StablecoinService:
    service = StablecoinService({})
    service.set_balance("0xA", "USDC", 1000.0)
    return service


async def test_a_transfer_does_not_claim_to_have_settled(funded):
    """THE LOAD-BEARING ASSERTION."""
    result = await funded.transfer("USDC", "0xA", "0xB", 100.0)

    assert result["status"] == "recorded_unsettled"
    assert result["settled"] is False
    assert result["value_moved"] is False
    assert "no on-chain transfer was submitted" in result["disclosure"].lower()


async def test_the_identifier_does_not_assert_a_chain_origin(funded):
    """THE FORMAT IS A CLAIM. `tx_` reads as a transaction hash to anyone who
    sees it, independent of the status field."""
    result = await funded.transfer("USDC", "0xA", "0xB", 100.0)

    assert not result["transfer_id"].startswith("tx_")
    assert result["transfer_id"].startswith("ledger_"), (
        "the prefix should name what it actually is — an internal ledger entry"
    )


async def test_the_real_work_the_vocabulary_fix_preserved(funded):
    """WHY THIS WAS CATEGORY 6. Strip the claim and this is what remains — if
    any of it stops working, the disposition was wrong and the method should
    have been refused rather than renamed."""
    result = await funded.transfer("USDC", "0xA", "0xB", 100.0)

    assert result["fee"] > 0, "tiered fee arithmetic"
    assert result["fee_tier"], "tier classification"
    assert result["net_amount"] == pytest.approx(100.0 - result["fee"])
    assert funded._balances["0xA"]["USDC"] == pytest.approx(900.0)
    assert funded._balances["0xB"]["USDC"] == pytest.approx(result["net_amount"])


async def test_the_rate_limiter_still_blocks(funded):
    """A control that survives the fix. If this stops firing, the vocabulary
    change removed protection rather than a claim.

    REWRITTEN — THE FIRST VERSION OF THIS TEST WAS VACUOUS, and the adversarial
    pass proved it with a mutation. It sent 12 x 500,000 against a 50,000/day
    cap, so call #0 was ALREADY over the limit: every call blocked, the
    allow->block TRANSITION was never observed, and `record_transfer` was never
    reached. Deleting the limiter's entire usage accumulation left it green,
    while a real caller could move 1,000,000 USDC against a 50,000 cap — a 20x
    breach shipping under a passing test named for the control it did not test.

    A test that only ever sees the refusing branch of a threshold does not test
    the threshold. It tests that the function has a refusing branch.
    """
    service = StablecoinService({})
    service.set_balance("0xA", "USDC", 5_000_000.0)

    results = [
        await service.transfer("USDC", "0xA", f"0xB{i}", 10_000.0)
        for i in range(20)
    ]
    statuses = [r.get("status") for r in results]

    assert statuses[0] == "recorded_unsettled", "the first transfer must be ALLOWED"
    assert "blocked" in statuses, "the limiter never fired"

    allowed = statuses.count("recorded_unsettled")
    assert allowed == 5, (
        f"5 x 10,000 exhausts the 50,000 daily cap; {allowed} were allowed — "
        "usage is not accumulating across calls"
    )
    assert statuses.index("blocked") == 5, "the transition is not at the cap"


async def test_the_limiter_accumulates_rather_than_checking_one_call(funded):
    """THE MUTATION THE OLD TEST MISSED, asserted directly. If record_transfer
    stops accumulating, the per-call check still refuses a single oversized
    transfer — so only a test that reads the accumulated usage catches it."""
    service = StablecoinService({})
    service.set_balance("0xA", "USDC", 5_000_000.0)

    for i in range(3):
        await service.transfer("USDC", "0xA", f"0xB{i}", 10_000.0)

    import time as _time

    usage = service._rate_limiter._compute_usage("0xA", _time.time())
    assert usage["daily"] == pytest.approx(30_000.0), (
        f"three 10,000 transfers should register 30,000 of daily usage, got {usage['daily']}"
    )


async def test_the_lifetime_balance_tracker_records_the_right_direction(funded):
    """THE THIRD PILLAR OF THE CATEGORY-6 DISPOSITION, PREVIOUSLY UNASSERTED.

    The commit justified keeping this method (rather than removing it) on three
    pieces of real work: tiered fees, the rate limiter, and "a balance tracker
    recording inflow/outflow". The first two had tests. The third had NONE — the
    adversarial pass swapped the inflow/outflow directions so the SENDER was
    recorded as having received the money, and the suite stayed green.

    Evidence for a disposition has to be tested, or the disposition rests on a
    claim no one checked.
    """
    await funded.transfer("USDC", "0xA", "0xB", 100.0)

    sender = (await funded._balance_tracker.get_lifetime_volume("0xA"))["tokens"]["USDC"]
    recipient = (await funded._balance_tracker.get_lifetime_volume("0xB"))["tokens"]["USDC"]

    assert sender["outflow"] == pytest.approx(100.0)
    assert sender["inflow"] == pytest.approx(0.0), (
        "the sender is recorded as having RECEIVED the transfer"
    )
    assert recipient["outflow"] == pytest.approx(0.0)
    assert recipient["inflow"] == pytest.approx(100.0 - 0.1), (
        "the recipient's recorded inflow is not the NET amount"
    )


# ── 15-D: the guard NaN walked through ───────────────────────────────────


async def test_a_nan_amount_is_refused():
    """15-D. NaN is False against EVERY comparison, so `amount <= 0` and
    `sender_balance < amount` both passed it through."""
    service = StablecoinService({})

    result = await service.transfer("USDC", "0xA", "0xB", float("nan"))

    assert result["status"] == "error"
    assert "finite" in result["error"].lower()


async def test_a_nan_transfer_cannot_fund_an_unfunded_ledger():
    """THE ACTUAL HARM, asserted end to end. The first call poisoned three
    ledger entries with NaN; the SECOND call then credited a real 39,990 USDC
    from an address that was never funded. Driven at the pre-fix commit."""
    service = StablecoinService({})

    await service.transfer("USDC", "0xATTACKER", "0xSINK", float("nan"))
    assert service._balances == {}, "a refused transfer still wrote to the ledger"

    result = await service.transfer("USDC", "0xATTACKER", "0xVICTIM", 40_000.0)

    assert result["status"] == "error"
    assert "insufficient balance" in result["error"].lower()
    assert (await service.get_balance("0xVICTIM", "USDC"))["balance"] == 0.0


async def test_get_fee_does_not_classify_a_nan_into_the_maximum_tier():
    """SAME AXIS, SECOND ENTRY POINT — the surface rule. `amount < threshold` is
    False for NaN on every tier, so NaN fell through the whole loop and returned
    fee=NaN under tier "maximum", as though it had classified the amount."""
    service = StablecoinService({})

    fee = await service.get_fee(float("nan"))

    assert fee["tier"] == "invalid"
    assert fee["fee"] == 0.0


async def test_an_infinite_amount_is_refused_with_a_reason():
    """inf was ALREADY refused before the fix, but for the wrong reason —
    `sender_balance < inf` is True, so it read as "insufficient balance" rather
    than as a malformed amount. A funded ledger would have changed that answer."""
    service = StablecoinService({})
    service.set_balance("0xA", "USDC", 1000.0)

    result = await service.transfer("USDC", "0xA", "0xB", float("inf"))

    assert result["status"] == "error"
    assert "finite" in result["error"].lower()


async def test_no_surface_still_says_the_transfer_completed(caplog):
    """15-E. THE OPERATOR LOG IS A SURFACE. 15-A rewrote the response and left
    this line asserting the settlement the response denies — the same miss the
    cited template (NEW-85) had already fixed for cross_border. Pinned here by
    SHAPE rather than by service name, because pinning NEW-85 by service name is
    exactly why this instance was never caught (the RUN-4 shape)."""
    import logging

    service = StablecoinService({})
    service.set_balance("0xA", "USDC", 1000.0)

    with caplog.at_level(logging.INFO):
        await service.transfer("USDC", "0xA", "0xB", 100.0)

    live = "\n".join(r.getMessage() for r in caplog.records)
    assert "Transfer completed" not in live, "the log still claims settlement"
    assert "NOT settled" in live, "the log line no longer discloses"


# ── 15-C: the unattended mint ────────────────────────────────────────────


def test_set_balance_is_refused_outside_the_test_environment(monkeypatch):
    """15-C. An arbitrary mint on a stablecoin ledger — any address, any amount,
    no authorisation, no audit record. It had zero callers and no ACTION_MAP
    entry, so it was not live; that is the `migrate_members` shape, and the
    ruling there applies: AN INERT PRIMITIVE ONE LINE FROM LIVE IS NOT SAFE, IT
    IS UNATTENDED.

    Not deleted, because it is the ONLY thing that funds the ledger — removing
    it makes every transfer permanently impossible. Gated instead.
    """
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("OPENMATRIX_ALLOW_TEST_MINT", raising=False)
    monkeypatch.setitem(__import__("sys").modules, "pytest", None)
    monkeypatch.delitem(__import__("sys").modules, "pytest")

    service = StablecoinService({})
    with pytest.raises(RuntimeError) as exc:
        service.set_balance("0xATTACKER", "USDC", 1_000_000.0)

    assert "arbitrary mint" in str(exc.value).lower()
    assert "credential-gated issuance path" in str(exc.value).lower()


def test_the_funding_path_still_works_for_tests():
    """SCOPE PIN. Gating must not break the only way the ledger is fundable, or
    every transfer becomes permanently impossible and the test path dies."""
    service = StablecoinService({})
    service.set_balance("0xA", "USDC", 500.0)

    assert service._balances["0xA"]["USDC"] == 500.0


async def test_an_unfunded_ledger_still_refuses_a_well_formed_transfer():
    """── THIS TEST PINNED A FALSE CLAIM. THE CLAIM IS RETRACTED. ──

    It used to be named `test_an_unfunded_ledger_still_refuses_a_transfer` and
    its docstring read: "Nothing in production can fund a balance, so the
    fabricated 'completed' was unreachable — disarmed by ABSENCE OF A FUNDING
    PATH." That was FALSE, and 15-D proves it: `transfer` with `amount=NaN`
    funds the ledger from an unfunded address, reachable over HTTP.

    The assertion below is still TRUE — it just does not support the conclusion
    it was written to support. A WELL-FORMED transfer against an unfunded ledger
    is refused. That is one input. The docstring generalised it to every input
    and labelled 15-A "disarmed" on that basis.

    Kept, renamed, and re-scoped rather than deleted, because the behaviour is
    worth pinning and because the sixth adjudication category — a test that
    pins an unverified claim — is better shown than described. 15-A is
    reclassified ARMED in the closeout.
    """
    service = StablecoinService({})

    result = await service.transfer("USDC", "0xA", "0xB", 100.0)

    assert result["status"] == "error"
    assert "insufficient balance" in result["error"].lower()
