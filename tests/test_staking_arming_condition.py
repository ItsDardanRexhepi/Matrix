"""NEW-98 — the compound arming condition, and the premises it rests on.

ONE KEY ARMS EIGHT METHODS. `staking.staking_contract` flips the whole domain
(NEW-94), which is correct — a per-method domain is what that finding removed —
and it means the condition in service.py is the only thing between a config
change and every fabrication behind it.

A CONDITION A FUTURE DEVELOPER NEVER SEES IS NOT A CONTROL, so it lives in the
module they must edit, and these tests keep it honest in three ways:

  1. it is present and names all seven clauses;
  2. each clause states its own PARTIAL-STATE FAILURE MODE, because seven
     requirements without per-clause consequences invite the incremental arming
     they exist to prevent;
  3. THE PREMISES ARE ASSERTED, NOT ASSUMED. Each clause claims something is
     currently true of the code. If one stops being true — someone binds
     `staker`, or wires a treasury — the corresponding test fails, and that is
     the moment to re-read the condition rather than to delete it (rule 39:
     invert a retired pin, do not remove it).

Clause 2's root is the dispatcher's missing identity binding, DEFERRED REGISTER
ITEM 0 (NEW-82). This domain supplies its worked example, not its fix.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from runtime.blockchain.services.staking.service import StakingService
from runtime.blockchain.web3_manager import Web3Manager

SERVICE_SRC = (
    pathlib.Path(__file__).resolve().parent.parent
    / "runtime/blockchain/services/staking/service.py"
)

CLAUSE_HEADINGS = (
    "REWARDS HAVE A DEMONSTRATED FUNDED SOURCE",
    "`staker` IS BOUND TO AN AUTHENTICATED CALLER IDENTITY",
    "POSITION STATE IS READ FROM CHAIN",
    "THE POOL-ACCOUNTING CORRECTIONS ARE IN PLACE",
    "STATUS IS DERIVED FROM A RECEIPT",
    "DOES NOT RETURN A RECORD FOR A POSITION IT DELETED",
    "THE FEED SURFACES ARE RE-DERIVED AT ARMING TIME",
)


@pytest.fixture(autouse=True)
def _restore_shared_web3():
    shared = Web3Manager.get_shared({})
    before = (shared.available, shared.is_placeholder)
    yield
    shared.available, shared.is_placeholder = before


# ── The condition exists, and says what it must ─────────────────────────


def test_the_condition_is_present_and_names_all_seven_clauses():
    text = SERVICE_SRC.read_text()
    assert "STAKING ARMING CONDITION" in text
    assert "LIFTING CONDITION" in text
    for clause in CLAUSE_HEADINGS:
        assert clause in text, f"arming condition missing clause: {clause}"


def test_each_clause_states_its_own_partial_state_failure_mode():
    text = SERVICE_SRC.read_text()
    assert text.count("PARTIAL-STATE FAILURE MODE") >= 7


def _condition_prose() -> str:
    """The condition is a comment BLOCK, so it wraps across lines and behind
    `#` markers. Normalise to one whitespace-collapsed string before matching —
    asserting on a particular line break would make the test fail when someone
    reflows a paragraph, which is a control that punishes tidying."""
    import re

    raw = SERVICE_SRC.read_text()
    start = raw.index("STAKING ARMING CONDITION")
    end = raw.index("LIFTING CONDITION", start)
    block = raw[start:end]
    return re.sub(r"\s+", " ", block.replace("#", " "))


def test_it_says_what_makes_this_domain_different():
    """The accrual-vs-attribution distinction — the sharpest refinement of
    rule 21 this engagement has produced, because here the computation is
    genuinely real AND creates an obligation."""
    prose = _condition_prose()
    assert "DESCRIBES a payment someone else could make" in prose
    assert "CREATES an obligation" in prose
    assert "calculate a debt" in prose


def test_the_deferred_register_cross_reference_is_present():
    text = SERVICE_SRC.read_text()
    assert "DEFERRED\n#   REGISTER ITEM 0" in text or "REGISTER ITEM 0" in text
    assert "NEW-82" in text


def test_the_label_audit_ordering_constraint_is_explicit():
    """Clause 7's ordering is the whole point: repairing the key mismatch
    before auditing the table ships every stale label at once."""
    text = SERVICE_SRC.read_text()
    assert "MUST PRECEDE THE REPAIR OF ITS KEYS" in text


# ── The premises, asserted rather than assumed ──────────────────────────


def test_premise_clause_2_staker_is_still_an_unbound_parameter():
    """If `staker` gains an identity binding this fails — which is the moment
    to re-read clause 2, not to delete it."""
    for name in ("stake", "unstake", "claim_rewards", "get_position"):
        sig = inspect.signature(getattr(StakingService, name))
        assert "staker" in sig.parameters, f"{name} no longer takes `staker`"


async def test_premise_clause_2_the_worked_example_still_reproduces():
    """THE EXPLOIT, DRIVEN. An unrelated caller unstakes bob's position and is
    handed his record. This is deferred register item 0's worked example, and
    it must keep reproducing until that item is closed."""
    svc = StakingService({})
    svc._web3.available = True
    svc._web3.is_placeholder = lambda _a: False

    await svc.stake("0xbob", 100.0)
    result = await svc.unstake("0xbob", 40.0)      # no caller identity anywhere

    assert result["staker"] == "0xbob"
    assert result["staked_amount"] == 60.0, (
        "the cross-staker unstake no longer reproduces — if `staker` is now "
        "bound to an authenticated caller, clause 2 is satisfied and this test "
        "should be INVERTED to assert the refusal, not deleted"
    )


def _executable_source(path: pathlib.Path) -> str:
    """A module's code with COMMENTS AND DOCSTRINGS removed.

    THE DOCSTRING-VS-LIVE-CODE TRAP, FOURTH INSTANCE, and the first two
    attempts at this very function both fell into it. `ast.unparse` strips
    comments — which handles the arming condition, a comment block that
    discusses the absence of a treasury at length — but it PRESERVES
    docstrings, and `_accrue_rewards`'s docstring says "there is no treasury"
    in as many words. A premise test that greps for `treasury` therefore
    matched the prose explaining that no treasury exists.

    Every control in this suite quotes the names it matches, so raw text can
    never distinguish a matcher from its own explanation. Both layers are
    stripped structurally here.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            body[0] = ast.Expr(value=ast.Constant(value=""))
    return ast.unparse(ast.fix_missing_locations(tree))


