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
    change removed protection rather than a claim."""
    service = StablecoinService({})
    service.set_balance("0xA", "USDC", 10_000_000.0)

    results = [
        await service.transfer("USDC", "0xA", f"0xB{i}", 500_000.0)
        for i in range(12)
    ]

    assert any(r.get("status") == "blocked" for r in results), (
        "the rate limiter never fired across 12 large transfers"
    )


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


async def test_an_unfunded_ledger_still_refuses_a_transfer():
    """THE MEASUREMENT THAT MADE 15-A DISARMED. Nothing in production can fund a
    balance, so the fabricated 'completed' was unreachable — disarmed by ABSENCE
    OF A FUNDING PATH rather than by configuration, which is a distinct reason
    from the config-caused entries in domain 14."""
    service = StablecoinService({})

    result = await service.transfer("USDC", "0xA", "0xB", 100.0)

    assert result["status"] == "error"
    assert "insufficient balance" in result["error"].lower()
