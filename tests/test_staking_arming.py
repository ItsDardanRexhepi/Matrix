"""NEW-94 — the staking domain arms as a unit; the read exemption is a list.

WHAT WAS WRONG. Fifteen methods across three classes, exactly ONE gated
(`StakingService.stake`). The other fourteen ran identically deployed or not.

And the single gate was load-bearing by accident: `stake` is the only writer of
`StakingService._positions`, so gating it is the ONLY reason `unstake`,
`claim_rewards` and `get_position` are inert today. They were never safe — they
were starved. A domain that is quiet because a dictionary happens to be empty
has no control in it at all; remove one gate and four fabrications wake up.

THE COUNTEREXAMPLE THAT SHAPES THE FIX. The natural repair is "gate the writes,
exempt the reads." That rule is wrong here, and this domain proves it:

    StakingService.get_position -> await self._accrue_rewards(position, pool)

A method named `get` MINTS BALANCE. `test_the_counterexample_polling_a_read_mints_balance`
drives it: poll the read, watch `pending_rewards` rise from nothing.

So the exemption is an ENUMERATED LIST of five methods checked one at a time,
and `test_every_public_callable_is_classified` fails on any new public method
that appears on neither list. A future developer adding `get_rewards_preview()`
inherits no default from the word "get".
"""

from __future__ import annotations

import ast
import functools
import importlib
import inspect
import pathlib

import pytest

from runtime.blockchain.services.staking.apy_calculator import APYCalculator
from runtime.blockchain.services.staking.arming import (
    STAKING_GATED,
    STAKING_UNGATED_READS,
    resolve_staking_contract,
)
from runtime.blockchain.services.staking.pools import StakingPoolManager
from runtime.blockchain.services.staking.service import StakingService
from runtime.blockchain.web3_manager import Web3Manager

STAKING_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "runtime/blockchain/services/staking"
)



@pytest.fixture(autouse=True)
def _restore_shared_web3():
    """`Web3Manager.get_shared()` is a PROCESS-WIDE SINGLETON (rule 45).

    All three staking classes now hold the same instance — that is the point of
    NEW-94 — which also means arming it in one test arms it for every later
    test in the session. Restored rather than relied upon.
    """
    shared = Web3Manager.get_shared({})
    before = (shared.available, shared.is_placeholder)
    yield
    shared.available, shared.is_placeholder = before


def _dark() -> StakingService:
    """Contract unset: the state the platform is actually in today."""
    svc = StakingService({})
    svc._web3.available = False
    return svc


def _armed() -> StakingService:
    """Contract configured: the state in which the domain would fire."""
    svc = StakingService({})
    svc._web3.available = True
    svc._web3.is_placeholder = lambda _a: False
    return svc


def _is_refusal(result) -> bool:
    return isinstance(result, dict) and result.get("status") == "not_deployed"


# ── The gate, on every method that needed one ────────────────────────────


async def test_every_gated_method_refuses_when_undeployed():
    """SCENARIO: no staking contract. Pre-fix, thirteen of these fourteen
    answered as though there were one."""
    svc = _dark()

    results = {
        "APYCalculator.calculate_apy": await svc.apy_calculator.calculate_apy("default"),
        "StakingPoolManager.create_pool": await svc.pools.create_pool({"name": "P"}),
        "StakingPoolManager.add_stake": await svc.pools.add_stake("default", 5.0),
        "StakingPoolManager.remove_stake": await svc.pools.remove_stake("default", 5.0),
        "StakingService.stake": await svc.stake("0xa", 10.0),
        "StakingService.unstake": await svc.unstake("0xa", 1.0),
        "StakingService.claim_rewards": await svc.claim_rewards("0xa"),
        "StakingService.get_position": await svc.get_position("0xa"),
    }

    assert set(results) == set(STAKING_GATED), (
        "this test and arming.py disagree about which methods are gated"
    )
    for name, result in results.items():
        assert _is_refusal(result), f"{name} did not refuse: {result!r}"


async def test_the_dark_domain_mutates_nothing():
    """The refusals must be refusals, not logged-and-continued.

    Every store the domain owns stays untouched after calling all eight.
    """
    svc = _dark()
    pools_before = dict(svc.pools._pools)

    for coro in (
        svc.apy_calculator.calculate_apy("default"),
        svc.pools.create_pool({"name": "P"}),
        svc.pools.add_stake("default", 5.0),
        svc.pools.remove_stake("default", 5.0),
        svc.stake("0xa", 10.0),
        svc.unstake("0xa", 1.0),
        svc.claim_rewards("0xa"),
        svc.get_position("0xa"),
    ):
        await coro

    assert svc._positions == {}, "a position was created by a refused call"
    assert svc._commissions == [], "a commission was recorded by a refused call"
    assert svc.apy_calculator._history == {}, (
        "an APY snapshot was recorded while undeployed — an unarmed domain "
        "accumulating a history of yields it never earned is manufacturing "
        "evidence for whoever reads get_historical_apy later"
    )
    assert svc.pools._pools == pools_before, "a pool record changed"
    assert pools_before["default"]["total_staked"] == 0.0
    assert pools_before["default"]["staker_count"] == 0