def test_the_executable_source_helper_strips_both_layers():
    """Proven in both directions (rule 35), because the two prior versions of
    the helper each passed one layer and failed the other."""
    code = _executable_source(SERVICE_SRC)
    assert "STAKING ARMING CONDITION" not in code, "comments survived"
    assert "no treasury, no balance and no payer" not in code, "docstrings survived"
    assert "_accrue_rewards" in code, "the helper stripped executable code too"
    assert "recorded_unsettled" in code, "live string literals must survive"


def test_premise_clause_1_the_accrual_draws_against_nothing():
    """Clause 1's premise, expressed as BEHAVIOUR rather than vocabulary.

    THREE ATTEMPTS AT THIS TEST, AND THE FIRST TWO WERE THE WRONG UNIT. A
    word-presence check for "treasury" cannot express this premise, because
    the honest disclosure NEEDS the word — `get_position`'s
    `rewards_disclosure` says "No treasury or balance backs them", which is a
    live string literal and must survive any stripping. A control that fires on
    the sentence disclosing the absence is measuring the disclosure, not the
    code. So the unit changed from vocabulary to behaviour (rule 42).

    What clause 1 actually asserts: the accrual derives its figure from the
    pool's configured `reward_rate` alone, reads no balance, and cannot refuse
    for insufficiency. If any of that stops being true, re-read the clause —
    and check the accrual FAILS CLOSED, not merely that a balance exists.
    """
    body = ast.unparse(
        ast.parse(inspect.getsource(StakingService._accrue_rewards).strip())
    )

    assert 'pool.get("reward_rate"' in body or "pool.get('reward_rate'" in body, (
        "the accrual no longer reads the pool's configured rate — clause 1 may "
        "be satisfiable; verify it reads a real balance and refuses when short"
    )
    # It cannot refuse: no raise, no early return carrying a reason, nothing
    # that could express "insufficient funds".
    tree = ast.parse(inspect.getsource(StakingService._accrue_rewards).strip())
    raises = [n for n in ast.walk(tree) if isinstance(n, ast.Raise)]
    assert not raises, (
        "the accrual can now refuse — if that refusal is a funded-source "
        "coverage check, clause 1 is satisfied and this pin should be INVERTED "
        "to assert the refusal, not deleted"
    )
    # And it credits unconditionally. (ast.unparse normalises quote style, so
    # the needle is written the way unparse emits it.)
    assert "position['pending_rewards'] += earned" in body


