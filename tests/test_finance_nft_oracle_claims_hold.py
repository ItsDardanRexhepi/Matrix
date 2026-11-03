"""Finance, NFT and oracle services, held to what they claim.

Built true:
  * auctions "never fabricate scaling" — floats were scaled by 10**18 for any
    token, and a non-number became 0;
  * loans "refuse, do not coerce" a ratio — a non-positive or NaN borrow price
    made it 0; liquidation "leaves debt as it is" — a refused call accrued
    into the stored loan, and so did a `check_`;
  * DeFi "two writes, one of which can fail" — both could, and an unaccepted
    collateral token left an ACTIVE loan with no collateral; and the borrow
    position "cannot disagree" with the loans — it was set from one loan;
  * the DEX's "users pay nothing" — the pool's LP fee was taken while the
    trade said 0, and a swap that moved nothing said `confirmed`;
  * NFT lending: `onBehalfOf` "must be the platform account", and a caller
    could name any beneficiary; breed_nft's contract override is named in the
    module docstring, and a user session is refused it;
  * a quote for a predicate the platform would refuse now says so;
  * mint's royalty/rights writes are caught when refused, after the mint;
  * the oracle cache "never caches VRF" whatever the config, and a miss is
    fetched once per key;
  * the VRF provider no longer reports a request it never sent as pending;
  * TBA execution acts only on accounts the operator lists;
  * set_balance "refuses outside tests" — an env switch opened it anywhere.

Corrected: MPC's and NFT lending's "only sponsors gas", the NFT rights rule's
scope, royalty "enforcement", the NFT feed note, the insurance guard's "one
name", the fee engine that "never reads" the predicate, the oracle gateway's
"single entry point", an ABI comment, the staking gate's "fourteen", the
arming note's "today", and x402's owner and attestation promises.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import time

import pytest


def _prose(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\s*#\s*", " ", text or ""))


# ── auctions ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [1.5, "one", None, True])
def test_an_amount_that_is_not_a_base_unit_integer_is_refused(bad):
    from runtime.blockchain.services.auctions.service import AuctionService

    with pytest.raises(ValueError):
        AuctionService({})._to_wei(bad)
    assert AuctionService({})._to_wei(1_500_000) == 1_500_000
    assert AuctionService({})._to_wei("7") == 7


# ── loans ──────────────────────────────────────────────────────────────────

CONFIG = {"defi": {"fallback_prices": {"ETH": 2000.0, "USDC": 1.0}}}


@pytest.fixture
def defi(monkeypatch):
    from runtime.blockchain.services.defi import DeFiService

    svc = DeFiService(CONFIG)
    monkeypatch.setattr(svc._web3, "available", True)
    monkeypatch.setattr(svc._web3, "is_placeholder", lambda _a: False)
    return svc


async def test_a_zero_borrow_price_is_refused_not_a_ratio_of_zero(defi):
    lm = defi._loan_manager
    lm._min_collateral_ratio = 0.0          # the config the minimum hid behind
    with pytest.raises(ValueError):
        await lm.create_loan(borrower="0xA", collateral_token="ETH",
                             collateral_amount=1.0, borrow_token="USDC",
                             borrow_amount=100.0, collateral_price=2000.0,
                             borrow_price=0.0)


async def test_a_refused_liquidation_does_not_touch_the_loan(defi):
    loan = await defi.create_loan("0xA", "ETH", 10.0, "USDC", 1000.0)
    stored = defi._loan_manager._loans[loan["loan_id"]]
    stored["last_interest_update"] = int(time.time()) - 30 * 86400
    before = (stored["accrued_interest"], stored["last_interest_update"])

    with pytest.raises(ValueError):
        await defi._loan_manager.liquidate(loan["loan_id"], 2000.0, 1.0)
    await defi._loan_manager.check_liquidation_eligibility(loan["loan_id"], 2000.0, 1.0)

    after = (stored["accrued_interest"], stored["last_interest_update"])
    assert after == before, f"a refused liquidation / a check wrote the loan: {before} -> {after}"


async def test_an_unaccepted_collateral_token_opens_no_loan(defi):
    defi._loan_manager._pool_total = {}
    lm = defi._loan_manager
    count = len(lm._loans)

    async def _price(token):
        return {"SOL": 50.0, "USDC": 1.0}[token]

    defi._get_token_price = _price
    with pytest.raises(ValueError):
        await defi.create_loan("0xA", "SOL", 100.0, "USDC", 1000.0)
    assert len(lm._loans) == count, "an ACTIVE loan was recorded with no collateral"


async def test_the_borrow_position_covers_every_active_loan(defi):
    first = await defi.create_loan("0xA", "ETH", 10.0, "USDC", 1000.0)
    await defi.create_loan("0xA", "ETH", 10.0, "USDC", 500.0)
    await defi.repay_loan(first["loan_id"], 100.0)
    position = defi._collateral_manager._borrows["0xA"]["USDC"]
    expected = defi._loan_manager.outstanding_principal("0xA", "USDC")
    assert position == pytest.approx(expected)
    assert position > 1000.0, (
        f"repaying one loan erased the other from the position: {position}")


# ── the DEX ────────────────────────────────────────────────────────────────

async def test_a_swap_says_it_moved_nothing_and_names_the_pool_fee(monkeypatch):
    from runtime.blockchain.services.dex.service import DEXService

    dex = DEXService({"dex": {"router_contract": "0x" + "11" * 20}})
    monkeypatch.setattr(dex._web3, "available", True)
    monkeypatch.setattr(dex._web3, "is_placeholder", lambda _a: False)
    pool = await dex.pools.create_pool("ETH", "USDC")
    await dex.pools.add_liquidity(pool["pool_id"], "0xLP", 100.0, 200_000.0)
    trade = await dex.swap("0xT", "ETH", "USDC", 1.0, slippage=5.0)
    assert trade["status"] == "recorded_unsettled" and trade["value_moved"] is False
    assert trade["platform_fee"] == 0.0
    assert sum(f["amount"] for f in trade["pool_fees"]) > 0
    assert "user_fee" not in trade
    assert "Gas costs are absorbed by the platform. Users pay nothing for swaps." \
        not in _prose(DEXService.__doc__)


# ── NFT lending, MPC ───────────────────────────────────────────────────────

class _Account:
    address = "0x" + "aa" * 20


async def test_a_loan_cannot_name_another_beneficiary(monkeypatch):
    from runtime.blockchain.services.nft_lending.service import NFTLendingService

    svc = NFTLendingService({"services": {"nft_lending": {
        "pool_address": "0x" + "01" * 20, "reserve_asset": "0x" + "02" * 20}}})
    monkeypatch.setattr(svc._web3, "available", True)
    monkeypatch.setattr(svc._web3, "get_account", lambda: _Account())
    monkeypatch.setattr(svc._web3, "load_contract", lambda *a, **k: object())
    monkeypatch.setattr(svc._web3, "w3", type("W3", (), {
        "to_checksum_address": staticmethod(lambda a: a)})(), raising=False)
    out = await svc.borrow_against_nft(nft_asset="0x" + "03" * 20, nft_token_id=1,
                                       amount=1, on_behalf_of="0x" + "bb" * 20)
    assert out.get("refused") is True


def test_the_breeding_override_is_named_and_refused_to_a_session():
    """breed_nft takes its contract from the caller as well as from config, so
    the config gate is not the whole story: the module docstring says so, and
    a user session is refused the action (the operator's key keeps it)."""
    from runtime.access_policy import REFUSED_TO_A_SESSION
    from runtime.blockchain.services.nft_lending import service as lending

    assert ("nft_lending", "breed_nft") in REFUSED_TO_A_SESSION
    doc = _prose(lending.__doc__)
    assert "breed_nft`` also takes a ``breed_contract`` from its caller" in doc


def test_the_platform_is_named_as_the_sender_not_a_sponsor():
    from runtime.blockchain.services.mpc import service as mpc
    from runtime.blockchain.services.nft_lending import service as lending

    for mod in (mpc, lending):
        src = _prose(inspect.getsource(mod))
        assert "only SPONSORS the gas" not in src and "only sponsors gas" not in src


# ── insurance, NFT rights and royalties ────────────────────────────────────

async def test_a_quote_for_an_unissuable_predicate_says_so(monkeypatch):
    from runtime.blockchain.services.insurance.service import InsuranceService

    svc = InsuranceService({})
    monkeypatch.setattr(svc._web3, "available", True)
    monkeypatch.setattr(svc._web3, "is_placeholder", lambda _a: False)
    out = await svc.assess_risk("0xH", "weather", {
        "coverage_amount": 50_000, "metric": "timestamp", "threshold": 0})
    assert out["predicate_issuable"] is False and out["predicate_refusal"]


def test_the_nft_sentences_scope_what_they_claim():
    from runtime.blockchain.services.insurance import _guards, _predicate
    from runtime.blockchain.services.nft_services import rights, royalty_enforcement, service

    r = _prose(inspect.getsource(rights))
    assert "THIS IS NOT AN AUTHORITY CHECK, AND IS NOT WRITTEN AS ONE. Nothing here refuses." not in r
    assert "ensure royalties are paid on every NFT sale" not in _prose(royalty_enforcement.__doc__)
    s = _prose(inspect.getsource(service))
    assert "so every sale that transfers nothing is BROADCAST" not in s
    assert "except PermissionError as exc:" in inspect.getsource(service.NFTService.mint)
    assert "overrides exactly one name" not in _prose(inspect.getsource(_guards))
    assert "still chooses, and `FeeEngine.calculate_premium` never reads `metric`" \
        not in _prose(_predicate.__doc__)


# ── oracles ────────────────────────────────────────────────────────────────

def test_vrf_is_never_cached_whatever_the_config():
    from runtime.blockchain.services.oracle_gateway.cache import OracleCache

    assert OracleCache(ttls={"random_vrf": 60})._ttls["random_vrf"] == 0


async def test_one_miss_is_fetched_once():
    from runtime.blockchain.services.oracle_gateway.gateway import OracleGateway

    gw = OracleGateway({})
    calls = []

    async def slow(params):
        calls.append(1)
        await asyncio.sleep(0.01)
        return {"price": len(calls)}

    gw._dispatch = lambda oracle_type: slow
    a, b = await asyncio.gather(gw.request("price_feed", {"pair": "ETH/USD"}, caller="x"),
                                gw.request("price_feed", {"pair": "ETH/USD"}, caller="y"))
    assert len(calls) == 1, "two concurrent misses both fetched"
    assert a["price"] == b["price"]


async def test_the_vrf_provider_does_not_report_an_unsent_request_as_pending():
    from runtime.blockchain.services.oracle_gateway.vrf_provider import VRFProvider

    vrf = VRFProvider({"oracle": {"vrf": {"coordinator_address": "0x" + "05" * 20}}})
    out = await vrf.request_random(1)
    assert out["status"] == "not_implemented" and "request_id" not in out


def test_the_gateway_does_not_claim_to_be_the_only_entry_point():
    from runtime.blockchain.services.oracle_gateway import gateway

    # The docstring follows the module's `from __future__` import, so it is
    # not `__doc__`: read the source.
    src = _prose(inspect.getsource(gateway))
    assert "OracleGateway — single entry point for ALL oracle data across The Matrix." not in src


# ── TBA, stablecoin ────────────────────────────────────────────────────────

async def test_no_token_bound_account_is_operated_on_a_request(monkeypatch):
    """execute_as_tba signed a call the request composed, from the platform's
    wallet: it is refused for every account, before anything is built or
    signed, whatever the operator's config lists."""
    from runtime.blockchain.services.tba.service import TokenBoundAccountService as TBAService

    listed = "0x" + "06" * 20
    for cfg in ({"executable_accounts": [listed]}, {}):
        svc = TBAService({"services": {"tba": cfg}})
        monkeypatch.setattr(svc._web3, "available", True)
        for account in (listed, "0x" + "07" * 20):
            out = await svc.execute_as_tba(account=account, to="0x" + "08" * 20, value=1)
            assert out.get("status") == "refused", out


def test_no_environment_switch_opens_the_test_mint(monkeypatch):
    import sys

    from runtime.blockchain.services.stablecoin.service import StablecoinService

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("MATRIX_ALLOW_TEST_MINT", "1")
    monkeypatch.delitem(sys.modules, "pytest")
    with pytest.raises(RuntimeError):
        StablecoinService({}).set_balance("0xATTACKER", "USDC", 1_000_000.0)


# ── the remaining sentences ────────────────────────────────────────────────

def test_the_remaining_finance_sentences():
    from runtime.blockchain.services.oracles_plus import service as op
    from runtime.blockchain.services.staking import arming, service as staking
    from runtime.blockchain.services.x402_payments import limit_updater

    assert "fourteen sibling methods now use it too" not in _prose(inspect.getsource(staking))
    assert "is the *only* reason ``unstake``, ``claim_rewards`` and ``get_position`` are inert today" \
        not in _prose(arming.__doc__)
    assert "Ensures only authorised owners can update limits." not in _prose(limit_updater.__doc__)
    assert "# Minimal Pyth IPyth ABI — only the read functions this service calls." \
        not in inspect.getsource(op)
