"""NEW-96 — the shadow pool manager, the misspelled key, and the third 0.0.

THREE INDEPENDENT CAUSES OF ONE VISIBLE NUMBER. The dashboard showed a staking
APY of 0.0 for a funded position, and it would have kept showing 0.0 after any
one or two of these were fixed:

  1. THE SHADOW. `APYCalculator.calculate_apy` constructed a fresh
     `StakingPoolManager` on every call and read ITS default pool, whose
     `total_staked` is 0.0, while the service's real manager held the actual
     total. Two objects of the same class, different state, and the yield was
     always computed from the empty one. `get_position` returned the real
     position and the shadow's APY in a single response.

  2. THE KEY. `aggregator.py` read `apy_data["apy"]`. The calculator has always
     returned `current_apy`. The evidence that this is a MISSPELLING and not a
     second convention: the service's own caller,
     `StakingService.get_position`, reads `current_apy` from the same
     calculator. One producer, two call sites, one of them wrong.

  3. THE EXCEPT. A bare `except Exception:` substituted 0.0 for any failure.

THAT IS WHY THIS IS ONE COMMIT. Fix the shadow alone and the dashboard still
reads the wrong key: 0.0. Fix the key alone and the shadow still returns 0.0.
A correct fix that changes nothing a user can see is a fix that gets reverted.

AND 0.0 WAS NEVER A SAFE DEFAULT — the honest behaviour already existed
downstream and was being unmade by its caller, the same shape as NEW-90.
`formatters.py` reads `if apy is not None:` and omits the yield sentence
entirely when it does not know. The aggregator's 0.0 forced it to print "Your
current annual yield is 0.0%" — a fabricated yield claim — over a component
already written to stay silent.

THE TESTS ASSERT THE NUMBER ARRIVES AT THE DASHBOARD, not that the calculator
returns it. Asserting on `calculate_apy`'s return would have passed throughout
the entire life of defect 2, which is precisely the distinction between testing
the fix and testing the outcome.
"""

from __future__ import annotations

import inspect

import pytest

from runtime.blockchain.services.dashboard.aggregator import DashboardAggregator
from runtime.blockchain.services.dashboard.formatters import PlainEnglishFormatter
from runtime.blockchain.services.staking.apy_calculator import APYCalculator
from runtime.blockchain.services.staking.service import StakingService
from runtime.blockchain.web3_manager import Web3Manager


@pytest.fixture(autouse=True)
def _restore_shared_web3():
    shared = Web3Manager.get_shared({})
    before = (shared.available, shared.is_placeholder)
    yield
    shared.available, shared.is_placeholder = before


def _armed_staking() -> StakingService:
    svc = StakingService({})
    svc._web3.available = True
    svc._web3.is_placeholder = lambda _a: False
    return svc


async def _portfolio(svc: StakingService, address: str) -> dict:
    agg = DashboardAggregator({}, {"staking": svc})
    return await agg.aggregate_portfolio(address)


def _entry(portfolio: dict) -> dict:
    positions = portfolio["staking_positions"]
    assert len(positions) == 1, f"expected one staking position, got {positions}"
    return positions[0]


# ── The outcome: a real yield reaches the dashboard ──────────────────────


async def test_a_funded_position_shows_a_real_apy_on_the_dashboard():
    """THE TEST THAT MATTERS. Pre-fix this read 0.0 for all three reasons.

    It asserts on the dashboard's own output, so it stays honest if someone
    later changes which key the aggregator reads, or reintroduces a throwaway
    manager, or swallows an error back to a default.
    """
    svc = _armed_staking()
    await svc.stake("0xalice", 100.0)

    entry = _entry(await _portfolio(svc, "0xalice"))

    assert entry["apy"] is not None, "the dashboard still cannot see an APY"
    assert entry["apy"] > 0.0, (
        f"the dashboard shows apy={entry['apy']} for a funded pool — one of "
        "the three causes of the 0.0 is back"
    )
    assert "apy_unavailable" not in entry


async def test_the_dashboard_number_equals_the_calculator_for_the_real_pool():
    """The value must be the SERVICE'S pool's APY, not merely non-zero.

    A throwaway manager returning some other non-zero number would satisfy the
    test above; this pins the identity.
    """
    svc = _armed_staking()
    await svc.stake("0xalice", 100.0)

    direct = await svc.apy_calculator.calculate_apy("default")
    entry = _entry(await _portfolio(svc, "0xalice"))

    assert entry["apy"] == pytest.approx(direct["current_apy"])
    assert direct["total_staked"] == 100.0, (
        "the calculator is not reading the service's pool — total_staked "
        f"{direct['total_staked']} should be the 100.0 that was staked"
    )


