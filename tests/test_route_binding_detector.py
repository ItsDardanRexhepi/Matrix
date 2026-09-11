"""D8 — every gateway handler must be able to CALL the method it targets.

THE LAYER FINDING. This is not a collection of local defects. Measured at
b81a00f, 49 of 105 handler→method bindings could not execute: fewer than 54% of
the platform's HTTP routes could reach the method they name. The route layer was
written against IMAGINED signatures and never once exercised against the service
layer.

That reframes earlier findings retroactively. Domain 4 found one dead route.
Domain 5 found five. Domain 7 found `/claim/settle` pointing at a method that
never existed. Each looked local. They were samples of this.

THREE CLASSES, three dispositions:

  SERVICE-MISSING  the target service does not exist at all
                   (`prediction`, `legal`, `ai`, `energy` — no package, no
                   class, no registry entry). Route deletion.
  MISMATCH         service and method exist; the forwarded kwarg NAMES do not
                   bind. HTTP 400 "That request could not be understood" — a
                   SERVER signature bug reported as a CLIENT error.
  METHOD-MISSING   service exists, method does not. HTTP 404 "Method 'x' not
                   found on 'y'".

WHY A DETECTOR AND NOT JUST A CLEANUP. A one-time fix leaves the class free to
regrow the next time someone writes a handler against a signature they remember
rather than one they checked. Binding is mechanically checkable, so it should be
mechanically checked. Same move that made D2 a real gate.

HOW IT CHECKS: resolve each `self._call("svc", "meth", k=…)` through the REAL
ServiceRegistry and bind the forwarded kwarg names against the real signature
with `inspect.Signature.bind`. Names only — this cannot catch a kwarg that binds
but carries a semantically wrong value (a `token` where a `pool_id` was meant).
That limit is stated rather than papered over; semantic correctness is a reading
judgment and belongs in the census, not here.

RATCHET: frozen BY NAME, may only shrink.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

ROUTES = pathlib.Path(__file__).resolve().parent.parent / "gateway/service_routes.py"


def find_broken_bindings() -> dict[str, str]:
    """Map ``handler -> CLASS`` for every binding that cannot execute."""
    from runtime.blockchain.services.registry import ServiceRegistry

    reg = ServiceRegistry({})
    broken: dict[str, str] = {}
    tree = ast.parse(ROUTES.read_text())

    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not fn.name.startswith("_handle_"):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "attr", None) != "_call":
                continue
            if len(node.args) < 2:
                continue
            try:
                service = ast.literal_eval(node.args[0])
                method = ast.literal_eval(node.args[1])
            except (ValueError, SyntaxError):
                continue
            # A **kwargs splat cannot be checked statically; skip rather than
            # guess, and say so here so the gap is visible.
            if any(k.arg is None for k in node.keywords):
                continue
            kwargs = [k.arg for k in node.keywords if k.arg]

            try:
                instance = reg.get(service)
            except Exception:
                broken[fn.name] = "SERVICE-MISSING"
                continue
            bound = getattr(instance, method, None)
            if bound is None:
                broken[fn.name] = "METHOD-MISSING"
                continue
            try:
                inspect.signature(bound).bind(**dict.fromkeys(kwargs))
            except TypeError:
                broken[fn.name] = "MISMATCH"
    return broken


# ── The frozen inventory (measured 2026-08-11; ratchet: may only shrink) ──
#
# 49 at introduction -> 38 (SERVICE-MISSING deletions) -> 18 (NEW-89
# Tier 1 + Tier 2). The 18 that remain are exactly the client-called set.
#
# The 11 SERVICE-MISSING routes are GONE, and the triage that produced that is
# worth recording, because "the service does not exist, so delete" turned out to
# be the right answer for THREE DIFFERENT REASONS — and the reasons mattered:
#
#   2 were DUPLICATES of a working route. /api/v1/ai/agent/register and
#     /api/v1/legal/dispute/file target services that do not exist, but
#     /api/v1/agent/register and /api/v1/dispute/file already serve those exact
#     operations. Repointing would have created two routes to one method — the
#     D2 handler-collapse defect.
#
#   6 WOULD HAVE BEEN REPOINTED ONTO A KNOWN FABRICATION. A real implementation
#     exists under another service name for carbon buy/retire, license grant,
#     agreement execute, model trade and prediction-market create — and every
#     one of those targets is on D6's frozen fabrication list. Repointing would
#     have converted an honest 404 into a convincing fake. That is strictly
#     worse than the defect: a 404 tells the truth.
#
#   3 had no implementation anywhere.
#
# So the triage did not change the disposition and was still necessary: without
# it, 8 of the 11 would have been "helpfully" repointed, 6 onto fabrications.

KNOWN_BROKEN_BINDINGS = {
    # ── TIER 3 ONLY — the 18 routes the shipped iOS client CALLS ────────
    #
    # Tier 1 (17) and Tier 2 (3) are CLEARED by NEW-89. What remains is the
    # coordination gate: every route below is invoked by MTRX today, so the
    # server contract cannot be chosen unilaterally. Fixing a route the client
    # calls with the wrong shape does not fix the feature — it MOVES the
    # breakage, from a server that rejects the call to a server that accepts a
    # call the client is not making correctly.
    #
    # These stay broken ON PURPOSE until the intended contract is chosen per
    # route. A 400 is a safe state; a route that accepts the wrong shape is not.
    "_handle_agent_register": "MISMATCH",
    "_handle_bridge_execute": "METHOD-MISSING",
    "_handle_bridge_quote": "METHOD-MISSING",
    "_handle_fundraising_create": "MISMATCH",
    "_handle_governance_create": "MISMATCH",
    "_handle_insurance_create": "MISMATCH",
    "_handle_ip_register": "MISMATCH",
    "_handle_nft_mint": "MISMATCH",
    "_handle_rwa_listings": "METHOD-MISSING",
    "_handle_rwa_tokenize": "MISMATCH",
    "_handle_securities_create": "MISMATCH",
    "_handle_social_post": "METHOD-MISSING",
    "_handle_stablecoin_transfer": "MISMATCH",
    "_handle_staking_stake": "MISMATCH",
    "_handle_staking_unstake": "MISMATCH",
    "_handle_swap_execute": "METHOD-MISSING",
    "_handle_swap_route": "METHOD-MISSING",
    "_handle_zk_proof": "METHOD-MISSING",
}


def test_no_new_broken_bindings():
    """A handler that cannot call its target is a route that cannot work."""
    current = find_broken_bindings()

    new = set(current) - set(KNOWN_BROKEN_BINDINGS)
    assert not new, (
        "new handler(s) cannot bind to the method they target — the route "
        f"layer has drifted from the service layer again: "
        f"{ {h: current[h] for h in sorted(new)} }"
    )

    fixed = set(KNOWN_BROKEN_BINDINGS) - set(current)
    assert not fixed, (
        "these now bind — remove them from KNOWN_BROKEN_BINDINGS to tighten "
        f"the ratchet: {sorted(fixed)}"
    )


def test_the_class_of_each_known_break_is_unchanged():
    """A MISMATCH silently becoming a METHOD-MISSING (or vice versa) means
    something moved underneath; the ratchet should notice."""
    current = find_broken_bindings()
    drifted = {
        h: (KNOWN_BROKEN_BINDINGS[h], current[h])
        for h in KNOWN_BROKEN_BINDINGS
        if h in current and current[h] != KNOWN_BROKEN_BINDINGS[h]
    }
    assert not drifted, f"binding class changed: {drifted}"


def test_the_measured_counts_are_recorded():
    """BURN-DOWN: 49 at introduction -> 38 after the SERVICE-MISSING deletions.

    22 MISMATCH + 16 METHOD-MISSING remain, each needing its own disposition:
    MISMATCH is not uniformly a rename (several are semantic gaps where the
    route never collects what the method needs), and METHOD-MISSING needs the
    NEW-81 judgment per item.
    """
    current = find_broken_bindings()
    assert len(KNOWN_BROKEN_BINDINGS) == 18
    assert len(current) == 18

    by_class: dict[str, int] = {}
    for cls in current.values():
        by_class[cls] = by_class.get(cls, 0) + 1
    assert by_class == {"MISMATCH": 11, "METHOD-MISSING": 7}, by_class


def test_the_deleted_service_missing_routes_stay_deleted():
    """The 11 are gone from BOTH registration tables and their handler bodies
    are removed. An unregistered handler is still a callable path."""
    src = ROUTES.read_text()
    for handler in (
        "_handle_ai_agent_register", "_handle_ai_model_trade",
        "_handle_carbon_buy", "_handle_carbon_prices", "_handle_carbon_retire",
        "_handle_agreement_execute", "_handle_legal_dispute_file",
        "_handle_license_grant", "_handle_market_bet", "_handle_market_create",
        "_handle_market_list",
    ):
        assert handler not in src, f"{handler} came back"

    for service in ('"prediction"', '"legal"', '"ai"', '"energy"'):
        assert f"self._call(\n            {service}" not in src


def test_the_canonical_routes_that_survived_are_still_registered():
    """Two of the eleven were DUPLICATES of working routes. Deleting the wrong
    one of a pair is silent — it just removes a capability."""
    src = ROUTES.read_text()
    assert "/api/v1/agent/register" in src
    assert "/api/v1/dispute/file" in src


def test_the_binder_cannot_check_kwargs_splats():
    """States the detector's blind spot rather than leaving it implicit.

    A handler forwarding **kwargs is skipped, because the names are not
    statically known. One such handler exists today; if that number grows, the
    detector's coverage silently shrinks.
    """
    tree = ast.parse(ROUTES.read_text())
    splats = 0
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not fn.name.startswith("_handle_"):
            continue
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "_call"
                and any(k.arg is None for k in node.keywords)
            ):
                splats += 1
    assert splats <= 1, (
        f"{splats} handlers now forward **kwargs and are invisible to D8; "
        "the detector's coverage has shrunk"
    )