# ── The exemption: five methods, each checked ────────────────────────────


async def test_the_five_exempt_reads_still_answer_when_undeployed():
    """The exemption must be real, or "gated domain" just means "dead domain"
    and the list is theatre."""
    svc = _dark()

    assert await svc.pools.get_pool("default") is not None
    assert await svc.pools.list_pools() != []
    assert await svc.apy_calculator.get_historical_apy("default") == []
    assert isinstance(svc.apy_calculator, APYCalculator)
    assert isinstance(svc.pools, StakingPoolManager)


async def test_the_exempt_reads_claim_no_balance():
    """WHY each is exempt, asserted rather than asserted-about.

    `get_pool` returns a CONFIG record — rate, lock, minimum. The two fields
    that would be balance claims are zero and stay zero while dark.
    """
    svc = _dark()
    pool = await svc.pools.get_pool("default")

    assert pool["total_staked"] == 0.0
    assert pool["staker_count"] == 0
    assert {"reward_rate", "lock_period", "min_stake"} <= set(pool)

    # And the history reader is empty because its only writer is now gated —
    # not because it was empty to begin with.
    assert await svc.apy_calculator.get_historical_apy("default") == []
    assert "APYCalculator.calculate_apy" in STAKING_GATED


# ── The counterexample that makes the exemption a list ───────────────────


async def test_the_counterexample_polling_a_read_mints_balance():
    """THE REASON THE EXEMPTION IS AN ENUMERATED LIST.

    `get_position` is on the GATED list even though its name promises a read.
    This drives why: on an armed service, calling it credits rewards that no
    stake, claim or caller intent asked for. If someone later "simplifies" the
    exemption into the rule "reads are safe", this test is what breaks.
    """
    svc = _armed()
    await svc.stake("0xa", 10.0)
    position = svc._positions[("0xa", "default")]
    assert position["pending_rewards"] == 0.0

    # Backdate the accrual clock an hour; nothing else changes.
    position["last_reward_at"] -= 3600

    before = position["pending_rewards"]
    await svc.get_position("0xa")          # a READ, and only a read
    after = svc._positions[("0xa", "default")]["pending_rewards"]

    assert before == 0.0
    assert after > 0.0, (
        "get_position no longer accrues — if that is deliberate, move it to "
        "STAKING_UNGATED_READS and delete this test; do not leave both"
    )


def test_get_position_is_gated_and_says_why():
    """The reason must live where the next developer will read it."""
    assert "StakingService.get_position" in STAKING_GATED
    assert "StakingService.get_position" not in STAKING_UNGATED_READS

    doc = inspect.getdoc(StakingService.get_position) or ""
    assert "COUNTEREXAMPLE" in doc
    assert "MINTS BALANCE" in doc
    assert "_accrue_rewards" in doc

    # And the claim in that docstring is true of the live code, not just of
    # the prose — the docstring is stripped before the body is inspected.
    fn = ast.parse(inspect.getsource(StakingService.get_position).strip()).body[0]
    body = fn.body[1:] if ast.get_docstring(fn) else fn.body
    assert "_accrue_rewards" in ast.unparse(ast.Module(body=body, type_ignores=[])), (
        "the docstring claims get_position accrues, but the body no longer does"
    )


# ── The structural control: no method may arrive unclassified ────────────


#: Attribute kinds that are callable or computed but are NOT plain functions
#: in ``vars(cls)``. The first version of this control used only
#: ``inspect.isfunction``, which is FALSE for the ``staticmethod`` and
#: ``classmethod`` OBJECTS that ``vars(cls)`` actually holds — so one decorator
#: silently removed a method from a control whose whole purpose is that nothing
#: arrives unclassified. Found by adversarial review, not by this suite.
#: ``StakingService._sanitize_position`` is already a ``@staticmethod``, so the
#: shape was in live use in the very domain being gated.
_CALLABLE_KINDS = (property, functools.cached_property, staticmethod, classmethod)


def _is_public_callable(obj: object) -> bool:
    """True for anything a caller can invoke or read as a computed attribute."""
    return isinstance(obj, _CALLABLE_KINDS) or callable(obj)


