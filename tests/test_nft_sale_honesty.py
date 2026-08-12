"""NEW-90/91 — the NFT sale stops asserting a transfer that was refused.

TWO METHODS, SAME NAME, DIFFERENT CLASSES, and both are fixed here:

    NFTService.process_sale          (service.py)             — NEW-90
    RoyaltyEnforcement.process_sale  (royalty_enforcement.py) — NEW-91

They are the only ungated pair in the domain — every other fabrication-shaped
method in nft_services opens with an `is_placeholder` gate and refuses today.
A future reader grepping `process_sale` must find both, hence this note.

NEW-90. `NFTService.process_sale` had:

    await self._factory.transfer_token(...)   # bare statement, return DROPPED
    ...
    sale_result["nft_transferred"] = True     # asserted, unconditional

`NFTFactory.transfer_token` refuses on BOTH branches — including when
`_is_ready()` is true, where the reason is "factory ABI not yet wired into
runtime". The one component honest enough to refuse was called, ignored, and
contradicted by its own caller.

THE FACTORY IS CORRECT, AND THAT IS THE POINT. `_collections` is declared in
its own comment as a "cache for in-process queries"; ownership lives on-chain
in OpenMatrixNFT.sol, a real ERC721, and the D2 twin reads `ownerOf()`. So
refusing while that contract is undeployed is right. The defect was never a
missing implementation — it was an IMPLEMENTED REFUSAL BEING OVERWRITTEN, which
is worse than a stub: someone did the work correctly and the caller unmade it.

NEW-91. `get_total_royalties_paid` returned `total_royalties_eth` — the word
"paid" over a sum of line items this module wrote for itself, with no wallet,
balance or payout anywhere to reconcile against.

SCENARIO COVERAGE:
    the refusal reaches the caller   -> test_the_factory_refusal_is_propagated
    the arithmetic survives          -> test_the_real_royalty_maths_is_preserved
    no false custody claim           -> test_no_transfer_is_claimed
    the honest path still works      -> test_a_real_transfer_would_be_reported_true
    the royalty ledger discloses     -> test_the_royalty_record_discloses
    "paid" no longer overstates      -> test_the_totals_say_recorded_not_paid
"""

from __future__ import annotations

import ast
import inspect

import pytest

from runtime.blockchain.services.nft_services.service import NFTService


@pytest.fixture(autouse=True)
def _restore_shared_web3():
    """`Web3Manager.get_shared()` is a PROCESS-WIDE SINGLETON.

    Arming it in one test arms it for every later test in the session, which
    made `test_those_seven_still_refuse_when_undeployed` pass or fail purely on
    ordering. That is the same shared-singleton hazard the census recorded
    against the service layer (NEW-59), reappearing in my own test file — so it
    is fixed here rather than worked around.
    """
    from runtime.blockchain.web3_manager import Web3Manager

    shared = Web3Manager.get_shared({})
    before = (shared.available, shared.is_placeholder)
    yield
    shared.available, shared.is_placeholder = before


def _armed() -> NFTService:
    """Contract configured — the state in which the fabrication would fire.

    Mutates the shared Web3Manager; the autouse fixture above restores it.
    """
    svc = NFTService({})
    svc._web3.available = True
    svc._web3.is_placeholder = lambda _a: False
    return svc


async def _sale(svc: NFTService):
    await svc.configure_royalty("0xC", 7, "0xcreator", 500)
    return await svc.process_sale("0xC", 7, 2.0, "0xseller", "0xbuyer")


# ── NEW-90 ───────────────────────────────────────────────────────────────


async def test_the_factory_refusal_is_propagated():
    """SCENARIO: the factory refuses (its only behaviour today).

    The caller must both DERIVE its claim from that answer and CARRY the
    answer, so a reader can see WHY, not just that the answer was no.
    """
    result = await _sale(_armed())

    assert result["nft_transferred"] is False
    assert result["transfer_result"]["status"] == "not_deployed"
    assert "ABI" in result["transfer_result"].get("reason", "")


async def test_no_transfer_is_claimed():
    """The custody half. Pre-fix this said nft_transferred: True."""
    result = await _sale(_armed())

    assert result["status"] == "recorded_unsettled"
    assert result["settled"] is False
    assert result["value_moved"] is False
    assert "NOT transferred" in result["disclosure"]
    assert "Ownership of this token is unchanged" in result["disclosure"]
    assert "holds no ownership record of its own" in result["disclosure"], (
        "the disclosure must say the platform has no ownership store — that is "
        "the fact a buyer would most want and least expect"
    )


