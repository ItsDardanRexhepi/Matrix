"""D2 — Handler-collapse detector.

RUN-2 was two routes (`/contracts/convert` and `/contracts/deploy`) whose
handlers were byte-identical and both dispatched to
``contract_conversion.convert``. A client POSTing to ``/deploy`` got HTTP 200
and concluded a contract was deployed. It never was — the service has no
``deploy`` method at all.

That turned out not to be one router typo but a shape repeated across three
independent dispatch tables. This detector builds the
``route -> (service, method)`` mapping from each of them and fails on any
target reached by two different names that is not in an explicit, justified
allowlist.

Every allowlist entry is a promise that the aliasing is deliberate AND that the
two names mean the same thing to a caller. "Deploy" and "convert" do not.

Parsing is done with ``ast`` rather than regex because the ``self._call(...)``
sites span multiple lines; a line-oriented pattern silently matches 3 of them
out of 100+ and would make this detector look clean while seeing almost nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVICE_ROUTES = ROOT / "gateway" / "service_routes.py"
DISPATCHER = ROOT / "runtime" / "blockchain" / "services" / "service_dispatcher.py"
CATALOG = ROOT / "runtime" / "capabilities" / "catalog.py"
ROUTES_MD = ROOT / "docs" / "ROUTES.md"

# Deliberate aliases: (service, method) -> why more than one name is correct.
# Adding an entry here is an assertion that a caller cannot be misled by the
# difference between the names. Keep it empty unless that is really true.
ALLOWED_ALIASES: dict[tuple[str, str], str] = {
    # NEW-10. Six adjudicated aliases. Each carries WHY, not just "alias" — a
    # bare name list is a mute button; the reason is what lets the next reviewer
    # tell a deliberate alias from one silenced to green the build.
    #
    # Triage record: 11 collisions were adjudicated. FIVE were bugs, not aliases,
    # and were fixed rather than listed here — `get_price` pointed at the generic
    # `oracle_gateway.request` and returned a validation error on every call
    # (repointed to `query_price`), and four pairs published a feed event under
    # one name and nothing under the other (both names now publish). Judging by
    # name shape — "verb_noun vs noun_verb is just a naming variant" — would have
    # filed all five here and closed them.
    ("did_identity", "create_did"):
        "create_did / did_create are naming-convention variants of one call: "
        "identical target, identical params, identical feed event. The two "
        "routes /identity/create and /identity/did/create are path variants "
        "onto the same handler.",
    ("dispute_resolution", "file_dispute"):
        "dispute_file / file_dispute — same call, same params, same feed event. "
        "Verb-first and noun-first spellings of one operation.",
    ("oracles_plus", "pyth_pull"):
        "pyth_pull / pyth_pull_price — one Pyth pull. Both eventless by design "
        "(a pull is a read), so there is no divergence of the kind that made "
        "the four register/mint/tokenize/custody pairs bugs.",
    ("ip_royalties", "register_ip"):
        "POST /api/v1/ip/register and POST /api/v1/licensing/ip both REGISTER "
        "IP — verified by reading the handler, which takes owner/type/name and "
        "calls register_ip. Registration is the licensing prerequisite, so the "
        "licensing surface exposes it. Licensing ITSELF is the separate "
        "`license_ip` action, which does not collide.",
    ("social", "create_community"):
        "POST /api/v1/groups and POST /api/v1/social/community/create — group "
        "and community are one entity under two product names; the handlers "
        "take identical params (creator, name, description, token_gate).",
    ("oracle_gateway", "query_price"):
        "get_price / oracle_price_query — a genuine alias only AFTER the NEW-10 "
        "fix. get_price previously pointed at the generic `request`, which "
        "requires an oracle_type a price caller never sends, so every call "
        "failed validation. Repointed to `query_price`, which is what "
        "oracle_price_query already used.",

    # The four feed-divergence pairs. They remain collisions — the fix did not
    # remove the second name (deleting a live action breaks callers, and NEW-20
    # already showed client and server disagree about which names exist). What
    # the fix removed was the DIVERGENCE: both names now publish the same event,
    # so which name a caller uses no longer decides whether the state change is
    # recorded. They are aliases now; they were bugs before, and the entry says
    # so, so nobody reads this list as "these were always fine".
    ("agent_identity", "register_agent"):
        "ai_agent_register / register_agent — one registration. WAS A BUG: only "
        "ai_agent_register emitted `ai_agent_registered`; register_agent "
        "recorded nothing. Both now publish (NEW-10).",
    ("gaming", "mint_game_asset"):
        "game_asset_mint / mint_game_asset — one mint. WAS A BUG: only "
        "game_asset_mint emitted `game_asset_minted`. Both now publish (NEW-10).",
    ("rwa_tokenization", "tokenize_asset"):
        "rwa_tokenize / tokenize_asset — one tokenization. WAS A BUG: only "
        "rwa_tokenize emitted `rwa_tokenized`. Both now publish (NEW-10).",
    ("supply_chain", "transfer_custody"):
        "custody_transfer / transfer_custody — one custody transfer. WAS A BUG: "
        "only custody_transfer emitted `custody_transferred`. Both now publish "
        "(NEW-10).",
}


def _service_method_by_handler() -> dict[str, set[tuple[str, str]]]:
    """handler name -> {(service, method)} it dispatches to, via AST."""
    tree = ast.parse(SERVICE_ROUTES.read_text())
    out: dict[str, set[tuple[str, str]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        targets: set[tuple[str, str]] = set()
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            fn = call.func
            if not (isinstance(fn, ast.Attribute) and fn.attr == "_call"):
                continue
            args = [a for a in call.args if isinstance(a, ast.Constant)]
            if len(args) >= 2 and isinstance(args[0].value, str) and isinstance(args[1].value, str):
                targets.add((args[0].value, args[1].value))
        if targets:
            out[node.name] = targets
    return out


def _routes_by_handler() -> dict[str, list[str]]:
    """handler name -> [route paths] from the generated table."""
    if not ROUTES_MD.is_file():
        pytest.skip("docs/ROUTES.md missing — run scripts/generate_route_table.py")
    out: dict[str, list[str]] = {}
    for line in ROUTES_MD.read_text().splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("Method", "---"):
            continue
        method, path, handler = cells[0], cells[1].strip("`"), cells[2].strip("`")
        if path.startswith("/"):
            out.setdefault(handler, []).append(f"{method} {path}")
    return out


def _dict_literal(path: Path, name: str) -> dict:
    """Evaluate a module-level dict literal (e.g. ACTION_MAP) without importing."""
    tree = ast.parse(path.read_text())
    for node in tree.body:
        targets = (
            node.targets if isinstance(node, ast.Assign)
            else [node.target] if isinstance(node, ast.AnnAssign)
            else []
        )
        for t in targets:
            if isinstance(t, ast.Name) and t.id == name and node.value is not None:
                return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path} — the table was renamed or moved")


def test_no_two_routes_share_a_service_method():
    """Two route paths reaching the same service.method is RUN-2's shape."""
    handler_targets = _service_method_by_handler()
    routes_by_handler = _routes_by_handler()

    assert handler_targets, "AST parse produced zero _call sites — parser is broken"

    by_target: dict[tuple[str, str], set[str]] = {}
    for handler, targets in handler_targets.items():
        for route in routes_by_handler.get(handler, []):
            for target in targets:
                by_target.setdefault(target, set()).add(route)

    collisions = {
        target: sorted(routes)
        for target, routes in by_target.items()
        if len(routes) > 1 and target not in ALLOWED_ALIASES
    }
    assert not collisions, (
        "Routes collapsing onto one service.method (each is an alias to document "
        "or a RUN-2):\n"
        + "\n".join(
            f"  {svc}.{meth}  <-  {', '.join(routes)}"
            for (svc, meth), routes in sorted(collisions.items())
        )
    )


