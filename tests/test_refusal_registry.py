"""NEW-94c — the shared refusal registry is load-bearing, so it is proven.

tests/refusal_primitives.py is now a dependency of THREE controls — D6
(gate asymmetry / fabrication shape), D7 (fake delivery), D10 (discarded
refusal). It exists because NEW-94 wrapped `not_deployed_response` in
`staking_not_deployed` and D6, which matched the old literal and skipped files
that never mention it, went blind to the entire staking package — while its
count fell from 7/11 to 6/10, which read as confirmation that the staking
asymmetry had been fixed. A verifier disabled EVERY staking gate and re-ran:
still 6/10, still no staking entry. The instrument had stopped looking.

The registry makes that blinding impossible rather than detected. But a shared
dependency that is not itself proven is a SINGLE POINT OF SILENT FAILURE FOR
ALL THREE CONTROLS — the same category of defect, one level up. So this file
proves it, in both directions:

  1. NO DETECTOR MAY MATCH A REFUSAL NAME IT DID NOT GET FROM THE REGISTRY.
     Otherwise the class comes back one hardcoded literal at a time: a future
     detector writes "not_deployed_response" inline, the next wrapper lands,
     and only that one control goes quiet.

  2. THE REGISTRY MUST ACTUALLY DRIVE WHAT THE DETECTORS SEE. Add a name and
     they must recognise the new wrapper; remove one and they must stop. A
     registry every detector imports but none depends on is decoration, and it
     would look identical from the outside.

Requirement 2 is why the detectors call `mentions_refusal()` /
`is_refusal_name()` instead of binding `REFUSAL_PRIMITIVES` at import time: the
functions resolve the tuple at CALL time, which is the indirection that lets
this file mutate the registry and observe the consequence.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from tests import refusal_primitives
from tests import test_discarded_refusal_detector as d10
from tests import test_fake_delivery_detector as d7
from tests import test_uuid_mint_fabrication_shape as d6

TESTS_DIR = pathlib.Path(__file__).resolve().parent

#: Every module that recognises refusals by NAME. Adding a fourth detector to
#: the suite means adding it here.
DETECTOR_MODULES = (
    "test_uuid_mint_fabrication_shape.py",
    "test_fake_delivery_detector.py",
    "test_discarded_refusal_detector.py",
)


# ── Requirement 1: no detector may hardcode a refusal name ───────────────


def _matcher_string_literals(path: pathlib.Path) -> list[str]:
    """String constants in a file's MATCHING code.

    Two exclusions, both deliberate and both structural rather than textual:

    DOCSTRINGS. Every control in this suite explains itself in prose that
    quotes the very names it matches on. A check that could not tell those
    apart would be unusable — and twice already a grep-based test here has been
    tripped by a docstring quoting the literal it was written to forbid.

    `test_*` FUNCTION BODIES. The requirement is that no detector MATCHES on a
    name it did not get from the registry. A test asserting something ABOUT a
    primitive — `is_refusal_name("staking_not_deployed")`, or D10 checking that
    pools.py no longer names the primitive directly — is not a matcher, and
    forbidding it would push those assertions into indirection that made them
    harder to read for no gain. Module-level constants ARE included: D7's
    hardcoded whitelist tuple lived at module level, and that is precisely the
    form this must catch.
    """
    tree = ast.parse(path.read_text())

    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                skip.add(id(body[0].value))
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        ):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    skip.add(id(inner))

    return [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in skip
    ]


def test_no_detector_hardcodes_a_refusal_name():
    """REQUIREMENT 1.

    A detector that writes a primitive's name inline is not using the registry,
    so the next wrapper blinds it alone and silently — exactly what happened to
    D6, and what D7 was one rename away from (it hardcoded
    "not_deployed_response" in its real-or-refuses whitelist, where the failure
    mode is inverted: an unregistered wrapper makes an honest refusal look like
    a fake delivery).
    """
    offenders: dict[str, list[str]] = {}
    for name in DETECTOR_MODULES:
        hardcoded = [
            s for s in _matcher_string_literals(TESTS_DIR / name)
            if s in refusal_primitives.REFUSAL_PRIMITIVES
        ]
        if hardcoded:
            offenders[name] = sorted(set(hardcoded))

    assert not offenders, (
        f"detector(s) hardcoding a refusal primitive: {offenders}. Import "
        "tests.refusal_primitives and call mentions_refusal()/"
        "is_refusal_name() instead — a hardcoded literal means the next "
        "wrapper blinds this control alone, and quietly."
    )


def test_the_hardcode_check_can_actually_fire():
    """Proven in both directions (rule 35).

    A scan that cannot distinguish a live literal from a docstring mention
    would be trivially green here, since every one of these files discusses
    the names at length in prose.
    """
    honest = "\n".join([
        '"""A docstring mentioning not_deployed_response at length."""',
        "from tests import refusal_primitives",
        "x = refusal_primitives.is_refusal_name(name)",
        "def test_it():",
        '    assert refusal_primitives.is_refusal_name("staking_not_deployed")',
    ])
    cheating = "\n".join([
        '"""A docstring mentioning not_deployed_response at length."""',
        '_WHITELIST = ("send_transaction", "not_deployed_response")',
    ])
    tmp = TESTS_DIR / "_registry_probe.py"
    try:
        tmp.write_text(honest)
        assert not [
            s for s in _matcher_string_literals(tmp)
            if s in refusal_primitives.REFUSAL_PRIMITIVES
        ], "the check fires on a file that only MENTIONS the name in prose"

        tmp.write_text(cheating)
        assert [
            s for s in _matcher_string_literals(tmp)
            if s in refusal_primitives.REFUSAL_PRIMITIVES
        ], "the check does not fire on a genuine hardcoded literal"
    finally:
        tmp.unlink(missing_ok=True)


def test_every_detector_imports_the_registry():
    """The other half of requirement 1: not hardcoding is necessary but not
    sufficient — a detector could simply stop recognising refusals at all."""
    for name in DETECTOR_MODULES:
        src = (TESTS_DIR / name).read_text()
        assert "from tests import refusal_primitives" in src, (
            f"{name} recognises refusals by name but does not import the "
            "registry"
        )


# ── Requirement 2: the registry must drive the detectors ─────────────────


@pytest.fixture
def registry(monkeypatch):
    """Mutate REFUSAL_PRIMITIVES for the duration of one test.

    Patching the MODULE ATTRIBUTE works only because the detectors call
    `mentions_refusal()` / `is_refusal_name()` rather than holding their own
    import-time copy of the tuple. If someone reintroduces
    `from ... import REFUSAL_PRIMITIVES` in a detector, these tests stop being
    able to move it — and `test_no_detector_hardcodes_a_refusal_name` plus
    `test_every_detector_imports_the_registry` are what keep that from
    happening quietly.
    """
    class _Registry:
        @staticmethod
        def set(*names: str) -> None:
            monkeypatch.setattr(
                refusal_primitives, "REFUSAL_PRIMITIVES", tuple(names)
            )
    return _Registry()


def test_removing_a_name_makes_the_detectors_stop_recognising_it(registry):
    """THE BLINDING, REPRODUCED ON PURPOSE.

    Drop `staking_not_deployed` and the registry is back to what it was when
    D6 went blind. All three controls must visibly lose the staking domain —
    if any of them is unaffected, it is not really consulting the registry.
    """
    # Baseline: with the wrapper registered, D6 sees staking as fully gated
    # and D10 recognises the pool methods as refusers.
    assert {"add_stake", "remove_stake", "create_pool"} <= d10._refusing_methods()
    assert d6._is_gated(_staking_fn("add_stake")) is True

    registry.set("not_deployed_response")          # the pre-NEW-94 registry

    blinded = d10._refusing_methods()
    assert "add_stake" not in blinded, (
        "D10 still recognises a staking refuser after the wrapper was "
        "unregistered — it is not consulting the registry"
    )
    assert d6._is_gated(_staking_fn("add_stake")) is False, (
        "D6 still reads add_stake as gated — this is the exact blindness the "
        "registry exists to prevent, and it is not being driven by it"
    )
    assert "staking_not_deployed" not in d7._real_or_refuses(), (
        "D7's whitelist did not follow the registry"
    )


def test_adding_a_name_makes_the_detectors_see_a_new_wrapper(registry):
    """The positive half. Registering a name that exists in the code as a
    real call must make the detectors recognise its callers.

    `_require_pool` is a genuine method in pools.py, called by `add_stake` and
    `remove_stake`. It is NOT a refusal — it is borrowed here precisely because
    it is inert, so the only thing that can change the detectors' answer is the
    registry entry itself.
    """
    before = d10._refusing_methods()
    assert "get_pool" not in before

    registry.set("not_deployed_response", "staking_not_deployed", "_require_pool")

    after = d10._refusing_methods()
    assert after > before, "adding a registry name changed nothing"
    assert "_require_pool" in d7._real_or_refuses()
    assert refusal_primitives.is_refusal_name("_require_pool")


def test_the_registry_functions_resolve_at_call_time():
    """The mechanism the two mutation tests depend on, asserted directly.

    A module-level `from ... import REFUSAL_PRIMITIVES` in the registry's own
    helpers would freeze the tuple and make every mutation above a no-op that
    still passed — the tests would be measuring nothing.
    """
    original = refusal_primitives.REFUSAL_PRIMITIVES
    try:
        refusal_primitives.REFUSAL_PRIMITIVES = ("zzz_probe",)
        assert refusal_primitives.is_refusal_name("zzz_probe")
        assert not refusal_primitives.is_refusal_name("not_deployed_response")
        assert refusal_primitives.mentions_refusal("x = zzz_probe()")
        assert not refusal_primitives.mentions_refusal("x = not_deployed_response()")
    finally:
        refusal_primitives.REFUSAL_PRIMITIVES = original

    assert refusal_primitives.is_refusal_name("not_deployed_response")


# ── helper ───────────────────────────────────────────────────────────────


def _staking_fn(name: str) -> ast.AST:
    """The AST of a named method in the staking pool manager."""
    src = (
        pathlib.Path(__file__).resolve().parent.parent
        / "runtime/blockchain/services/staking/pools.py"
    ).read_text()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"staking method {name} not found")