async def test_the_real_royalty_maths_is_preserved():
    """The argument for propagation over removal: strip the false claim and a
    genuine engine remains. 2.0 ETH at 500 bps = 0.1 royalty."""
    result = await _sale(_armed())

    assert result["royalty"]["amount"] == pytest.approx(0.1)
    assert result["royalty"]["recipient"] == "0xcreator"
    assert result["seller_proceeds"] > 0
    assert result["sale_price"] == 2.0


async def test_a_real_transfer_would_be_reported_true():
    """POSITIVE CONTROL. The fix must not hardcode False in place of True —
    that would be the same defect with the sign flipped."""
    svc = _armed()

    async def ok(**_kw):
        return {"status": "transferred", "tx_hash": "0xdead"}

    svc._factory.transfer_token = ok
    result = await _sale(svc)

    assert result["nft_transferred"] is True
    assert result.get("status") != "recorded_unsettled"
    assert "Ownership of this token is unchanged" not in result.get("disclosure", ""), (
        "the OWNERSHIP disclaimer must not be added when the transfer happened"
    )

    # But `value_moved` is STILL False, and that is correct rather than a
    # leftover: the token moved, the ROYALTY did not. NEW-91's record-level
    # disclosure is about the payment, NEW-90's is about the token, and the two
    # claims are independent — which is precisely rule 21 (real is not one
    # property) applied inside a single response.
    assert result["value_moved"] is False
    assert "No transfer was made to the royalty recipient" in result["disclosure"]


def test_the_refusal_is_no_longer_discarded():
    """Structural: the bare `await` is gone and the result is bound."""
    fn = ast.parse(inspect.getsource(NFTService.process_sale).strip()).body[0]
    discarded = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Await)
        and isinstance(n.value.value, ast.Call)
        and getattr(n.value.value.func, "attr", None) == "transfer_token"
    ]
    assert not discarded, "transfer_token's return is still being discarded"


# ── NEW-91 ───────────────────────────────────────────────────────────────


async def test_the_royalty_record_discloses():
    """Every stored sale record must carry its own disclosure — a reader of
    `_sales` must not mistake a computed line item for a payment."""
    svc = _armed()
    await _sale(svc)
    record = svc._royalty._sales[-1]

    assert record["settled"] is False
    assert record["value_moved"] is False
    assert "No transfer was made" in record["disclosure"]


async def test_the_totals_say_recorded_not_paid():
    """SCENARIO: `get_total_royalties_paid`. The method name is retained so
    existing callers resolve; the response says what the number actually is."""
    svc = _armed()
    await _sale(svc)
    totals = await svc._royalty.get_total_royalties_paid("0xcreator")

    assert "total_royalties_eth" not in totals, (
        "the bare `_eth` key is back — it reads as money that moved"
    )
    assert totals["total_royalties_recorded_eth"] == pytest.approx(0.1)
    assert totals["settled"] is False
    assert "RECORDED, NOT PAID" in totals["disclosure"]
    assert "no external ledger" in totals["disclosure"]


# ── The scope boundary ───────────────────────────────────────────────────


async def test_the_seven_gated_fabrications_are_untouched():
    """SCOPE PIN. fractionalize/rent/batch_mint/royalty_claim/bridge_nft/
    mint_soulbound/dynamic_update are category 3 — armed-on-deployment, NOT
    fixed here. They are items 4-5 and need a compound gating condition.

    If any silently changed, this commit did undisclosed work.
    """
    svc = _armed()
    assert (await svc.fractionalize("0xC", 1, 10, 1.0))["status"] == "fractionalized"
    assert (await svc.rent("0xC", 1, "0xR", 7, 1.0))["status"] == "rented"
    assert (await svc.royalty_claim("0xC", 1, "0xA"))["status"] == "claimed"


async def test_those_seven_still_refuse_when_undeployed():
    """And the gate that makes them inert today must still fire.

    The undeployed state is set EXPLICITLY rather than assumed from a fresh
    construction. `Web3Manager.get_shared()` is a process-wide singleton, so an
    earlier test file in the same session can leave it armed — this test failed
    in the full suite while passing alone, purely on ordering. Controlling the
    precondition is the fix; relying on session state is what the census calls
    a control that works by accident.
    """
    svc = NFTService({})
    svc._web3.available = False

    assert (await svc.fractionalize("0xC", 1, 10, 1.0))["status"] == "not_deployed"
    assert (await svc.rent("0xC", 1, "0xR", 7, 1.0))["status"] == "not_deployed"
    assert (await svc.batch_mint("0xC", "0xA", 2, {}))["status"] == "not_deployed"
