"""D10 — an honest refusal must not be discarded by its caller.

THE PATTERN. `NFTService.process_sale` did this:

    await self._factory.transfer_token(...)      # bare statement, return DROPPED
    ...
    sale_result["nft_transferred"] = True        # asserted twelve lines later

`NFTFactory.transfer_token` refuses on BOTH branches — including when
`_is_ready()` is true, where it returns not_deployed with reason "factory ABI
not yet wired into runtime". So the one component honest enough to say "I
cannot do this" was called, ignored, and contradicted by its own caller.

WHY THIS IS WORSE THAN A STUB. The factory is CORRECT. `_collections` is
declared in its own comment as a "cache for in-process queries"; ownership
lives on-chain in OpenMatrixNFT.sol, a real ERC721, and refusing while that
contract is undeployed is the right behaviour. The defect was never a missing
implementation — it was an IMPLEMENTED REFUSAL BEING OVERWRITTEN. Someone did
the work correctly and the caller unmade it, which is exactly the shape that
hides a fabrication behind real code.

WHAT THIS CONTROL IS WORTH — the negative result is the point. Measured
repo-wide at the time of writing:

    81 methods can return not_deployed_response
     1 caller discarded one
     0 after NEW-90

A detector that finds ONE instance and proves the class is BOUNDED is worth as
much as one that finds fifty: it converts "how much of this is there?" from an
open question into a closed one. This is a preventive control, frozen at zero.

SCOPE, stated rather than implied. It catches the syntactic form — `await
<refuser>(...)` as a bare expression statement. It does NOT catch a caller that
CAPTURES the result and then never inspects it; that is a dataflow question, not
a syntax one, and claiming otherwise would overstate the guarantee. The captured
-but-unchecked form is a Phase-6 read, not a detector.
"""

from __future__ import annotations

import ast
import pathlib

from tests import refusal_primitives

ROOT = pathlib.Path(__file__).resolve().parent.parent / "runtime/blockchain"

# The registry lives in tests/refusal_primitives.py because a wrapper blinds
# EVERY name-matching detector at once, not just this one — NEW-94's wrapper
# silently blinded D6 as well, and D6's falling count read as progress. One
# list, imported by all of them, is the only version of this that stays true.



def _mentions_refusal(fn: ast.AST) -> bool:
    return refusal_primitives.mentions_refusal(ast.unparse(fn))


def _refusing_methods() -> set[str]:
    """Every method whose body can return an honest refusal."""
    names: set[str] = set()
    for path in ROOT.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            for fn in cls.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if _mentions_refusal(fn):
                    names.add(fn.name)
    return names


def find_refusal_wrappers() -> set[str]:
    """Module-level functions that return a refusal — i.e. new primitives.

    A free function (as opposed to a method) whose body constructs a refusal is
    by definition a wrapper other code will call in place of the primitive.
    Each one must be registered in tests/refusal_primitives.py or it blinds
    this detector — and D6 and D7 — to everything downstream of it.
    """
    found: set[str] = set()
    for path in ROOT.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in tree.body:  # module level only — methods are not wrappers
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _mentions_refusal(node):
                found.add(node.name)
    return found


def find_discarded_refusals() -> set[str]:
    """``file::Caller.method -> callee`` for every DISCARDED honest refusal."""
    refusers = _refusing_methods()
    found: set[str] = set()
    for path in ROOT.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        rel = str(path.relative_to(ROOT))
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            for fn in cls.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for node in ast.walk(fn):
                    # `await x.y(...)` as a bare statement == return dropped
                    if not isinstance(node, ast.Expr):
                        continue
                    if not isinstance(node.value, ast.Await):
                        continue
                    call = node.value.value
                    if not isinstance(call, ast.Call):
                        continue
                    callee = getattr(call.func, "attr", None)
                    if callee in refusers:
                        found.add(f"{rel}::{cls.name}.{fn.name} -> {callee}")
    return found


def test_every_refusal_wrapper_is_registered():
    """THE DETECTOR'S OWN BLIND SPOT, made into a failing test.

    D10 matches on a NAME. Any helper that returns a refusal on the primitive's
    behalf silences D10 for all of that helper's callers — the detector keeps
    reporting zero while an entire domain's refusals become invisible to it.

    So every free function in runtime/blockchain that can produce a refusal
    must appear in the shared registry. This test is what makes the
    registration mandatory rather than remembered.
    """
    unregistered = find_refusal_wrappers() - set(refusal_primitives.REFUSAL_PRIMITIVES)
    assert not unregistered, (
        "a new refusal wrapper exists but is not registered in "
        f"the registry: {sorted(unregistered)}. Every caller of it is "
        "currently INVISIBLE to D10, so this file's green means less than it "
        "did before the wrapper was added. Add the name to the tuple."
    )