def test_premise_clause_3_positions_are_still_process_local():
    """`_positions` is a plain dict with no persistence and no chain read."""
    svc = StakingService({})
    assert isinstance(svc._positions, dict)

    src = ast.unparse(ast.parse(inspect.getsource(StakingService.get_position).strip()))
    assert "self._positions" in src, "get_position no longer reads the local dict"
    assert "ownerOf" not in src and "functions." not in src, (
        "get_position appears to read chain state — clause 3 may be satisfied"
    )


def test_premise_clause_5_create_pool_still_asserts_its_status():
    """The domain's single D6 entry, still shaped that way."""
    from tests.test_uuid_mint_fabrication_shape import find_fabrication_shape

    staking = {k for k in find_fabrication_shape() if k.startswith("staking/")}
    assert staking == {"staking/pools.py::StakingPoolManager.create_pool"}, (
        f"the staking D6 set changed: {staking}. If create_pool now derives "
        "its status from a receipt, clause 5 is satisfied — invert this pin."
    )


async def test_premise_clause_6_unstake_still_returns_a_deleted_record():
    """It deletes the store entry and returns a snapshot built from a local
    reference that outlived it."""
    svc = StakingService({})
    svc._web3.available = True
    svc._web3.is_placeholder = lambda _a: False

    await svc.stake("0xalice", 10.0)
    result = await svc.unstake("0xalice", 10.0)

    assert ("0xalice", "default") not in svc._positions, "the position survived"
    assert result["staker"] == "0xalice" and result["staked_amount"] == 0.0, (
        "unstake no longer returns a record for the position it deleted — "
        "clause 6 may be satisfied; invert this pin rather than removing it"
    )


def test_premise_clause_7_the_feed_lookup_still_misses():
    """The feed's honesty is accidental: the action name and the label keys are
    different vocabularies, so the lookup falls through."""
    from runtime.social.feed_engine import ACTION_LABELS

    misses = [
        a for a in ("stake", "unstake") if f"{a}_tokens" not in ACTION_LABELS
    ]
    assert misses, (
        "the action/label key namespaces appear reconciled — clause 7's "
        "ordering constraint becomes URGENT: audit every label before relying "
        "on the repair"
    )
    # The one this domain fixed IS reachable, by both keys.
    for key in ("claim_rewards", "claim_staking_rewards"):
        assert "not settled" in ACTION_LABELS[key]


# ── The domain stays dark ────────────────────────────────────────────────


async def test_nothing_in_this_commit_armed_anything():
    """SCOPE PIN for the whole domain-10 close: the condition is a comment and
    a set of tests. The gate is untouched and the domain still refuses."""
    svc = StakingService({})
    svc._web3.available = False

    for coro in (
        svc.stake("0xa", 10.0),
        svc.unstake("0xa", 1.0),
        svc.claim_rewards("0xa"),
        svc.get_position("0xa"),
        svc.pools.create_pool({"name": "P"}),
        svc.pools.add_stake("default", 1.0),
        svc.pools.remove_stake("default", 1.0),
        svc.apy_calculator.calculate_apy("default"),
    ):
        assert (await coro)["status"] == "not_deployed"