async def test_the_calculator_reads_the_services_pool_object_itself():
    """Cause 1, at the root. Identity, not just equality of a number."""
    svc = _armed_staking()
    assert svc.apy_calculator._pools is svc.pools

    src = inspect.getsource(APYCalculator.calculate_apy)
    assert "StakingPoolManager(" not in src, (
        "calculate_apy constructs a pool manager again — that is the shadow"
    )


def test_the_calculator_cannot_be_built_without_a_pool_manager():
    """An optional parameter would let the defect return as a convenience."""
    with pytest.raises(TypeError):
        APYCalculator({})


# ── Cause 2: the key ─────────────────────────────────────────────────────


async def test_the_aggregator_reads_the_key_the_calculator_writes():
    """The producer emits `current_apy`; nothing emits `apy`.

    Driven rather than grepped: a calculator that returns ONLY `current_apy`
    must still reach the dashboard.
    """
    svc = _armed_staking()
    await svc.stake("0xalice", 100.0)

    async def only_current_apy(_pool_id):
        return {"pool_id": "default", "current_apy": 7.5}

    svc.apy_calculator.calculate_apy = only_current_apy
    entry = _entry(await _portfolio(svc, "0xalice"))

    assert entry["apy"] == 7.5


async def test_the_service_and_the_dashboard_read_the_same_key():
    """The evidence that `apy` was a misspelling: get_position — the service's
    own caller of the same calculator — has always read `current_apy`. If the
    two ever disagree again, one of them is wrong."""
    svc = _armed_staking()
    await svc.stake("0xalice", 100.0)

    position = await svc.get_position("0xalice")
    entry = _entry(await _portfolio(svc, "0xalice"))

    assert position["current_apy"] == pytest.approx(entry["apy"])


# ── Cause 3: the substituted zero ────────────────────────────────────────


async def test_a_failed_calculation_is_not_reported_as_zero_percent():
    """A raise must not become a yield of 0.0."""
    svc = _armed_staking()
    await svc.stake("0xalice", 100.0)

    async def boom(_pool_id):
        raise RuntimeError("price feed down")

    svc.apy_calculator.calculate_apy = boom
    entry = _entry(await _portfolio(svc, "0xalice"))

    assert entry["apy"] is None, "a failure is being reported as 0.0% yield"
    assert "price feed down" in entry["apy_unavailable"]


async def test_a_refusal_is_not_reported_as_zero_percent():
    """The NEW-94 path: an undeployed domain refuses, and a refusal dict has no
    `current_apy`. Pre-fix `.get("apy", 0.0)` turned that into 0.0 too."""
    svc = StakingService({})
    svc._web3.available = True
    svc._web3.is_placeholder = lambda _a: False
    await svc.stake("0xalice", 100.0)

    svc._web3.available = False           # domain goes dark
    entry = _entry(await _portfolio(svc, "0xalice"))

    assert entry["apy"] is None
    assert entry["apy_unavailable"] == "not_deployed"


async def test_an_unknown_pool_is_an_error_not_a_yield_of_zero():
    """`except Exception: pool = {}` inside the calculator turned an unknown
    pool into APY 0.0 — a number, indistinguishable from a real zero yield."""
    svc = _armed_staking()
    result = await svc.apy_calculator.calculate_apy("no_such_pool")

    assert result["status"] == "error"
    assert result["current_apy"] is None
    assert "not found" in result["error"]


# ── What the repoint ARMED ───────────────────────────────────────────────
#
# Found by adversarial review of this change, not by the tests above, which
# were green while carrying the crash.
#
# The compound-APY expression had NEVER EXECUTED. The shadow forced
# `total_staked` to 0.0 on every call, so `if total_staked <= 0` short-circuited
# every time and the `else` branch was dead code for the entire life of the
# defect. Repointing at the real pool ran it for the first time — and it raised
# OverflowError, because `daily_yield = reward_rate / total_staked` is unbounded
# and `min(apy, 10_000.0)` was applied AFTER the exponentiation, where it can
# never see a value that overflowed on the way in.
#
# FIXING A SHADOW ARMS WHATEVER THE SHADOW WAS HIDING. That is the
# arming-dead-machinery hazard reached by REPAIR rather than by configuration,
# and it is the reason a repoint is not a free operation even when the target
# is clean.


