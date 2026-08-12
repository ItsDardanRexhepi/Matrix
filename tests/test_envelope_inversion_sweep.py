"""An inner payload saying `error` must not be wrapped in an outer `ok`.

RUN-4 RECURRED ON A SURFACE ITS CONTROL COULD NOT SEE. The original finding
described a CLASS — a success envelope wrapping a failing payload — and was closed
with `tests/test_envelope_inversion.py`, which imports `ServiceRoutes` and asserts
on `routes._ok(...)` BY NAME. That is a unit test of one function, not a detector
for a pattern. The logic it encodes is correct and would have caught this; it was
simply never pointed anywhere else.

So `CapabilityRegistry.invoke` returned, unconditionally:

    {"status": "ok", "capability_id": ..., "action": ..., "result": result}

with `result` being the dispatcher's envelope — `{"status": "error",
"error_category": "not_implemented", ...}` for a refusal. Outer ok, inner error,
HTTP 200, for the entire life of the engagement.

A FINDING ABOUT A PATTERN CLOSED BY A TEST ABOUT AN INSTANCE IS NOT CLOSED. That
is why this file sweeps instead of asserting on a name.

═══════════════════════════════════════════════════════════════════════════
THE RATCHET IS "ONE UNDER THIS QUERY", NOT "ONE IN THE CODEBASE".
═══════════════════════════════════════════════════════════════════════════

A number whose scope is unstated is misleading regardless of whether it is right.
This query narrows deliberately, and the narrowing is a JUDGMENT CALL — the same
kind of call that made RUN-4's control too narrow. It cannot be escaped, only made
explicitly and recorded. What it EXCLUDES:

  * INCREMENTAL CONSTRUCTION. Only `return {...}` dict literals are examined. A
    site building its response piecewise — `resp = {}; resp["status"] = "ok";
    resp["data"] = inner` — is invisible here.
  * SYNCHRONOUS DELEGATES. Only names bound from an `await` count as "another
    layer's answer". A sync call wrapped the same way would not fire.
  * COMPUTED CARRIES. A broader form of this query returns 13 sites; twelve carry
    computed scalars (`gas_limit`, `cost_eth`, `tweet_id`) which are not envelopes
    and cannot invert. Requiring a bare name bound from an await is what
    distinguishes a wrapped ANSWER from a wrapped VALUE.

Neither excluded form is believed to occur in this repo. That belief is NOT
tested, and saying so is the point.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEARCH_ROOTS = ("runtime", "gateway", "extensions", "sdk")

#: Status values that assert the call worked.
SUCCESS_STATUSES = {"ok", "success", "completed"}


def find_wrapped_answers() -> list[str]:
    """Sites returning a literal success status while carrying an awaited result."""
    hits: list[str] = []

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

            for fn in [n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                awaited: dict[str, str] = {}
                for node in ast.walk(fn):
                    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Await):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                awaited[target.id] = ast.unparse(node.value)[:60]
                if not awaited:
                    continue

                for node in ast.walk(fn):
                    if not (isinstance(node, ast.Return)
                            and isinstance(node.value, ast.Dict)):
                        continue
                    literal_status = None
                    carried: list[str] = []
                    for key, value in zip(node.value.keys, node.value.values):
                        if (isinstance(key, ast.Constant) and key.value == "status"
                                and isinstance(value, ast.Constant)):
                            literal_status = value.value
                        if isinstance(value, ast.Name) and value.id in awaited:
                            carried.append(f"{value.id} <- {awaited[value.id]}")
                    if literal_status in SUCCESS_STATUSES and carried:
                        hits.append(
                            f"{rel}:{node.lineno} {fn.name}() returns literal "
                            f"status={literal_status!r} while carrying {carried}"
                        )
    return hits


def test_no_site_wraps_an_awaited_answer_in_an_unconditional_success():
    """RATCHET AT ONE — and the one is a KNOWN, RECORDED defect, not an accepted
    one.

    `CapabilityRegistry.invoke` is deliberately left in place: it is the known
    instance of a far larger architectural finding (enforcement lives at the
    caller rather than the chokepoint — `invoke` satisfies ZERO of the nine
    contracts the gateway `_call` path enforces), which is on the deferred
    register merged with NEW-82 and scoped as a design change rather than a
    patch. Fixing this one contract on this one caller would be the same
    instance-not-pattern error RUN-4 made, made knowingly.

    If this count rises, a NEW inversion has appeared and wants fixing on its own
    terms.
    """
    hits = find_wrapped_answers()

    assert len(hits) == 1, (
        "envelope-inversion count changed — expected exactly the known "
        f"CapabilityRegistry.invoke site:\n  " + "\n  ".join(hits)
    )
    assert "capabilities/registry.py" in hits[0], (
        f"the one known site is no longer the one found: {hits[0]}"
    )


def test_the_detector_sees_the_shape_it_exists_for():
    """PROVEN IN BOTH DIRECTIONS. A detector that cannot fire is a detector that
    reports clean."""

    def hits(src: str) -> bool:
        tree = ast.parse(src.strip())
        fn = tree.body[0]
        awaited = {t.id for n in ast.walk(fn)
                   if isinstance(n, ast.Assign) and isinstance(n.value, ast.Await)
                   for t in n.targets if isinstance(t, ast.Name)}
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)):
                continue
            lit, carried = None, False
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and k.value == "status" and isinstance(v, ast.Constant):
                    lit = v.value
                if isinstance(v, ast.Name) and v.id in awaited:
                    carried = True
            if lit in SUCCESS_STATUSES and carried:
                return True
        return False

    # THE DEFECT: the invoke shape.
    assert hits('''
async def invoke(self):
    result = await dispatcher.execute()
    return {"status": "ok", "result": result}
''') is True, "the detector cannot see the exact shape it exists for"

    # CORRECT: the inner status is propagated rather than overwritten.
    assert hits('''
async def invoke(self):
    result = await dispatcher.execute()
    return {"status": result.get("status", "ok"), "result": result}
''') is False, "the detector fires on a correctly-propagated status"

    # CORRECT: a computed value is not another layer's answer.
    assert hits('''
async def estimate(self):
    price = await get_price()
    return {"status": "ok", "cost": price * 2}
''') is False, "the detector fires on a wrapped VALUE rather than a wrapped ANSWER"

    # CORRECT: an honest failure envelope.
    assert hits('''
async def invoke(self):
    result = await dispatcher.execute()
    return {"status": "error", "result": result}
''') is False, "the detector fires on an error envelope"


def test_the_sweep_is_actually_reading_the_tree():
    """GUARD THE GUARD. A sweep that silently collected nothing would report one
    hit short and read as a fix."""
    scanned = sum(len(list((ROOT / r).rglob("*.py")))
                  for r in SEARCH_ROOTS if (ROOT / r).exists())

    assert scanned > 200, (
        f"only {scanned} files reachable — the search roots moved and this "
        "detector is no longer looking at the codebase"
    )
