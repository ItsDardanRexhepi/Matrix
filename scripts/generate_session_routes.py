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


def _call_pairs(fn_source: str, where: str) -> set:
    """Every (service, method) a handler's body passes to ``self._call``.

    Read from the AST, not a regex: a comment between ``self._call(`` and its
    first literal (NEW-89 left one in _handle_provenance_log) made the regex miss
    the call, and the capability behind it with it. EVERY literal call is kept,
    not only the first. A ``self._call`` whose service or method is not a string
    literal cannot be attributed to a pair, so it stops the generator rather than
    silently leaving an operation off the refusal set.
    """
    import ast as _ast
    import textwrap as _textwrap

    out = set()
    for node in _ast.walk(_ast.parse(_textwrap.dedent(fn_source))):
        if not (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)
                and node.func.attr == "_call" and isinstance(node.func.value, _ast.Name)
                and node.func.value.id == "self"):
            continue
        head = node.args[:2]
        if len(head) < 2 or not all(isinstance(a, _ast.Constant) and isinstance(a.value, str)
                                    for a in head):
            raise SystemExit(
                f"{where}: self._call with a non-literal service/method; the session "
                "refusal set cannot attribute it to an operation — make both literals")
        out.add((head[0].value, head[1].value))
    return out


_LIVE: dict = {}


def _live_server():
    """``(server, app)`` — the REAL gateway, built once per run."""
    if "app" not in _LIVE:
        import tempfile as _tempfile

        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from gateway.server import GatewayServer

        scratch = _tempfile.mkdtemp(prefix="opnmatrx-session-routes-")
        server = GatewayServer({"memory_dir": scratch,
                                "database": {"path": f"{scratch}/g.db"}})
        _LIVE["server"], _LIVE["app"] = server, server.create_app()
    return _LIVE["server"], _LIVE["app"]


def live_route_pairs() -> dict:
    """canonical route -> {(service, method)} from the REAL app's router.

    Routes are read from the router the gateway builds, not regexed out of
    service_routes.py: the regex only knew ``app.router.add_x("/path",
    self._handle_x)``, and the P2 routes registered from a
    ``(method, path, handler)`` table were invisible to it — including two whose
    operation a session is refused.
    """
    import inspect as _inspect

    _server, app = _live_server()
    out: dict = {}
    for route in app.router.routes():
        resource = route.resource
        if resource is None:
            continue
        fn = getattr(route.handler, "__func__", route.handler)
        try:
            source = _inspect.getsource(fn)
        except (OSError, TypeError):
            continue  # a closure or builtin handler has no self._call to find
        pairs = _call_pairs(source, f"{getattr(fn, '__qualname__', fn)} ({resource.canonical})")
        if pairs:
            out.setdefault(resource.canonical, set()).update(pairs)
    # A route also runs what its method WRAPS. /api/v1/social/feed/{wallet}
    # calls social.get_feed_view, which hands every argument to social.get_feed;
    # the literal pair alone left get_social_feed readable by an anonymous chat
    # while the route answered it 401.
    for pairs in out.values():
        frontier = list(pairs)
        while frontier:
            service, method = frontier.pop()
            for wrapped in wrapped_methods(service, method):
                if (service, wrapped) not in pairs:
                    pairs.add((service, wrapped))
                    frontier.append((service, wrapped))
    return out


def wrapped_methods(service: str, method: str) -> set:
    """Public methods of *service* that *method* passes EVERY one of its own
    parameters to — a wrapper runs that operation. A helper (the fee a transfer
    computes) receives only some of the caller's arguments and is not the
    route's operation, so it is not included. With no parameters, "every one"
    is vacuous, and only a sole public self-call counts."""
    import ast as _ast
    import importlib as _importlib
    import inspect as _inspect
    import textwrap as _textwrap

    from runtime.blockchain.services import registry as _registry

    if service not in _registry._SERVICE_MAP:
        return set()
    module_path, class_name = _registry._SERVICE_MAP[service]
    cls = getattr(_importlib.import_module(module_path, package=_registry._PACKAGE), class_name)
    fn = getattr(cls, method, None)
    try:
        fdef = _ast.parse(_textwrap.dedent(_inspect.getsource(fn))).body[0]
    except (OSError, TypeError, IndexError):
        return set()
    params = {a.arg for a in (fdef.args.posonlyargs + fdef.args.args + fdef.args.kwonlyargs)
              if a.arg != "self"}
    calls = [n for n in _ast.walk(fdef)
             if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
             and isinstance(n.func.value, _ast.Name) and n.func.value.id == "self"
             and not n.func.attr.startswith("_") and callable(getattr(cls, n.func.attr, None))]
    out = set()
    for call in calls:
        passed = {x.id for arg in [*call.args, *(k.value for k in call.keywords)]
                  for x in _ast.walk(arg) if isinstance(x, _ast.Name)}
        if params <= passed and (params or len(calls) == 1):
            out.add(call.func.attr)
    return out