async def test_a_small_pool_does_not_crash_the_position_read():
    """THE REGRESSION THE REPOINT INTRODUCED, driven exactly as reported.

    Stake the 1 ETH minimum, take an ordinary partial exit, read your position.
    Pre-repoint this returned (a wrong 0.0). Post-repoint, before this fix, it
    raised OverflowError out of `get_position`, which has no try/except around
    the calculator — so the user could not read their own position at all.
    """
    svc = _armed_staking()
    await svc.stake("0xalice", 1.0)
    await svc.unstake("0xalice", 0.96)

    pool = await svc.pools.get_pool("default")
    assert pool["total_staked"] < 0.05, "this case no longer exhibits a tiny pool"

    position = await svc.get_position("0xalice")     # must not raise
    assert position["current_apy"] == 10_000.0, (
        "an extreme-but-finite yield must report the cap, not crash and not "
        "a fabricated zero"
    )


async def test_a_high_configured_reward_rate_does_not_crash_a_healthy_pool():
    """The threshold is `total_staked < ~0.4886 * reward_rate`, so this is not
    only a dust-pool problem: at a configured rate of 100, a 40 ETH pool is
    inside the overflow band."""
    svc = StakingService({"staking": {"default_reward_rate": 100.0}})
    svc._web3.available = True
    svc._web3.is_placeholder = lambda _a: False
    await svc.stake("0xbob", 40.0)

    position = await svc.get_position("0xbob")       # must not raise
    assert position["current_apy"] == 10_000.0


async def test_the_apy_is_unchanged_for_ordinary_pools():
    """The overflow fix must not move any number a user would already have
    seen. Computed in log space now; below the cap it must equal the original
    expression to floating-point tolerance."""
    import math

    for staked, rate in ((100.0, 0.1), (1000.0, 0.1), (10.0, 0.1)):
        svc = StakingService({"staking": {"default_reward_rate": rate}})
        svc._web3.available = True
        svc._web3.is_placeholder = lambda _a: False
        await svc.stake("0xalice", staked)

        result = await svc.apy_calculator.calculate_apy("default")

        daily = (rate / staked) * 0.95
        n = 365
        # `calculate_apy` reports round(apy, 4), so the reference is rounded
        # the same way — comparing a rounded value to an unrounded one at
        # rel=1e-9 would fail on correct code, which it did when first written.
        expected = round(
            min(((1 + daily / n) ** (n * 365) - 1) * 100.0, 10_000.0), 4
        )
        assert result["current_apy"] == pytest.approx(expected, rel=1e-9), (
            f"the APY moved for staked={staked} rate={rate}"
        )
        assert not math.isnan(result["current_apy"])


def test_the_cap_binds_before_the_exponentiation_not_after():
    """STRUCTURAL, because the numeric tests above pass either way once the
    inputs are inside the representable range.

    `min(...)` applied after `**` cannot protect against an overflow that
    happens computing its argument. If someone restores the direct form, this
    fails.
    """
    import ast
    import inspect

    # AST-unparsed, so COMMENTS ARE STRIPPED. The comment block in
    # calculate_apy quotes the old expression verbatim to explain the fix, and
    # a raw-source grep matches its own explanation — the docstring-vs-live-code
    # trap this suite has now hit three times.
    src = ast.unparse(
        ast.parse(inspect.getsource(APYCalculator.calculate_apy).strip())
    )
    assert "** (n * 365)" not in src, (
        "the direct exponentiation is back — it overflows for "
        "total_staked < ~0.4886 * reward_rate, and the cap after it cannot help"
    )
    assert "math.log1p" in src and "math.exp" in src


# ── The downstream component that was already honest ─────────────────────


def test_the_formatter_omits_the_yield_when_it_does_not_know():
    """The behaviour the 0.0 default was overwriting.

    This is why `None` and not `0.0`: the honest path was written, downstream,
    and its caller unmade it — the NEW-90 shape.
    """
    fmt = PlainEnglishFormatter()

    unknown = fmt.format_staking_info(
        {"staked_amount": 10.0, "pool_id": "default", "apy": None}
    )
    assert "annual yield" not in unknown, (
        "the formatter is inventing a yield sentence for an unknown APY"
    )
    assert "0.0%" not in unknown

    known = fmt.format_staking_info(
        {"staked_amount": 10.0, "pool_id": "default", "apy": 5.2}
    )
    assert "5.2%" in known, "the formatter no longer reports a known APY"


async def test_a_real_apy_survives_all_the_way_into_the_rendered_summary():
    """END TO END: pool -> calculator -> aggregator -> formatter -> text.

    The whole chain in one assertion, because every defect in this commit lived
    at a join between two of those stages.
    """
    svc = _armed_staking()
    await svc.stake("0xalice", 100.0)

    entry = _entry(await _portfolio(svc, "0xalice"))
    summary = PlainEnglishFormatter().format_staking_info(entry)

    assert "annual yield" in summary
    assert "0.0%" not in summary, "a fabricated zero yield reached the text"
    assert f"{entry['apy']:.1f}%" in summary