def _staking_classes() -> dict[str, type]:
    """Every class DEFINED in the staking package, discovered not hardcoded.

    Hardcoding the three known classes left a second hole: a new class added to
    the package would be outside the control entirely. Discovery closes it.
    """
    found: dict[str, type] = {}
    for path in sorted(STAKING_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        mod = importlib.import_module(
            f"runtime.blockchain.services.staking.{path.stem}"
        )
        for name, obj in vars(mod).items():
            if inspect.isclass(obj) and obj.__module__ == mod.__name__:
                found[name] = obj
    return found


def _public_callables() -> set[str]:
    """Every public callable or computed attribute in the staking package."""
    found: set[str] = set()
    for cname, cls in _staking_classes().items():
        for name, obj in vars(cls).items():
            if name.startswith("_"):
                continue
            if _is_public_callable(obj):
                found.add(f"{cname}.{name}")
    return found


def test_every_public_callable_is_classified():
    """THE CONTROL THAT OUTLIVES THIS COMMIT.

    A developer adding `get_rewards_preview()` must choose a list. They cannot
    inherit "it's a getter, getters are safe" — that reasoning is exactly what
    `get_position` disproves, one file away.
    """
    public = _public_callables()
    classified = STAKING_GATED | STAKING_UNGATED_READS

    unclassified = public - classified
    assert not unclassified, (
        f"new public staking callable(s) on neither list: {sorted(unclassified)}. "
        "Read the body and put each on STAKING_GATED or STAKING_UNGATED_READS "
        "in arming.py. Do not assume a name beginning with 'get' is safe — "
        "StakingService.get_position mints balance."
    )

    stale = classified - public
    assert not stale, (
        f"arming.py names callables that no longer exist: {sorted(stale)}"
    )


def test_the_classifier_sees_decorated_methods_too():
    """THE HOLE THE FIRST VERSION OF THIS CONTROL HAD.

    `_public_callables` used `inspect.isfunction`, which is False for the
    `staticmethod` and `classmethod` OBJECTS that live in `vars(cls)`. So a
    one-word decorator removed a public method from the control that exists to
    guarantee nothing arrives unclassified — and the suite stayed green while
    an ungated, value-claiming method sat on a class in a dark domain.

    Found by adversarial review, not by this file. Pinned here in BOTH
    directions (rule 35): the classifier must see each kind, and must still
    ignore plain data attributes.
    """
    class Probe:
        @staticmethod
        def preview_rewards(amount: float) -> dict:
            return {"projected_rewards": amount * 0.12, "apy": 12.0}

        @classmethod
        def from_config(cls, config: dict):
            return cls()

        @functools.cached_property
        def cached_total(self) -> float:
            return 1.0

        @property
        def total(self) -> float:
            return 1.0

        def plain(self) -> None:
            pass

        VERSION = "1.0"          # data, not callable
        LIMITS = {"max": 1}      # data, not callable

    seen = {
        n for n, o in vars(Probe).items()
        if not n.startswith("_") and _is_public_callable(o)
    }
    assert seen == {
        "preview_rewards", "from_config", "cached_total", "total", "plain",
    }, f"the classifier misses a callable kind: {seen}"

    # The negative half — it must not sweep in plain data, or the control
    # would demand classification for constants and get switched off.
    assert "VERSION" not in seen
    assert "LIMITS" not in seen

    # And the shape is in live use in this domain, which is why it matters:
    assert isinstance(
        vars(StakingService)["_sanitize_position"], staticmethod
    ), "the reference staticmethod moved; re-check that this hole stays closed"


def test_the_class_set_is_discovered_not_hardcoded():
    """The second half of the same hole: a NEW class in the staking package
    was outside the control entirely while CLASSES was a literal."""
    discovered = _staking_classes()
    assert set(discovered) == {
        "APYCalculator", "StakingPoolManager", "StakingService",
    }, (
        f"the staking package's class set changed: {sorted(discovered)}. "
        "A new class here is in scope for the arming lists — classify its "
        "public callables in arming.py."
    )


def test_the_two_lists_are_disjoint():
    """A method on both lists would make the classification meaningless."""
    assert not (STAKING_GATED & STAKING_UNGATED_READS)
    assert len(STAKING_GATED) == 8
    assert len(STAKING_UNGATED_READS) == 5
    assert len(_public_callables()) == 13


def test_private_helpers_inherit_arming_from_a_classified_caller():
    """The scope claim in arming.py, asserted instead of assumed.

    The lists cover the PUBLIC surface. That is only sufficient if every
    private helper is reached through a public entry point that is itself
    classified — otherwise `_accrue_rewards` could be called from somewhere
    unclassified and the domain would leak through the gap.
    """
    for cname, cls in _staking_classes().items():
        src = inspect.getsource(cls)
        tree = ast.parse(src).body[0]
        methods = {
            n.name: n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        privates = {
            n for n in methods
            if n.startswith("_") and not n.startswith("__")
        }
        for priv in privates:
            callers = {
                name for name, fn in methods.items()
                if name != priv
                and any(
                    getattr(c.func, "attr", None) == priv
                    for c in ast.walk(fn) if isinstance(c, ast.Call)
                )
            }
            public_callers = {c for c in callers if not c.startswith("_")}
            assert public_callers, (
                f"{cname}.{priv} has no public caller in its own class — it is "
                "outside the reach of the arming lists, so NEW-94's scope claim "
                "no longer holds. Classify it explicitly or find its caller."
            )
            unclassified = {
                c for c in public_callers
                if f"{cname}.{c}" not in (STAKING_GATED | STAKING_UNGATED_READS)
            }
            assert not unclassified, (
                f"{cname}.{priv} is reachable from unclassified public "
                f"method(s) {sorted(unclassified)}"
            )


# ── Positive controls: the gate must not be a hardcoded 'no' ─────────────


async def test_the_domain_works_when_armed():
    """The fix must not replace fourteen fabrications with fourteen refusals —
    that is the same defect with the sign flipped."""
    svc = _armed()

    result = await svc.stake("0xa", 10.0)
    assert not _is_refusal(result)
    assert result["staked_amount"] == 10.0

    pool = await svc.pools.get_pool("default")
    assert pool["total_staked"] == 10.0

    apy = await svc.apy_calculator.calculate_apy("default")
    assert not _is_refusal(apy)
    assert "current_apy" in apy

    created = await svc.pools.create_pool({"pool_id": "p2", "name": "Second"})
    assert not _is_refusal(created)
    assert created["pool_id"] == "p2"

    unstaked = await svc.unstake("0xa", 4.0)
    assert not _is_refusal(unstaked)
    assert unstaked["staked_amount"] == 6.0


# ── Scope pins ───────────────────────────────────────────────────────────


async def test_stake_refusal_shape_is_unchanged():
    """SCOPE. `stake` was ALREADY gated. NEW-94 replaced its inline gate with
    the shared helper; the answer a caller sees must be the same one.
    """
    result = await _dark().stake("0xa", 10.0)

    assert result["status"] == "not_deployed"
    assert result["operation"] == "stake"
    assert result["requested"] == {
        "staker": "0xa", "amount": 10.0, "pool_id": "default",
    }


def test_all_three_classes_resolve_the_same_contract():
    """A domain gate is only a domain gate if every class reads one address.

    Two classes resolving it differently is how the asymmetry would grow back.
    """
    cfg = {"blockchain": {"staking_contract": "0xSTAKE"}}
    svc = StakingService(cfg)

    assert svc._staking_contract == "0xSTAKE"
    assert svc.pools._staking_contract == "0xSTAKE"
    assert svc.apy_calculator._staking_contract == "0xSTAKE"
    assert resolve_staking_contract(cfg) == "0xSTAKE"

    # And the staking-scoped key still wins where it did before.
    assert resolve_staking_contract(
        {"staking": {"staking_contract": "0xA"},
         "blockchain": {"staking_contract": "0xB"}}
    ) == "0xA"

    assert svc._web3 is svc.pools._web3 is svc.apy_calculator._web3, (
        "the three classes hold different Web3Managers, so one could be armed "
        "while another is dark"
    )


async def test_a_pool_refusal_leaves_no_orphan_position():
    """THE ORDERING NEW-94 FORCED, driven.

    `add_stake` can now refuse. The old code credited the position first and
    discarded whatever `add_stake` returned, so a refusal arriving late would
    leave a staker holding a balance the pool never recorded. Pool accounting
    now happens first, and nothing is published if it refuses.
    """
    svc = _armed()

    async def refuses(*_a, **_kw):
        return {"status": "not_deployed", "operation": "add_stake"}

    svc._pools.add_stake = refuses
    result = await svc.stake("0xa", 10.0)

    assert _is_refusal(result)
    assert svc._positions == {}, (
        "a position was published even though the pool accounting refused"
    )


def test_no_staking_method_still_names_the_primitive_directly():
    """The domain must go through the registered wrapper, or D10's view of it
    is only as good as whichever call site was remembered."""
    for path in STAKING_DIR.glob("*.py"):
        if path.name == "arming.py":
            continue
        assert "not_deployed_response" not in path.read_text(), (
            f"{path.name} calls the refusal primitive directly instead of "
            "staking_not_deployed — the domain gate is no longer uniform"
        )
