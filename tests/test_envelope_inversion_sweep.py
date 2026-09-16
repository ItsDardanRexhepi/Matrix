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

from runtime.protocols.outcome_truth import OUTCOME_FIELD

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEARCH_ROOTS = ("runtime", "gateway", "extensions", "sdk")

#: Status values that assert the call worked.
SUCCESS_STATUSES = {"ok", "success", "completed"}


def states_the_wrapped_verdict(node: ast.Dict) -> bool:
    """True when this returned dict STATES the outcome of what it carries.

    A wrapper that says "I served this request" over a payload that says the
    action was refused is an inversion. A wrapper that ALSO states the verdict
    it read out of that payload is not: both claims are made, and the reader
    is no longer left with only the one about the wrapping.

    Two conditions, and the second is the one that matters. The key is the
    platform's stated-verdict field, spelled through the symbol as the tree
    spells it everywhere. And the value is COMPUTED — `OUTCOME_FIELD:
    report_of(result)` states what the carried payload said; `OUTCOME_FIELD:
    "success"` would be the same unconditional claim wearing a second field,
    and still fires.
    """
    for key, value in zip(node.keys, node.values):
        named = ((isinstance(key, ast.Name) and key.id == "OUTCOME_FIELD")
                 or (isinstance(key, ast.Constant) and key.value == OUTCOME_FIELD))
        if named and not isinstance(value, ast.Constant):
            return True
    return False


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
                    if (literal_status in SUCCESS_STATUSES and carried
                            and not states_the_wrapped_verdict(node.value)):
                        hits.append(
                            f"{rel}:{node.lineno} {fn.name}() returns literal "
                            f"status={literal_status!r} while carrying {carried}"
                        )
    return hits


def test_no_site_wraps_an_awaited_answer_in_an_unconditional_success():
    """RATCHET AT ZERO. It stood at one, and the one is now closed.

    `CapabilityRegistry.invoke` was left in place as a recorded defect: the
    known instance of a larger architectural finding (enforcement at the caller
    rather than the chokepoint — `invoke` satisfies none of the contracts the
    gateway `_call` path enforces), deferred as a design change. What was NOT
    deferrable is the half this file is about: the envelope answered for what
    it wrapped. It states the carried payload's own verdict now, and
    `POST /api/v1/capabilities/{id}/invoke` answers a `not_deployed` with 503
    rather than 200 — the same answer the /api/v1 route for the same service
    gives. The deferred half is still deferred, and it is not this query's.

    If this count rises, a NEW inversion has appeared and wants fixing on its
    own terms.
    """
    hits = find_wrapped_answers()

    assert hits == [], (
        "an envelope states a success over an answer it did not read:\n  "
        + "\n  ".join(hits)
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
            if (lit in SUCCESS_STATUSES and carried
                    and not states_the_wrapped_verdict(node.value)):
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

    # CORRECT: the wrapping is claimed and the wrapped verdict is STATED. Both
    # claims are made, which is the fix this query was ratcheted down for.
    assert hits('''
async def invoke(self):
    result = await dispatcher.execute()
    return {"status": "ok", OUTCOME_FIELD: report_of(result), "result": result}
''') is False, "a wrapper that states what it wraps is not an inversion"

    # THE DEFECT, WEARING THE FIX'S CLOTHES: a hard-coded verdict states
    # nothing about the payload — it is the same unconditional claim twice.
    assert hits('''
async def invoke(self):
    result = await dispatcher.execute()
    return {"status": "ok", OUTCOME_FIELD: "success", "result": result}
''') is True, "a literal outcome was accepted as a reading of the payload"


def test_the_sweep_is_actually_reading_the_tree():
    """GUARD THE GUARD. A sweep that silently collected nothing would report one
    hit short and read as a fix."""
    scanned = sum(len(list((ROOT / r).rglob("*.py")))
                  for r in SEARCH_ROOTS if (ROOT / r).exists())

    assert scanned > 200, (
        f"only {scanned} files reachable — the search roots moved and this "
        "detector is no longer looking at the codebase"
    )
