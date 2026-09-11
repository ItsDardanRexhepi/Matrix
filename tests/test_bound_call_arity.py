"""A `self.method(...)` call whose argument count its target cannot accept.

THE STANDING RULE THIS ENFORCES: a removal is not complete until a symbol diff
proves exactly the intended names left. This is the mechanical half of that rule
— the half that runs on every commit instead of being remembered.

THE NEIGHBOUR-DELETION TRAP, THIRD INSTANCE. Deleting a method takes whatever is
lexically adjacent to it if the hunk boundary lands wrong. In 3e931d4 the
`migrate_members` hunk ended on the `@staticmethod` decorator belonging to the
NEXT method, so `_calculate_voting_power` silently became an instance method and
`self._calculate_voting_power(a, b, c)` began passing four arguments to three
parameters. `ConversionWizard.convert()` raised TypeError on every call and the
2000-test suite did not notice, because nothing called it.

The previous two instances of this class were caught by a symbol diff run by
hand. It was not run here. So it becomes a test.

WHY ARITY AND NOT "IS IT A STATICMETHOD". Pinning the decorator would catch this
one symbol. The DEFECT is the mismatch between how a method is called and what
it can accept, and a lost decorator is only one way to produce it — renaming a
parameter, adding a required argument, or changing binding all land in the same
place. The shape is the thing worth detecting.

DELIBERATE LIMITS, stated rather than implied:
  * only `self.<name>(...)` calls resolved against a method defined in the SAME
    class — inherited and mixin methods are skipped, since resolving them needs
    an MRO this AST pass does not have;
  * any target taking *args or **kwargs is skipped (it can absorb anything);
  * any call using *unpacking or **unpacking is skipped for the same reason;
  * decorators other than static/class/property/abstract mean the wrapper may
    change the signature, so those targets are skipped.
Each limit trades a possible miss for not crying wolf, which is the standing
trade-off in this engagement: a control that fires on correct code creates
pressure to delete it.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Trees this control walks. Tests are excluded — fixtures legitimately use
#: signatures a static reading cannot follow.
SEARCH_ROOTS = ("runtime", "gateway", "extensions")

#: Decorators that leave the signature readable from the source.
_SIGNATURE_PRESERVING = {
    "staticmethod", "classmethod", "property", "abstractmethod",
    "cached_property", "abstractproperty",
}


def _decorators(fn: ast.AST) -> set[str]:
    names = set()
    for dec in fn.decorator_list:
        node = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _arity(fn: ast.AST) -> tuple[int, int] | None:
    """(min, max) positional arguments the DEFINITION accepts, or None if it
    can absorb anything."""
    args = fn.args
    if args.vararg is not None or args.kwarg is not None:
        return None
    positional = args.posonlyargs + args.args
    total = len(positional)
    required = total - len(args.defaults)

    decs = _decorators(fn)
    if decs - _SIGNATURE_PRESERVING:
        return None                       # an unknown wrapper may re-sign it
    if "staticmethod" in decs:
        return required, total            # `self.f(...)` passes NO implicit arg
    # instance and class methods both consume one implicit leading argument
    return max(0, required - 1), max(0, total - 1)


def find_arity_mismatches() -> list[str]:
    """Every `self.m(...)` passing a count its own class's `m` cannot accept."""
    bad: list[str] = []

    for root in SEARCH_ROOTS:
        base = ROOT / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            rel = path.relative_to(ROOT)

            for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
                defined = {
                    f.name: f for f in cls.body
                    if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                for node in ast.walk(cls):
                    if not isinstance(node, ast.Call):
                        continue
                    fn = node.func
                    if not (
                        isinstance(fn, ast.Attribute)
                        and isinstance(fn.value, ast.Name)
                        and fn.value.id == "self"
                        and fn.attr in defined
                    ):
                        continue
                    if any(isinstance(a, ast.Starred) for a in node.args):
                        continue
                    if any(k.arg is None for k in node.keywords):
                        continue

                    bounds = _arity(defined[fn.attr])
                    if bounds is None:
                        continue
                    low, high = bounds
                    passed = len(node.args)
                    if passed > high or passed + len(node.keywords) < low:
                        bad.append(
                            f"{rel}::{cls.name}.{fn.attr} — call at line "
                            f"{node.lineno} passes {passed} positional "
                            f"(+{len(node.keywords)} keyword); the definition "
                            f"accepts {low}..{high}"
                        )
    return bad


def test_no_bound_call_passes_an_impossible_argument_count():
    """THE CONTROL. Ratchet at zero.

    A mismatch here is a guaranteed TypeError at runtime on a path the test
    suite may not cover — which is precisely how `ConversionWizard.convert()`
    shipped broken behind 2000 passing tests.
    """
    mismatches = find_arity_mismatches()

    assert not mismatches, (
        "bound call(s) whose target cannot accept the arguments passed — each "
        "raises TypeError when reached:\n  " + "\n  ".join(mismatches)
    )


def test_the_control_sees_the_defect_it_was_built_for():
    """PROVEN IN BOTH DIRECTIONS — reproducing the exact 3e931d4 regression."""

    def mismatches(src: str) -> bool:
        tree = ast.parse(src.strip())
        cls = tree.body[0]
        defined = {
            f.name: f for f in cls.body
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(cls):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                    and fn.value.id == "self" and fn.attr in defined):
                continue
            bounds = _arity(defined[fn.attr])
            if bounds is None:
                continue
            low, high = bounds
            if len(node.args) > high or len(node.args) + len(node.keywords) < low:
                return True
        return False

    # THE REGRESSION: the decorator is gone, so `self.f(a, b, c)` passes four.
    assert mismatches('''
class W:
    def convert(self):
        return self._power(1, 2, "x")
    def _power(self, shares, total, kind):
        return 0.0
''') is False, "an ordinary instance method taking self + 3 must NOT fire"

    assert mismatches('''
class W:
    def convert(self):
        return self._power(1, 2, "x")
    def _power(shares, total, kind):
        return 0.0
''') is True, "the control cannot see the exact defect it exists for"

    # THE FIX: decorator restored — three parameters, no implicit self.
    assert mismatches('''
class W:
    def convert(self):
        return self._power(1, 2, "x")
    @staticmethod
    def _power(shares, total, kind):
        return 0.0
''') is False, "the control fires on the CORRECTED form"

    # Not a mismatch: defaults widen the accepted range.
    assert mismatches('''
class W:
    def go(self):
        return self._f(1)
    def _f(self, a, b=2, c=3):
        return a
''') is False, "the control ignores defaults"

    # Not a mismatch: *args absorbs anything.
    assert mismatches('''
class W:
    def go(self):
        return self._f(1, 2, 3, 4, 5)
    def _f(self, *args):
        return args
''') is False, "the control fires on a *args target"

    # Too FEW arguments is equally fatal, and equally invisible to a green suite.
    assert mismatches('''
class W:
    def go(self):
        return self._f(1)
    def _f(self, a, b, c):
        return a
''') is True, "the control misses an under-supplied call"


def test_the_control_is_actually_looking_at_the_tree():
    """GUARD THE GUARD. A scan that silently collected nothing would report
    zero mismatches and look identical to a clean tree."""
    scanned = 0
    for root in SEARCH_ROOTS:
        base = ROOT / root
        if base.exists():
            scanned += len(list(base.rglob("*.py")))

    assert scanned > 200, (
        f"only {scanned} files reachable — the search roots moved and this "
        "control is no longer looking at the codebase"
    )
