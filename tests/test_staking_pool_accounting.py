"""NEW-95 — the pool-accounting cluster: a sign, a clamp, and a counter.

THE SERIOUS ONE IS THE SIGN. `remove_stake` computed

    pool["total_staked"] = max(0.0, pool["total_staked"] - amount)

with no check on `amount`. A negative amount SUBTRACTS A NEGATIVE, so the
withdrawal path was a deposit path. Driven against the live object before the
fix: 10.0 staked, `remove_stake(pool, -20.0)` -> `total_staked` 30.0. Twenty
ETH appeared in a pool total from a call whose name, docstring and only caller
all describe removing money, and nothing downstream would have contradicted it.

THE CLAMP IS THE SAME DEFECT WEARING A SAFETY BELT. `max(0.0, ...)` made
`remove_stake(pool, 100.0)` against 10.0 staked return normally with
`total_staked` 0.0 — the pool then disagreed with the sum of its positions, with
no error, no log, and no way for a reader to know. Clamping is not a check; it
is a check's silence. The `max(0.0, ...)` is retained as a float-drift floor
only, with the real check in front of it.

THE COUNTER, STATED HONESTLY. `staker_count` never decremented, and incremented
on every `add_stake` call rather than per staker — so three stakes from one
address read as three stakers, and a full withdrawal left the count untouched.
It is written in one place and read by NO non-test code in this repo, and none
in the iOS client. So this is a correctness fix to a PUBLISHED FIELD — it ships
inside every `get_pool`/`list_pools` record — not to a live denominator. Saying
otherwise would overstate the finding.

EVERY ASSERTION READS THE STORE, NOT THE RETURN. `remove_stake` both mutates
and returns, and the last domain produced a real bug that only a store-reading
test could catch (rule 43): NFTService.process_sale mutated the same dict object
the royalty ledger had already persisted, so asserting on the return would have
passed over a corrupted record.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.staking.pools import StakingPoolManager
from runtime.blockchain.services.staking.service import StakingService
from runtime.blockchain.web3_manager import Web3Manager


@pytest.fixture(autouse=True)
def _armed():
    """`Web3Manager.get_shared()` is a process-wide singleton (rule 45).

    NEW-95 is about arithmetic, so every test here runs ARMED — otherwise the
    NEW-94 gate refuses first and none of this code is reached.
    """
    shared = Web3Manager.get_shared({})
    before = (shared.available, shared.is_placeholder)
    shared.available = True
    shared.is_placeholder = lambda _a: False
    yield
    shared.available, shared.is_placeholder = before


def _pm() -> StakingPoolManager:
    return StakingPoolManager({})


async def _total(pm: StakingPoolManager) -> float:
    return pm._pools["default"]["total_staked"]


async def _count(pm: StakingPoolManager) -> int:
    return pm._pools["default"]["staker_count"]


# ── 1. The sign ──────────────────────────────────────────────────────────


async def test_a_negative_withdrawal_is_rejected_not_treated_as_a_deposit():
    """THE HEADLINE. Pre-fix this left total_staked at 30.0."""
    pm = _pm()
    await pm.add_stake("default", 10.0, new_staker=True)

    with pytest.raises(ValueError, match="must be positive"):
        await pm.remove_stake("default", -20.0)

    assert await _total(pm) == 10.0, (
        "a negative unstake changed the pool total — the withdrawal path is a "
        "deposit path again"
    )


async def test_the_refusal_names_what_used_to_happen():
    """The message must tell a reader why the check exists, not just that a
    number was out of range."""
    pm = _pm()
    await pm.add_stake("default", 10.0, new_staker=True)

    with pytest.raises(ValueError) as exc:
        await pm.remove_stake("default", -1.0)
    assert "INCREASED total_staked" in str(exc.value)


async def test_zero_is_rejected_on_both_sides():
    """Zero is not a withdrawal or a deposit; accepting it lets a caller churn
    staker_count without moving value."""
    pm = _pm()
    await pm.add_stake("default", 10.0, new_staker=True)

    with pytest.raises(ValueError):
        await pm.remove_stake("default", 0.0)
    with pytest.raises(ValueError):
        await pm.add_stake("default", 0.0)
    with pytest.raises(ValueError):
        await pm.add_stake("default", -5.0)

    assert await _total(pm) == 10.0


# ── 2. The clamp ─────────────────────────────────────────────────────────


async def test_over_withdrawal_is_rejected_not_silently_absorbed():
    """Pre-fix: total_staked went to 0.0 and the call returned normally."""
    pm = _pm()
    await pm.add_stake("default", 10.0, new_staker=True)

    with pytest.raises(ValueError, match="only 10.0 is staked"):
        await pm.remove_stake("default", 100.0)

    assert await _total(pm) == 10.0, (
        "the over-withdrawal was absorbed — the pool total no longer agrees "
        "with the sum of its positions and nothing said so"
    )


async def test_an_exact_full_withdrawal_is_allowed():
    """The check must reject MORE than is staked, not all of it — otherwise
    nobody could ever close a position."""
    pm = _pm()
    await pm.add_stake("default", 10.0, new_staker=True)
    await pm.remove_stake("default", 10.0, staker_exited=True)

    assert await _total(pm) == 0.0


async def test_the_tolerance_is_load_bearing_at_all():
    """A case where the pool total drifts BELOW a position.

    0.1 + 0.4 = 0.5; 0.5 - 0.4 = 0.09999999999999998. The remaining staker owns
    exactly 0.1 and the pool now believes it holds slightly less, so a bare
    `amount > total_staked` refuses an honest full withdrawal. Delete the
    tolerance term and this test fails — which the FIRST version of this file
    could not detect, because its drift case stacked 0.1 three times and
    withdrew 0.3, and 0.1x3 accumulates ABOVE 0.3, so the comparison was
    already False and the tolerance was never evaluated.
    """
    pm = _pm()
    await pm.add_stake("default", 0.1, new_staker=True)
    await pm.add_stake("default", 0.4, new_staker=True)
    await pm.remove_stake("default", 0.4, staker_exited=True)

    assert await _total(pm) < 0.1, "this case no longer exhibits the drift"

    await pm.remove_stake("default", 0.1, staker_exited=True)   # must not raise
    assert await _total(pm) == 0.0, "the residual must be floored, not negative"


async def test_the_tolerance_scales_with_the_pool():
    """THE REGRESSION THE FIRST VERSION SHIPPED, pinned.

    The check used a FIXED 1e-9. Representation error is relative to
    magnitude, so an absolute epsilon binds at scale: adversarial review drove
    300 single-deposit stakers through the real service and, above a pool peak
    near 1e6, the LAST staker out was refused a withdrawal of the exact balance
    `get_position` had just reported them — a call that could not raise at all
    before NEW-95.

    Reproduced deterministically here: after 299 stakers exit, the pool holds
    ~6.05e-09 LESS than the remaining staker's deposit. Under the old absolute
    1e-9 that raises. Under a relative floor it does not.
    """
    import random

    rng = random.Random(7)
    deposits = [round(rng.uniform(1e5, 1e6), 6) for _ in range(300)]

    pm = _pm()
    for d in deposits:
        await pm.add_stake("default", d, new_staker=True)
    for d in deposits[1:]:
        await pm.remove_stake("default", d, staker_exited=True)

    alice, residual = deposits[0], await _total(pm)
    deficit = alice - residual
    assert deficit > 1e-9, (
        f"this case no longer exceeds the old absolute epsilon (deficit "
        f"{deficit:.3e}) — pick figures that do, or the regression is unpinned"
    )

    await pm.remove_stake("default", alice, staker_exited=True)  # must not raise
    assert await _total(pm) == 0.0
    assert await _count(pm) == 0


async def test_an_over_withdrawal_still_raises_at_scale():
    """The relative floor must not become slack. It absorbs representation
    error, not a wrong number: 1% over is refused at any magnitude."""
    pm = _pm()
    await pm.add_stake("default", 1_000_000.0, new_staker=True)

    with pytest.raises(ValueError, match="Cannot remove"):
        await pm.remove_stake("default", 1_010_000.0)
    assert await _total(pm) == 1_000_000.0


# ── 3. The counter ───────────────────────────────────────────────────────


async def test_staker_count_counts_stakers_not_stake_operations():
    """Pre-fix: one address staking three times counted as three stakers."""
    pm = _pm()
    await pm.add_stake("default", 5.0, new_staker=True)
    await pm.add_stake("default", 5.0)
    await pm.add_stake("default", 5.0)

    assert await _count(pm) == 1
    assert await _total(pm) == 15.0, "the total must still accumulate"


async def test_staker_count_decrements_when_a_staker_exits():
    """Pre-fix it never decremented: three stakes then a full withdrawal left
    staker_count at 3 with total_staked at 0.0."""
    pm = _pm()
    await pm.add_stake("default", 5.0, new_staker=True)
    await pm.remove_stake("default", 5.0, staker_exited=True)

    assert await _count(pm) == 0
    assert await _total(pm) == 0.0


class _Clock:
    """A controllable stand-in for the `time` module.

    WHY THIS EXISTS. The first version of the service-level exit test asserted
    `staker_count == 0` after a full withdrawal and passed — but only because
    the whole test ran inside one second. `_accrue_rewards` early-returns when
    `elapsed == 0`; let a single second-boundary pass and `pending_rewards`
    becomes nonzero, the position is NOT deleted (the cleanup requires zero
    rewards), `will_exit` is correctly False, and the count stays 1.
    Adversarial review demonstrated it with a real `time.sleep(1.1)`: the
    shipped test failed with `assert 2 == 1`.

    The code was right and the test was wrong — it asserted one branch and
    claimed the general case. Both branches are now driven on a clock this
    file controls, so neither result depends on how fast the suite runs.
    """

    def __init__(self, start: int = 1_700_000_000) -> None:
        self.t = float(start)

    def time(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock(monkeypatch):
    from runtime.blockchain.services.staking import service as service_mod

    c = _Clock()
    monkeypatch.setattr(service_mod, "time", c)
    return c


async def test_a_staker_who_exits_with_no_rewards_is_removed_from_the_count(clock):
    """BRANCH 1 of will_exit — deterministic, not fast-suite luck.

    The clock does not move, so nothing accrues, the position is deleted, and
    the counter follows it down.
    """
    svc = _svc()
    await svc.stake("0xalice", 10.0)
    assert await _count(svc.pools) == 1

    await svc.unstake("0xalice", 10.0)

    assert ("0xalice", "default") not in svc._positions
    assert await _count(svc.pools) == 0
    assert await _total(svc.pools) == 0.0


async def test_a_staker_with_unclaimed_rewards_is_still_a_staker(clock):
    """BRANCH 2, which the first version of this file silently never reached.

    A day passes, so `_accrue_rewards` credits pending_rewards. The staker
    withdraws their whole stake, but the position SURVIVES because it still
    holds unclaimed rewards — so it is correct that the count does not drop.
    `staker_count` counts POSITION RECORDS, not staked balances, and this is
    the case that makes the distinction real.
    """
    svc = _svc()
    await svc.stake("0xalice", 10.0)
    clock.advance(86_400)

    await svc.unstake("0xalice", 10.0)

    position = svc._positions[("0xalice", "default")]
    assert position["staked_amount"] == 0.0
    assert position["pending_rewards"] > 0.0
    assert await _count(svc.pools) == 1, (
        "the position still exists, so the count must still include it"
    )
    assert await _total(svc.pools) == 0.0

    # And once the rewards are claimed, the next exit does close it.
    await svc.claim_rewards("0xalice")
    await svc.stake("0xalice", 10.0)
    await svc.unstake("0xalice", 10.0)
    assert ("0xalice", "default") not in svc._positions
    assert await _count(svc.pools) == 0


async def test_staker_count_equals_the_number_of_open_positions(clock):
    """THE INVARIANT, driven across BOTH branches.

    This is what `staker_count` actually means, and it is the assertion that
    survives someone rewording the cleanup condition. It would have caught the
    untested branch: dropping `pending_rewards <= 0` from `will_exit` makes
    the counter and the position store disagree here.
    """
    svc = _svc()

    async def invariant() -> None:
        open_positions = sum(
            1 for (_s, p) in svc._positions if p == "default"
        )
        assert svc.pools._pools["default"]["staker_count"] == open_positions, (
            f"staker_count={svc.pools._pools['default']['staker_count']} but "
            f"{open_positions} position record(s) exist"
        )

    await svc.stake("0xalice", 10.0)
    await invariant()
    await svc.stake("0xbob", 10.0)
    await invariant()

    clock.advance(86_400)                 # rewards accrue for both

    await svc.unstake("0xalice", 10.0)    # position survives (rewards)
    await invariant()
    await svc.claim_rewards("0xalice")
    await invariant()

    clock.advance(0)                      # no further accrual
    await svc.stake("0xalice", 1.0)
    await svc.unstake("0xalice", 1.0)     # now it closes
    await invariant()

    await svc.unstake("0xbob", 10.0)
    await invariant()


async def test_staker_count_never_goes_negative():
    """A miscounted exit must not make the field meaningless in the other
    direction — the fix must not be the same defect with the sign flipped."""
    pm = _pm()
    await pm.add_stake("default", 5.0, new_staker=True)
    await pm.remove_stake("default", 2.0, staker_exited=True)
    await pm.remove_stake("default", 3.0, staker_exited=True)

    assert await _count(pm) == 0


# ── 4. The silent no-op on a missing pool ────────────────────────────────


async def test_an_unknown_pool_raises_instead_of_doing_nothing():
    """`if pool:` meant these returned normally having done nothing, so a
    caller could credit a position against a pool that does not exist. They now
    agree with `get_pool`, which already raised for the same input."""
    pm = _pm()
    with pytest.raises(ValueError, match="not found"):
        await pm.add_stake("ghost", 1.0)
    with pytest.raises(ValueError, match="not found"):
        await pm.remove_stake("ghost", 1.0)
    with pytest.raises(ValueError, match="not found"):
        await pm.get_pool("ghost")


# ── 5. Through the service — the accounting stays consistent ─────────────


def _svc() -> StakingService:
    svc = StakingService({})
    svc._web3.available = True
    svc._web3.is_placeholder = lambda _a: False
    return svc


async def test_the_pool_total_tracks_the_positions_through_a_full_lifecycle():
    """THE INVARIANT the three defects each broke in a different way:
    total_staked == the sum of open positions, always."""
    svc = _svc()

    async def invariant() -> None:
        positions = sum(p["staked_amount"] for p in svc._positions.values())
        assert svc.pools._pools["default"]["total_staked"] == pytest.approx(
            positions
        ), "pool total and position sum disagree"

    await svc.stake("0xalice", 10.0)
    await invariant()
    await svc.stake("0xbob", 20.0)
    await invariant()
    assert await _count(svc.pools) == 2

    await svc.stake("0xalice", 5.0)          # same staker, second stake
    await invariant()
    assert await _count(svc.pools) == 2, "a repeat stake invented a staker"

    await svc.unstake("0xalice", 15.0)       # alice fully exits
    await invariant()
    assert await _count(svc.pools) == 1
    assert ("0xalice", "default") not in svc._positions

    await svc.unstake("0xbob", 5.0)          # bob partially exits
    await invariant()
    assert await _count(svc.pools) == 1, "a partial unstake removed a staker"


async def test_the_service_still_refuses_an_over_unstake():
    """The service's own guard predates NEW-95 and must survive it — the pool
    check is defence in depth behind it, not a replacement."""
    svc = _svc()
    await svc.stake("0xalice", 10.0)

    with pytest.raises(ValueError, match="Cannot unstake"):
        await svc.unstake("0xalice", 100.0)

    assert svc._positions[("0xalice", "default")]["staked_amount"] == 10.0
    assert svc.pools._pools["default"]["total_staked"] == 10.0


async def test_the_new_94_gate_still_precedes_all_of_this():
    """SCOPE PIN. NEW-95 added raises inside methods NEW-94 gated. The gate
    must still win, or an undeployed domain would start throwing ValueErrors
    where it used to refuse honestly."""
    pm = StakingPoolManager({})
    pm._web3.available = False

    # A negative amount on a DARK domain gets the refusal, not the ValueError.
    assert (await pm.remove_stake("default", -20.0))["status"] == "not_deployed"
    assert (await pm.add_stake("default", 0.0))["status"] == "not_deployed"
    assert (await pm.remove_stake("ghost", 1.0))["status"] == "not_deployed"