def refused_pairs(allowed: set) -> dict:
    """``"service.method"`` -> an operator-only route whose handler runs it.

    Every session-reachable DISPATCHER — ``/api/v1/capabilities/{id}/invoke``
    (catalog id), ``/bridge/v1/action`` (ACTION_MAP action name) and the chat
    agent's ``request_execution`` / ``platform_action`` tools (action name, plus a
    ``service`` override) — ends in the same ServiceDispatcher, which resolves
    what it is given to a (service, method) pair. So "exactly the routes the app
    calls" is true of URLs and false of operations unless the refusal is keyed
    on that PAIR: a session that gets 403 on a dedicated route must get 403 on
    every dispatcher that resolves to the same ``self._call``. bb6635b keyed it on
    the catalog id and enforced it on the invoke route only; /bridge/v1/action
    still answered 200 for all of them.

    When one pair backs several routes and ANY of them is refused, the pair is
    refused (errs toward the visible 403, as the module docstring says).
    """
    out: dict = {}
    for route, pairs in sorted(live_route_pairs().items()):
        if (route.rstrip("/") or "/") in allowed:
            continue
        for service, method in sorted(pairs):
            out.setdefault(f"{service}.{method}", route)
    return out


def anonymous_refused_pairs() -> dict:
    """``"service.method"`` -> a route whose handler runs it and that the auth
    wall does not let a caller with NO credential reach.

    The chat surfaces are public paths: an anonymous caller reaches Trinity, and
    through her dispatching tools the same ServiceDispatcher. The session set
    above models only the operator tier, so an anonymous chat ran operations
    whose own route answers it 401. Public is read from the real server's
    ``_public_paths`` — the set the wall itself consults. Same tie-break: a pair
    behind ANY non-public route is refused.
    """
    server, _app = _live_server()
    public = set(server._public_paths)
    out: dict = {}
    for route, pairs in sorted(live_route_pairs().items()):
        if route in public:
            continue
        for service, method in sorted(pairs):
            out.setdefault(f"{service}.{method}", route)
    return out


