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
ALLOWED_ALIASES: dict[tuple[str, str], str] = {}


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
