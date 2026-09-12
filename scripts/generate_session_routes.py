#!/usr/bin/env python3
"""Generate gateway/session_routes.py — the routes a per-user session may reach.

T2 / path A (Matrix register entry::D005-DECIDED-A): the auth wall accepts the
Apple session the iOS app holds as a credential ONLY on the routes the app
actually calls. Anything else stays behind the operator key. The list is
derived, not hand-written:

    app-called paths  (string literals after `path:` / `endpoint:` in the
                       MTRX client, `\\(x)` interpolations → `{}`)
  ∩ gateway routes   (docs/ROUTES.md, `{name}` params → `{}`)
  − exclusions       (routes that exist and are called but must NOT open to a
                       user session, each with its reason)

Under-inclusion shows up as a 401 on a feature (visible); over-inclusion would
be a silent privilege grant — so the derivation errs toward the former.

Usage:
    python3 scripts/generate_session_routes.py [--client PATH] [--check]

The generated module is committed; CI needs no MTRX checkout. `--check` exits 1
when the committed module differs from what the inputs produce. Run it with the
repo's own interpreter: the capability escape set imports ACTION_MAP, and
tests/test_capability_catalog_truth.py re-derives that set from the live app
without the MTRX checkout, so CI catches a stale one either way.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTES_MD = ROOT / "docs" / "ROUTES.md"
OUT = ROOT / "gateway" / "session_routes.py"
# The whole app tree (minus its tests): MTRXAPIClient.swift carries nearly every
# call, but five component files reach the gateway on their own.
DEFAULT_CLIENT = ROOT.parent / "MTRX"

# Routes the app calls that a user session must NOT unlock, with the reason.
EXCLUDED = {
    "/memory/read": "reads an AGENT's memory, shared across every user (register §D3.6)",
    "/memory/write": "writes an AGENT's memory, shared across every user (register §D3.6)",
}

_LITERAL = re.compile(r'(?:path|endpoint):\s*"([^"]+)"')
_INTERP = re.compile(r"\\\([^)]*\)")
_PARAM = re.compile(r"\{[^}]*\}")
_ROUTE_ROW = re.compile(r"^\|\s*(GET|POST|PUT|DELETE|PATCH)\s*\|\s*`?(/[^\s`|]*)")


def _swift_sources(client: Path):
    if client.is_file():
        return [client]
    return sorted(f for f in client.rglob("*.swift") if "/Tests/" not in f.as_posix())


def app_paths(client: Path) -> set[str]:
    out = set()
    for f in _swift_sources(client):
        text = f.read_text(encoding="utf-8", errors="replace")
        for lit in _LITERAL.findall(text):
            p = _INTERP.sub("{}", lit)
            p = p.split("?", 1)[0]
            out.add(p.rstrip("/") or "/")
    return out


def gateway_routes(routes_md: Path) -> dict[str, str]:
    """canonical route template → normalised (`{name}` → `{}`)."""
    out = {}
    for line in routes_md.read_text(encoding="utf-8").splitlines():
        m = _ROUTE_ROW.match(line)
        if not m:
            continue
        canonical = m.group(2).rstrip("/") or "/"
        out[canonical] = _PARAM.sub("{}", canonical)
    return out


def capability_escapes(routes_py: Path, allowed: set) -> dict:
    """Capabilities a session could invoke to reach a route it is refused.

    ``POST /api/v1/capabilities/{id}/invoke`` is on the allowlist because the app
    calls it — but it is a DISPATCHER: it resolves a catalog id to its ACTION_MAP
    (service, method) pair and calls the same ServiceDispatcher the dedicated
    /api/v1 routes call. So "exactly the routes the app calls" is true of URLs
    and false of operations: a session gets 403 on the dedicated route and 200
    on the capability that performs the identical call. This returns
    {capability_id: dedicated_route} for every capability whose dispatch reaches
    a dedicated route that is NOT session-reachable — the set the invoke handler
    must refuse.

    The pair is read from ACTION_MAP, the table dispatch actually uses — NOT from
    the catalog row's own `service`/`method` fields. This used to regex those two
    fields out of catalog.py, and 81 rows named a method that did not exist: they
    matched no route, so 14 capabilities that reach an operator-only route were
    left invokable by a session (a 15th, provenance_log, was hidden by the regex
    below — see the AST note). An allow/deny must not rest on what the judged
    artifact says about itself (§EE). When one pair backs several routes and any
    of them is refused, the capability is refused (errs toward the visible 403,
    as the module docstring says).
    """
    import re as _re
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    from runtime.capabilities import catalog

    import ast as _ast

    routes = routes_py.read_text(encoding="utf-8")
    route_of_handler = {m.group(3): m.group(2) for m in _re.finditer(
        r'app\.router\.add_(get|post|put|delete|patch)\("([^"]+)",\s*self\.(_handle_[a-z0-9_]+)\)', routes)}
    # The handler -> (service, method) link is read from the AST, not a regex: a
    # comment between `self._call(` and its first literal (NEW-89 left one in
    # _handle_provenance_log) made the regex miss the call, and the capability
    # behind it with it.
    pair_of_handler = {}
    for fn in _ast.walk(_ast.parse(routes)):
        if not (isinstance(fn, (_ast.AsyncFunctionDef, _ast.FunctionDef))
                and fn.name.startswith("_handle_")):
            continue
        for node in _ast.walk(fn):
            if (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)
                    and node.func.attr == "_call" and isinstance(node.func.value, _ast.Name)
                    and node.func.value.id == "self" and len(node.args) >= 2
                    and all(isinstance(a, _ast.Constant) and isinstance(a.value, str)
                            for a in node.args[:2])):
                pair_of_handler[fn.name] = (node.args[0].value, node.args[1].value)
                break
    routes_of_pair: dict[tuple[str, str], set[str]] = {}
    for handler, route in route_of_handler.items():
        if handler in pair_of_handler:
            routes_of_pair.setdefault(pair_of_handler[handler], set()).add(route)
    out = {}
    for cap in catalog.CAPABILITIES:
        refused = sorted(r for r in routes_of_pair.get(ACTION_MAP.get(cap["action"]), ())
                         if (r.rstrip("/") or "/") not in allowed)
        if refused:
            out[cap["id"]] = refused[0]
    return out


def derive(client: Path, routes_md: Path):
    called = app_paths(client)
    routes = gateway_routes(routes_md)
    allowed, excluded = [], []
    for canonical, normalised in sorted(routes.items()):
        if normalised not in called:
            continue
        if canonical in EXCLUDED:
            excluded.append(canonical)
            continue
        allowed.append(canonical)
    return allowed, excluded, len(called), len(routes)


def render(allowed, excluded, escapes=None) -> str:
    lines = [
        '"""GENERATED by scripts/generate_session_routes.py — do not edit by hand.',
        "",
        "Routes a per-user wallet session (the Apple session the iOS app holds) may",
        "reach through the auth wall. Everything else that is not public stays behind",
        "the operator key. Derived as: app-called paths ∩ gateway routes − exclusions.",
        '"""',
        "from __future__ import annotations",
        "",
        "USER_SESSION_ROUTES: frozenset[str] = frozenset({",
    ]
    lines += [f'    "{p}",' for p in allowed]
    lines += ["})", "", "# Called by the app, present on the server, deliberately NOT session-reachable:"]
    lines += [f"#   {p} — {EXCLUDED[p]}" for p in excluded]
    lines += [
        "EXCLUDED_FROM_SESSION: frozenset[str] = frozenset({",
    ]
    lines += [f'    "{p}",' for p in excluded]
    lines += [
        "})",
        "",
        "# A session may invoke a catalog capability EXCEPT one that would reach a",
        "# service method whose own route is refused to it. The invoke route is a",
        "# dispatcher, so allowlisting the URL is not allowlisting the operation.",
        "CAPABILITIES_OFF_ALLOWLIST: dict[str, str] = {",
    ]
    lines += [f'    "{c}": "{r}",' for c, r in sorted((escapes or {}).items())]
    lines += [
        "}",
        "",
        "",
        "def session_may_invoke(capability_id: str) -> bool:",
        '    """False when this capability would reach a route the session is refused."""',
        "    return capability_id not in CAPABILITIES_OFF_ALLOWLIST",
        "",
        "",
        "def session_may_reach(canonical_route: str) -> bool:",
        '    """True when a per-user session is a sufficient credential for this route.',
        "",
        "    ``canonical_route`` is aiohttp's matched template",
        "    (``request.match_info.route.resource.canonical``), e.g.",
        '    ``/api/v1/portfolio/complete/{wallet}`` — exact membership, no prefix logic.',
        '    """',
        '    return (canonical_route.rstrip("/") or "/") in USER_SESSION_ROUTES',
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", type=Path, default=DEFAULT_CLIENT)
    ap.add_argument("--routes", type=Path, default=ROUTES_MD)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if not a.client.exists():
        print(f"client not found: {a.client}", file=sys.stderr)
        return 2
    allowed, excluded, n_called, n_routes = derive(a.client, a.routes)
    escapes = capability_escapes(ROOT / "gateway" / "service_routes.py", set(allowed))
    text = render(allowed, excluded, escapes)
    if a.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("gateway/session_routes.py is stale — regenerate", file=sys.stderr)
            return 1
        print(f"up to date: {len(allowed)} session routes, {len(excluded)} excluded")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(allowed)} session routes "
          f"(app paths {n_called} ∩ gateway routes {n_routes}) · excluded {len(excluded)} · "
          f"capabilities refused to a session {len(escapes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