def capability_escapes(pairs: dict) -> dict:
    """{capability_id: route} for every catalog capability whose ACTION_MAP pair
    is refused. Kept for the invoke route's message and for tooling; the
    decision itself is the pair's (session_refused_route).

    The pair is read from ACTION_MAP, the table dispatch actually uses — NOT from
    the catalog row's own `service`/`method` fields. This used to regex those two
    fields out of catalog.py, and 81 rows named a method that did not exist, so
    capabilities that reach an operator-only route were left invokable by a
    session. An allow/deny must not rest on what the judged artifact says about
    itself (§EE).
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    from runtime.capabilities import catalog

    out = {}
    for cap in catalog.CAPABILITIES:
        pair = ACTION_MAP.get(cap["action"])
        if pair is not None and f"{pair[0]}.{pair[1]}" in pairs:
            out[cap["id"]] = pairs[f"{pair[0]}.{pair[1]}"]
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


def render(allowed, excluded, escapes=None, pairs=None, anonymous=None) -> str:
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
        "# The same refusal keyed on what a dispatch RUNS: every (service, method) whose",
        "# dedicated route is refused to a session, whichever dispatcher reaches it —",
        "# the invoke route (catalog id), /bridge/v1/action (action name) or the chat",
        "# agent's request_execution / platform_action tools (action name + service).",
        "SERVICE_METHODS_OFF_ALLOWLIST: dict[str, str] = {",
    ]
    lines += [f'    "{p}": "{r}",' for p, r in sorted((pairs or {}).items())]
    lines += [
        "}",
        "",
        "# One credential down: every (service, method) whose route a caller with NO",
        "# credential cannot reach (not a public path). The chat surfaces are public,",
        "# so without this an anonymous chat ran operations its own routes answer 401.",
        "SERVICE_METHODS_OFF_ANONYMOUS: dict[str, str] = {",
    ]
    lines += [f'    "{p}": "{r}",' for p, r in sorted((anonymous or {}).items())]
    lines += [
        "}",
        "",
        "# What an anonymous refusal names when no route backs the operation at all:",
        "# no public route changes state, and there is no identity to attribute it to.",
        'UNROUTED_STATE_CHANGE = "no public route; it changes state"',
        "",
        "",
        "def session_may_invoke(capability_id: str) -> bool:",
        '    """False when this capability would reach a route the session is refused."""',
        "    return capability_id not in CAPABILITIES_OFF_ALLOWLIST",
        "",
        "",
        "def session_refused_route(action, service=None):",
        '    """The operator-only route behind what dispatching *action* would RUN, or None.',
        "",
        "    Resolved the way ServiceDispatcher.execute resolves it — ACTION_MAP at call",
        "    time, then a truthy ``service`` override replaces the service — so the",
        "    answer follows the operation, not the label a caller or catalog row gives",
        "    it. An unknown or non-string action resolves to nothing (the dispatcher",
        '    refuses those itself)."""',
        "    if not isinstance(action, str):",
        "        return None",
        "    from runtime.blockchain.services.service_dispatcher import ACTION_MAP",
        "    pair = ACTION_MAP.get(action)",
        "    if pair is None:",
        "        return None",
        "    target = service if service else pair[0]",
        '    return SERVICE_METHODS_OFF_ALLOWLIST.get(f"{target}.{pair[1]}")',
        "",
        "",
        "def caller_refused_route(caller_kind, action, service=None):",
        '    """What refuses *caller_kind* the operation dispatching *action* RUNS, or None.',
        "",
        '    ``caller_kind`` is the credential the gateway computed ("operator",',
        '    "session", "anonymous"; "" for a dispatch with no HTTP caller). The',
        "    operator and a caller-less dispatch are not refused here. A session is",
        "    refused what its routes refuse it. Anything else — anonymous, or a kind",
        "    this module does not recognise — is refused every operation behind a",
        "    non-public route, and every state change whether or not a route backs it.",
        '    Resolved on the pair, the way ServiceDispatcher.execute resolves it."""',
        '    if caller_kind in ("operator", ""):',
        "        return None",
        '    if caller_kind == "session":',
        "        return session_refused_route(action, service)",
        "    if not isinstance(action, str):",
        "        return None",
        "    from runtime.blockchain.services.service_dispatcher import (",
        "        ACTION_MAP, _STATE_MODIFYING_ACTIONS,",
        "    )",
        "    pair = ACTION_MAP.get(action)",
        "    if pair is None:",
        "        return None",
        "    target = service if service else pair[0]",
        '    key = f"{target}.{pair[1]}"',
        "    routed = SERVICE_METHODS_OFF_ALLOWLIST.get(key) or SERVICE_METHODS_OFF_ANONYMOUS.get(key)",
        "    if routed:",
        "        return routed",
        "    if action in _STATE_MODIFYING_ACTIONS or any(",
        "            ACTION_MAP.get(a) == (target, pair[1]) for a in _STATE_MODIFYING_ACTIONS):",
        "        return UNROUTED_STATE_CHANGE",
        "    return None",
        "",
        "",
        "def caller_refusal_message(caller_kind, refused):",
        '    """The client-facing text for a ``caller_refused_route`` refusal."""',
        '    if caller_kind == "session":',
        '        return ("This action is not available to a user session; "',
        '                f"its route ({refused}) requires the operator key.")',
        '    return ("This action is not available without signing in "',
        '            f"({refused}); sign in and try again.")',
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
    pairs = refused_pairs(set(allowed))
    escapes = capability_escapes(pairs)
    anonymous = anonymous_refused_pairs()
    text = render(allowed, excluded, escapes, pairs, anonymous)
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
          f"operations refused to a session {len(pairs)} (catalog capabilities {len(escapes)}) · "
          f"to an anonymous caller {len(anonymous)} + every unrouted state change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