def test_no_two_dispatcher_actions_share_a_service_method():
    """Same check for the agent-facing ACTION_MAP."""
    action_map = _dict_literal(DISPATCHER, "ACTION_MAP")
    by_target: dict[tuple[str, str], set[str]] = {}
    for action, target in action_map.items():
        by_target.setdefault(tuple(target), set()).add(action)

    collisions = {
        t: sorted(actions)
        for t, actions in by_target.items()
        if len(actions) > 1 and t not in ALLOWED_ALIASES
    }
    assert not collisions, (
        "Dispatcher actions collapsing onto one service.method:\n"
        + "\n".join(
            f"  {svc}.{meth}  <-  {', '.join(actions)}"
            for (svc, meth), actions in sorted(collisions.items())
        )
    )


def test_capability_catalog_does_not_advertise_a_collapsed_action():
    """A capability must not promise more than the method it calls delivers.

    `deploy_contract` and `convert_contract` both bind to
    contract_conversion.convert, but only one of them describes converting.
    The other advertises a deployment and emits a `contract_deployed` feed
    event — so the fake success escapes the API into the social feed.
    """
    src = CATALOG.read_text()
    tree = ast.parse(src)

    caps: list[tuple[str, str, str, str]] = []  # (id, service, method, feed_event)
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id == "_cap"):
            continue
        pos = [a.value if isinstance(a, ast.Constant) else None for a in call.args]
        if len(pos) < 5:
            continue
        cap_id, service, method = pos[0], pos[3], pos[4]
        feed = ""
        for kw in call.keywords:
            if kw.arg == "feed_event" and isinstance(kw.value, ast.Constant):
                feed = kw.value.value
        if cap_id and service and method:
            caps.append((cap_id, service, method, feed))

    assert caps, "parsed zero capabilities — _cap() signature changed"

    by_target: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for cap_id, service, method, feed in caps:
        by_target.setdefault((service, method), []).append((cap_id, feed))

    collisions = {
        t: v for t, v in by_target.items()
        if len(v) > 1 and t not in ALLOWED_ALIASES
    }
    assert not collisions, (
        "Capabilities collapsing onto one service.method (feed_event in "
        "parentheses — differing events on an identical call are the tell):\n"
        + "\n".join(
            f"  {svc}.{meth}  <-  "
            + ", ".join(f"{cid} ({feed or 'no event'})" for cid, feed in sorted(v))
            for (svc, meth), v in sorted(collisions.items())
        )
    )