def test_the_wrapper_registration_is_load_bearing():
    """Proven in both directions (rule 35): the registration must actually
    change what the detector sees, or it is decoration.

    With `staking_not_deployed` registered, the staking methods that refuse
    through it are recognised as refusers. Drop it and they vanish.
    """
    assert refusal_primitives.is_refusal_name("staking_not_deployed")

    with_wrapper = _refusing_methods()
    assert {"add_stake", "remove_stake", "create_pool"} <= with_wrapper, (
        "the NEW-94 staking refusals are not being recognised"
    )

    # And the negative half: they are recognised ONLY because of the wrapper.
    src = (ROOT / "services/staking/pools.py").read_text()
    assert "not_deployed_response" not in src, (
        "pools.py now names the primitive directly, so this test no longer "
        "demonstrates that the wrapper registration is what makes D10 see it"
    )


# ── The frozen inventory (measured 2026-08-11; ratchet: may only shrink) ──
#
# 1 at introduction -> 0 after NEW-90. The only instance was
# NFTService.process_sale discarding NFTFactory.transfer_token.

KNOWN_DISCARDED_REFUSALS: set[str] = set()


def test_no_caller_discards_an_honest_refusal():
    """A refusal that is thrown away is a fabrication waiting to be asserted."""
    current = find_discarded_refusals()

    new = current - KNOWN_DISCARDED_REFUSALS
    assert not new, (
        "a caller is DISCARDING the return of a method that can refuse. The "
        "refusal cannot influence what the caller reports, so any success it "
        f"claims is unfounded: {sorted(new)}"
    )

    fixed = KNOWN_DISCARDED_REFUSALS - current
    assert not fixed, (
        f"remove from KNOWN_DISCARDED_REFUSALS to tighten the ratchet: {sorted(fixed)}"
    )


def test_the_inventory_is_empty_and_the_class_is_bounded():
    """BURN-DOWN: 1 -> 0 (NEW-90).

    The bound is the finding: 81 methods can refuse, exactly one caller ever
    discarded one, and none does now.
    """
    assert KNOWN_DISCARDED_REFUSALS == set()
    assert find_discarded_refusals() == set()
    assert len(_refusing_methods()) >= 50, (
        "the refuser set collapsed — the detector is scanning nothing, so its "
        "green means nothing"
    )


def test_the_detector_fires_on_the_shape_it_exists_for():
    """Proven in BOTH directions (rule 35): it must fire, and correctly not.

    Reconstructs the exact NEW-90 shape and its fixed form as synthetic ASTs,
    so the control is shown to DISCRIMINATE rather than merely to trip.
    """
    refusers = _refusing_methods()
    assert "transfer_token" in refusers, "the reference refuser vanished"

    def discards(src: str) -> bool:
        fn = ast.parse(src).body[0].body[0]
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Await)
                and isinstance(node.value.value, ast.Call)
                and getattr(node.value.value.func, "attr", None) in refusers
            ):
                return True
        return False

    bad = (
        "class S:\n"
        "    async def sale(self):\n"
        "        await self._factory.transfer_token(a=1)\n"
        "        return {'nft_transferred': True}\n"
    )
    good = (
        "class S:\n"
        "    async def sale(self):\n"
        "        r = await self._factory.transfer_token(a=1)\n"
        "        return {'nft_transferred': r.get('status') != 'not_deployed'}\n"
    )
    assert discards(bad), "D10 does not fire on the shape it exists for"
    assert not discards(good), (
        "D10 fires on a caller that CAPTURES and CHECKS the refusal — it would "
        "flag the fix, which is worse than a blind spot"
    )


def test_the_scope_limit_is_recorded_not_implied():
    """The captured-but-unchecked form is NOT covered, and saying so is part of
    the control. A detector whose name or green implies more than it checks is
    the same defect as a method whose docstring overstates its behaviour — the
    reason D6 was renamed."""
    doc = __doc__ or ""
    assert "does NOT catch" in doc and "CAPTURES" in doc
