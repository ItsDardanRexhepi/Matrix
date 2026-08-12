"""NEW-92/93 — the valuation says what it measured; the arming condition is written.

NEW-92 — `estimate_value` names its evidence.
Rarity and creator reputation are neutral CONSTANTS (1.0 and 0.5), carrying
0.30 + 0.15 of the declared weight, while floor carries a further 0.25 from a
store whose only writer (`update_floor_price`) has zero callers. So up to 70% of
a "weighted multi-factor" valuation could rest on nothing observed, and the
response gave no way to tell.

THE SETTERS ARE DELIBERATELY NOT WIRED. `estimate_value` returns a price a user
acts on IMMEDIATELY — unlike insurance's risk score, which only gates
eligibility. Wiring `update_floor_price`/`update_creator_score` would move it
from visibly low-confidence to CONFIDENTLY WRONG over a scoring path no one has
validated. Arming dead machinery is worse here than leaving it dead.

AND THE CAP WAS ACCIDENTAL. Confidence could never exceed 0.6 because
`_calculate_confidence`'s `has_floor` branch is unreachable while `_floor_prices`
stays empty. That truncation was doing the disclosure's job BY ACCIDENT, and an
accident is not a control — it would not survive someone "improving" the cap.
Now the response states the measured fraction outright.

NEW-93 — the arming condition, and the clause unique to this domain.
One key, `nft.contract_address`, arms SEVEN gated fabrications at once. What
makes this different from every prior arming condition: a false claim about
money is contradicted by a balance; a false claim about PROPERTY, with no title
record on either side, is contradicted by nothing. This platform holds no
ownership record — `_collections` is a cache that is never written — and
ownership lives on-chain in a contract that is not deployed.
"""

from __future__ import annotations

import pathlib

import pytest

from runtime.blockchain.services.nft_services.service import NFTService
from runtime.blockchain.services.nft_services.valuation import ValuationEngine

SERVICE_SRC = (
    pathlib.Path(__file__).resolve().parent.parent
    / "runtime/blockchain/services/nft_services/service.py"
)


# ── NEW-92 ───────────────────────────────────────────────────────────────


async def test_a_valuation_with_no_data_says_so():
    """SCENARIO: fresh engine. Pre-fix it returned a number and a confidence
    label with no way to tell that nothing was measured."""
    result = await ValuationEngine({}).estimate_value("0xC", 1)

    assert result["measured_weight_fraction"] == 0
    assert set(result["unmeasured_factors"]) == {
        "floor_price", "recent_sales", "collection_volume",
        "rarity", "creator_reputation",
    }
    assert "0% of the declared weight" in result["disclosure"]
    assert "not a price" in result["disclosure"]


async def test_the_constants_are_named_as_unmeasured_even_with_data():
    """SCENARIO: a real sale recorded. Two factors become measured; rarity and
    creator reputation must STILL be listed as unmeasured, because they are
    constants regardless of how much sales data arrives."""
    engine = ValuationEngine({})
    engine.record_sale("0xC", 1, 5.0)
    result = await engine.estimate_value("0xC", 1)

    assert result["estimated_value_eth"] > 0
    assert result["measured_factors"]["recent_sales"] is True
    assert result["measured_factors"]["collection_volume"] is True
    assert result["measured_factors"]["rarity"] is False
    assert result["measured_factors"]["creator_reputation"] is False
    assert "rarity" in result["unmeasured_factors"]
    assert "creator_reputation" in result["unmeasured_factors"]


async def test_the_measured_fraction_is_derived_not_asserted():
    """It must be computed from the weights, so it moves when they move."""
    engine = ValuationEngine({})
    engine.record_sale("0xC", 1, 5.0)
    result = await engine.estimate_value("0xC", 1)

    expected = engine._weights["recent_sales"] + engine._weights["collection_volume"]
    assert result["measured_weight_fraction"] == pytest.approx(expected, rel=1e-6)


async def test_the_floor_setter_is_still_not_wired():
    """THE DELIBERATE NON-FIX, pinned.

    If someone wires update_floor_price, this fails — which is the moment to
    re-read why it was left dead: estimate_value returns a price a user acts on,
    and the scoring path has never been validated against real data.
    """
    import ast
    import inspect

    src = inspect.getsource(ValuationEngine)
    calls = [
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call)
        and getattr(n.func, "attr", None) in ("update_floor_price", "update_creator_score")
    ]
    assert not calls, (
        "a valuation setter is now being called — read the NEW-92 note before "
        "accepting this: wiring it moves estimate_value from visibly "
        "low-confidence to confidently wrong"
    )


# ── NEW-93 ───────────────────────────────────────────────────────────────


def test_the_gating_condition_is_present_and_names_all_five_clauses():
    """A condition a future developer never sees is not a control. It lives in
    the module they would edit to add the contract address."""
    text = SERVICE_SRC.read_text()

    assert "NFT GATING CONDITION" in text
    assert "LIFTING CONDITION" in text
    for clause in (
        "OWNERSHIP IS READABLE",
        "EITHER PERFORMS ITS OPERATION OR REFUSES",
        "FEED EVENT IS DERIVED FROM SETTLEMENT",
        "OWNERSHIP IS CHECKED BEFORE ACTING",
        "STILL DISCLOSES",
    ):
        assert clause in text, f"lifting condition missing clause: {clause}"


def test_each_clause_states_its_own_partial_state_failure_mode():
    """The coupling is the point — five requirements without per-clause
    consequences invites exactly the incremental arming it prevents."""
    text = SERVICE_SRC.read_text()
    assert text.count("PARTIAL-STATE FAILURE MODE") >= 5


def test_the_condition_states_what_makes_this_domain_different():
    """The clause that distinguishes this from insurance's arming condition."""
    text = SERVICE_SRC.read_text()
    assert "contradicted by a balance" in text
    assert "contradicted by nothing" in text
    assert "NEVER WRITTEN" in text


def test_no_ownership_store_exists_yet():
    """The premise of the whole condition, asserted rather than assumed.

    If `_collections` gains a writer, clause 1 may be satisfiable and this
    fails — which is the moment to re-read the condition, not to delete it.
    """
    factory_src = (
        SERVICE_SRC.parent / "factory.py"
    ).read_text()
    writes = [
        ln for ln in factory_src.splitlines()
        if "_collections[" in ln and "=" in ln and not ln.strip().startswith("#")
    ]
    assert not writes, (
        f"_collections now has a writer: {writes}. Re-read the NFT GATING "
        "CONDITION — clause 1 may now be satisfiable."
    )


async def test_the_seven_still_refuse_and_are_unchanged():
    """SCOPE. NEW-92/93 changed a valuation response and added a comment block.
    None of the seven gated fabrications was touched."""
    svc = NFTService({})
    svc._web3.available = False
    for coro in (
        svc.fractionalize("0xC", 1, 10, 1.0),
        svc.rent("0xC", 1, "0xR", 7, 1.0),
        svc.batch_mint("0xC", "0xA", 2, {}),
        svc.royalty_claim("0xC", 1, "0xA"),
        svc.bridge_nft("0xC", 1, "base", "0xA"),
        svc.mint_soulbound("0xI", "0xR", {}),
        svc.dynamic_update("0xC", 1, {}),
    ):
        assert (await coro)["status"] == "not_deployed"
