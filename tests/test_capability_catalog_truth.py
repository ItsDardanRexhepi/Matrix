"""The capability catalog must describe what the dispatcher actually runs.

`runtime/capabilities/catalog.py` is served verbatim at GET /api/v1/capabilities
and /api/v1/capabilities/{id}: every row publishes a `service`, a `method` and a
`feed_event`. Nothing dispatches from those fields — ServiceDispatcher dispatches
from ACTION_MAP, and `install_action_map` refuses to overwrite an ACTION_MAP entry
that already exists — so a wrong row was invisible to every behavioural test.

Measured at 9f4aa37: 81 of 195 rows named a method that does not exist on the
named service (and 6 of those named the wrong service outright), and 32 rows
published `feed_event: null` for an action whose dispatch emits a feed event.
The resulting conflicts were logged at DEBUG, truncated to five names — the same
silence that let `community_create` resolve to nothing until NEW-14.

§EE: the catalog's own fields are the claim under test, so nothing here trusts
them. The service class is resolved through the registry's own map and the
method looked up on it; the dispatch target, feed event and state flag are read
from the dispatcher's live tables.
"""
from __future__ import annotations

import functools
import importlib

import pytest

from runtime.blockchain.services import registry as service_registry
from runtime.blockchain.services import service_dispatcher as sd
from runtime.capabilities import catalog


def _service_class(service: str):
    module_path, class_name = service_registry._SERVICE_MAP[service]
    module = importlib.import_module(module_path, package=service_registry._PACKAGE)
    return getattr(module, class_name)


def test_every_row_names_a_method_that_exists_on_its_service():
    wrong = []
    for cap in catalog.CAPABILITIES:
        if cap["service"] not in service_registry._SERVICE_MAP:
            wrong.append(f"{cap['id']}: no service {cap['service']!r}")
            continue
        if not callable(getattr(_service_class(cap["service"]), cap["method"], None)):
            wrong.append(f"{cap['id']}: {cap['service']}.{cap['method']} does not exist")
    assert not wrong, f"{len(wrong)} catalog rows publish a method nobody can call:\n  " + "\n  ".join(wrong)


def test_every_row_names_the_target_the_dispatcher_actually_runs():
    drift = [
        f"{cap['id']}: catalog says {(cap['service'], cap['method'])}, "
        f"dispatch runs {sd.ACTION_MAP.get(cap['action'])}"
        for cap in catalog.CAPABILITIES
        if sd.ACTION_MAP.get(cap["action"]) != (cap["service"], cap["method"])
    ]
    assert not drift, f"{len(drift)} rows describe a dispatch that does not happen:\n  " + "\n  ".join(drift)


def test_install_reports_no_conflicts_against_the_live_map():
    """The mechanism the drift hid behind: a conflict is kept silently."""
    skipped = catalog.install_action_map(dict(sd.ACTION_MAP))
    assert skipped == {}, skipped


def test_every_row_publishes_the_feed_event_dispatch_emits():
    drift = [
        f"{cap['id']}: catalog says {cap['feed_event']!r}, "
        f"dispatch emits {sd.ACTION_TO_FEED_EVENT.get(cap['action'])!r}"
        for cap in catalog.CAPABILITIES
        if (cap["feed_event"] or None) != sd.ACTION_TO_FEED_EVENT.get(cap["action"])
    ]
    assert not drift, f"{len(drift)} rows publish the wrong feed event:\n  " + "\n  ".join(drift)


def test_every_row_publishes_the_state_flag_dispatch_uses():
    drift = [
        cap["id"] for cap in catalog.CAPABILITIES
        if cap["state_modifying"] != (cap["action"] in sd._STATE_MODIFYING_ACTIONS)
    ]
    assert not drift, drift


def test_a_conflict_is_reported_in_full_not_truncated(caplog):
    """The install path logged `list(_skipped.keys())[:5]` at DEBUG. A drift
    report nobody sees at the default level, cut to five names, is how 81 rows
    went stale. It is a WARNING naming every entry now."""
    import logging

    conflicting = {cap["action"]: ("nowhere", "nothing") for cap in catalog.CAPABILITIES[:7]}
    with caplog.at_level(logging.DEBUG, logger=sd.logger.name):
        # install_action_map fills the map it is given; hand it a copy so
        # `conflicting` still names only the seven planted conflicts.
        sd._report_catalog_conflicts(catalog.install_action_map(dict(conflicting)))
    records = [r for r in caplog.records if "catalog" in r.getMessage().lower()]
    assert records, "a conflict produced no report at all"
    record = records[-1]
    assert record.levelno >= logging.WARNING, (
        f"conflict report logged at {record.levelname}, invisible at the default level")
    missing = [a for a in conflicting if a not in record.getMessage()]
    assert not missing, f"conflict report truncated; missing {missing}"


# ── the consequence: the session escape set was derived from the stale rows ───
#
# scripts/generate_session_routes.py computes CAPABILITIES_OFF_ALLOWLIST — the
# capabilities a user SESSION may not invoke because their operation's dedicated
# route requires the operator key — by matching each catalog row's
# (service, method) against the `self._call(service, method)` in each route
# handler. It read those two fields from catalog.py's source text. A row naming a
# method that does not exist matched no route, so its capability was never put in
# the escape set, and a session could invoke through
# /api/v1/capabilities/{id}/invoke an operation whose own route answers it 403.
# "Harmless because ACTION_MAP wins" was wrong: ACTION_MAP won the dispatch, the
# stale row won the authorization. Measured at 9f4aa37: 15 such capabilities
# answered HTTP 200 to a session — 14 through stale rows, and provenance_log
# because a comment inside its handler's `self._call(` hid the call from the
# generator's regex. Both derivations here and in the generator use the AST.


_ROUTE_META: dict = {}


@functools.lru_cache(maxsize=1)
def _route_pairs():
    """(service, method) -> {canonical route} from the REAL app: its registered
    routes, the `self._call(service, method, ...)` in each handler's own source —
    found on the AST, so a comment inside the call cannot hide it — and, in both
    directions, what wraps what:
      * Round 4: what the route's method WRAPS. /api/v1/social/feed/{wallet}
        calls social.get_feed_view, which hands every argument to social.get_feed.
      * Round 5: what WRAPS a method the route runs. /api/v1/oracle/price/{pair}
        calls oracle_gateway.request(oracle_type="price_feed", ...); query_price
        hands its every argument to request_safe, which hands them to request
        with that same literal. Literals are composed down the chain and compared
        with the route's, so request_vrf ("random_vrf") is not the price route.
      * Round 6: what performs a method the route runs ACROSS the service
        boundary. cross_border.get_quote asks its conversion component for a
        rate, and that component builds an OracleGateway and calls
        request("price_feed", {"pair": ...}) on it. No self.x() joins two
        services, so neither wrapper rule could see it.
    Rounds 5 and 6 repeat until nothing joins; a wrapper joins carrying the
    route's literals lifted onto its own parameters, so query_weather is still
    not the price route.
    """
    import ast
    import collections
    import inspect
    import tempfile
    import textwrap

    from gateway.server import GatewayServer

    scratch = tempfile.mkdtemp(prefix="the-matrix-catalog-truth-")
    app = GatewayServer({"memory_dir": scratch,
                         "database": {"path": f"{scratch}/t.db"}}).create_app()
    literal: dict = {}  # (route, service, method) -> {kw: binding} the handler fixes
    _ROUTE_META["methods"] = methods = collections.defaultdict(set)
    _ROUTE_META["literal"] = literal
    for route in app.router.routes():
        methods[route.resource.canonical].add(route.method)
        try:
            src = inspect.getsource(getattr(route.handler, "__func__", route.handler))
        except (OSError, TypeError):
            continue
        for node in ast.walk(ast.parse(textwrap.dedent(src))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_call" and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"):
                continue
            head = node.args[:2]
            # Every call, not the first; and a call this derivation cannot
            # attribute is a failure, not a skip (review of bb6635b).
            assert len(head) == 2 and all(
                isinstance(a, ast.Constant) and isinstance(a.value, str) for a in head), (
                f"{route.resource.canonical}: self._call with a non-literal service/method")
            fixed = {k.arg: (("const", k.value.value) if isinstance(k.value, ast.Constant)
                             else ("other",))
                     for k in node.keywords if k.arg is not None}
            key = (route.resource.canonical, head[0].value, head[1].value)
            if key in literal:  # the same pair twice: a literal that differs is no literal
                prev = literal[key]
                fixed = {k: (prev[k] if k in prev and k in fixed and prev[k] == fixed[k]
                             else ("other",)) for k in set(prev) | set(fixed)}
            literal[key] = fixed
    pairs = collections.defaultdict(set)
    frontier = []  # what each route RUNS: the literal pair and what it wraps
    for (route, service, method), fixed in literal.items():
        pairs[(service, method)].add(route)
        frontier.append((route, service, method, fixed))
        for wrapped, chain in _wrapper_closure(service, method).items():
            pairs[(service, wrapped)].add(route)
            frontier.append((route, service, wrapped, _through(fixed, chain)))
    while frontier:
        joined = []
        for route, service, method, fixed in frontier:
            for other, name, chain in _cross_runners().get((service, method), []):
                if route not in pairs.get((other, name), ()) and _consistent(chain, fixed):
                    pairs[(other, name)].add(route)
                    joined.append((route, other, name, {}))
            for name in _public_methods(service):
                chain = _wrapper_closure(service, name).get(method)
                if (route not in pairs.get((service, name), ()) and chain is not None
                        and _consistent(chain, fixed)):
                    pairs[(service, name)].add(route)
                    joined.append((route, service, name, _lift(chain, fixed)))
        frontier = joined
    return pairs


def _function_def(cls, name: str):
    import ast
    import inspect
    import textwrap

    fn = getattr(cls, name, None)
    if not callable(fn):
        return None
    try:
        return ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    except (OSError, TypeError, IndexError):
        return None


def _public_methods(service: str) -> list[str]:
    import inspect

    if service not in service_registry._SERVICE_MAP:
        return []
    return sorted(n for n, _ in inspect.getmembers(_service_class(service),
                                                   predicate=inspect.isfunction)
                  if not n.startswith("_"))


def _signature(fdef):
    a = fdef.args
    positional = [x.arg for x in a.posonlyargs + a.args if x.arg != "self"]
    kwonly = [x.arg for x in a.kwonlyargs]
    required = set(positional[:len(positional) - len(a.defaults)])
    required |= {k.arg for k, d in zip(a.kwonlyargs, a.kw_defaults) if d is None}
    var = [v.arg for v in (a.vararg, a.kwarg) if v is not None]
    return positional, kwonly, required, var


def _bindings(callee_fdef, call, own: set) -> dict:
    """callee parameter -> ("const", v) | ("param", the caller's own) | ("other",)."""
    import ast

    positional, kwonly, _required, _var = _signature(callee_fdef)

    def binding(node):
        if isinstance(node, ast.Constant):
            return ("const", node.value)
        if isinstance(node, ast.Name) and node.id in own:
            return ("param", node.id)
        return ("other",)

    out = {}
    for i, arg in enumerate(call.args):
        if not isinstance(arg, ast.Starred) and i < len(positional):
            out[positional[i]] = binding(arg)
    for kw in call.keywords:
        if kw.arg is not None and (kw.arg in positional or kw.arg in kwonly):
            out[kw.arg] = binding(kw.value)
    return out


@functools.lru_cache(maxsize=None)
def _wrapped_methods(service: str, method: str) -> dict:
    """Public methods of the same service that *method* WRAPS, each mapped to how
    the call binds the callee's parameters. A wrapper passes EVERY one of its own
    required parameters (and any *args / **kwargs) on, and at least one of its
    parameters at all; with none to pass, only a sole public self-call counts.
    (A helper, such as the quote a transfer computes, receives only some of the
    caller's arguments, and is not the route's operation. A defaulted parameter
    the wrapper keeps for itself — request_safe's stale_max_age — does not stop
    it being one.)"""
    import ast

    if service not in service_registry._SERVICE_MAP:
        return {}
    cls = _service_class(service)
    fdef = _function_def(cls, method)
    if fdef is None:
        return {}
    positional, kwonly, required, var = _signature(fdef)
    own = set(positional) | set(kwonly) | set(var)
    must = required | set(var)
    calls = [n for n in ast.walk(fdef)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"
             and not n.func.attr.startswith("_") and callable(getattr(cls, n.func.attr, None))]
    out = {}
    for call in calls:
        passed = {x.id for arg in [*call.args, *(k.value for k in call.keywords)]
                  for x in ast.walk(arg) if isinstance(x, ast.Name)}
        callee = _function_def(cls, call.func.attr)
        if callee is not None and must <= passed and ((own & passed) or len(calls) == 1):
            out[call.func.attr] = _bindings(callee, call, own)
    return out


def _through(outer: dict, inner: dict) -> dict:
    """Compose bindings down a chain; a caller parameter left unbound is its default."""
    return {p: (outer.get(b[1], ("default",)) if b[0] == "param" else b)
            for p, b in inner.items()}


def _wrapper_closure(service: str, method: str) -> dict:
    """Every public method *method* reaches through wrappers, transitively, mapped
    to how its parameters are bound in terms of *method*'s own and its literals."""
    reached: dict = {}
    frontier = [(method, None)]
    while frontier:
        current, bindings = frontier.pop()
        for callee, cb in _wrapped_methods(service, current).items():
            if callee in reached or callee == method:
                continue
            composed = cb if bindings is None else _through(bindings, cb)
            reached[callee] = composed
            frontier.append((callee, composed))
    return reached


def _consistent(chain: dict, fixed: dict) -> bool:
    """False only when both pin the SAME parameter to DIFFERENT literals — or the
    chain pins it to one of several (("any", {...})) and the route's is none."""
    for p, b in fixed.items():
        c = chain.get(p, ("other",))
        if b[0] == "const" and ((c[0] == "const" and c[1] != b[1])
                                or (c[0] == "any" and b[1] not in c[1])):
            return False
    return True


def _lift(chain: dict, fixed: dict) -> dict:
    """The route's literals as pins on a wrapper's OWN parameters: a routed
    parameter the route pins and the wrapper passes through by name."""
    return {chain[p][1]: b for p, b in fixed.items()
            if b[0] == "const" and chain.get(p, ("other",))[0] == "param"}


_REGISTRY: dict = {}


def _live_owner(service: str):
    if "registry" not in _REGISTRY:
        _REGISTRY["registry"] = service_registry.ServiceRegistry({})
    return _REGISTRY["registry"].get(service)


def _reached(owner, fn, seen, depth=0) -> list:
    """(tree, module) of every function *fn* reaches on *owner* through
    self.x(...) and self.part.x(...) calls — the write census's walk, through
    the real component objects."""
    import ast
    import inspect
    import textwrap

    code = getattr(fn, "__code__", None)
    if code is None or "site-packages" in code.co_filename or depth > 8:
        return []
    key = (id(owner), code.co_filename, code.co_firstlineno)
    if key in seen:
        return []
    seen.add(key)
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError):
        return []
    out = [(tree, inspect.getmodule(fn))]
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        receiver = node.func.value
        if isinstance(receiver, ast.Name) and receiver.id == "self":
            out += _reached(owner, getattr(type(owner), node.func.attr, None), seen, depth + 1)
        elif (isinstance(receiver, ast.Attribute) and isinstance(receiver.value, ast.Name)
              and receiver.value.id == "self"):
            part = getattr(owner, receiver.attr, None)
            if part is not None:
                out += _reached(part, getattr(type(part), node.func.attr, None), seen, depth + 1)
    return out


@functools.lru_cache(maxsize=None)
def _cross_service_runs(service: str, method: str) -> dict:
    """(other service, public method) -> literal bindings: every operation of
    ANOTHER registry service that *method* performs on an instance it builds.
    Over everything the walk reaches: a Cls(...) call naming the class the
    registry maps to another service, bound to it in the module or imported in
    the body, BUILDS it; an x.m(...) call, x not self, with m public on a built
    service, PERFORMS (that service, m). Literals only — a parameter pinned to
    different literals on two calls keeps the set, anything else is the
    caller's — so only a different literal can exclude."""
    import ast

    by_class: dict = {}
    for name, (_module, cls) in service_registry._SERVICE_MAP.items():
        by_class.setdefault(cls, name)
    owner = _live_owner(service)
    built, calls = set(), []
    for tree, module in _reached(owner, getattr(type(owner), method, None), set()):
        imported = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                    and (n.module or "").startswith("runtime.blockchain.services")
                    for a in n.names}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id in by_class:
                other = by_class[node.func.id]
                if other != service and (node.func.id in imported or getattr(
                        module, node.func.id, None) is _service_class(other)):
                    built.add(other)
            elif isinstance(node.func, ast.Attribute) and not (
                    isinstance(node.func.value, ast.Name) and node.func.value.id == "self"):
                calls.append(node)

    def lit(node):
        return ("const", node.value) if isinstance(node, ast.Constant) else ("other",)

    out: dict = {}
    for other in sorted(built):
        cls = _service_class(other)
        public = set(_public_methods(other))
        for call in calls:
            fdef = _function_def(cls, call.func.attr) if call.func.attr in public else None
            if fdef is None:
                continue
            positional, kwonly, _required, _var = _signature(fdef)
            b = {positional[i]: lit(a) for i, a in enumerate(call.args)
                 if not isinstance(a, ast.Starred) and i < len(positional)}
            b.update({k.arg: lit(k.value) for k in call.keywords
                      if k.arg is not None and (k.arg in positional or k.arg in kwonly)})
            prev = out.get((other, call.func.attr))
            out[(other, call.func.attr)] = b if prev is None else {
                p: _either(prev.get(p, ("other",)), b.get(p, ("other",)))
                for p in set(prev) | set(b)}
    return out


def _either(a: tuple, b: tuple) -> tuple:
    if a[0] == "other" or b[0] == "other":
        return ("other",)
    lits = (set(a[1]) if a[0] == "any" else {a[1]}) | (set(b[1]) if b[0] == "any" else {b[1]})
    return ("const", next(iter(lits))) if len(lits) == 1 else ("any", frozenset(lits))


@functools.lru_cache(maxsize=None)
def _cross_runners() -> dict:
    """(service, method) -> [(other, name, bindings)]: every public method of
    every registry service that performs it across the service boundary."""
    index: dict = {}
    for other in sorted(service_registry._SERVICE_MAP):
        for name in _public_methods(other):
            for target, bindings in _cross_service_runs(other, name).items():
                index.setdefault(target, []).append((other, name, bindings))
    return index


def _stores_read(service: str, method: str) -> set[str]:
    """The private attributes of self a method's body touches (its stores)."""
    import ast

    fdef = _function_def(_service_class(service), method)
    return {n.attr for n in ast.walk(fdef)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id == "self" and n.attr.startswith("_")}


@functools.lru_cache(maxsize=None)
def _private_touch(service: str, method: str) -> frozenset:
    """Every private name of ``self`` the method reaches — a store (`_provenance`)
    or a helper (`_verify_chain_integrity`) — following the private helpers it
    calls, so a read that reaches the store through `self._load()` counts too."""
    import ast

    cls = _service_class(service)
    out: set = set()
    frontier, seen = [method], set()
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        fdef = _function_def(cls, current)
        if fdef is None:
            continue
        for n in ast.walk(fdef):
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id == "self" and n.attr.startswith("_")):
                out.add(n.attr)
                if callable(getattr(cls, n.attr, None)):
                    frontier.append(n.attr)
    return frozenset(out)


def _actions_of(pair) -> list[str]:
    return sorted(a for a, p in sd.ACTION_MAP.items() if p == pair)


def _is_read_anchor(pair) -> bool:
    """True when an anonymous caller is refused this pair *as a read*: no
    state-changing action maps to it, and either a dispatcher can be asked to
    run it (an ACTION_MAP action the dispatcher classifies as a read) or a route
    that names it literally serves only safe HTTP methods. A refused WRITE is
    not an anchor: its route being credentialed says nothing about whether the
    record it writes is publicly readable, and the platform publishes those
    reads deliberately (get_loan, get_listing, get_balance...)."""
    actions = _actions_of(pair)
    if any(a in sd._STATE_MODIFYING_ACTIONS for a in actions):
        return False
    if actions:
        return True
    return any(frozenset(_ROUTE_META["methods"][route]) <= {"GET", "HEAD", "OPTIONS"}
               for (route, service, method) in _ROUTE_META["literal"]
               if (service, method) == pair)


def _sibling_read_census(derived: dict, held_refused: set):
    """The sibling axis, derived rather than listed.

    For every pair an anonymous caller is refused *as a read*, every OPEN
    dispatchable read of the same service that touches a private name — store or
    helper — that the refused read touches is a candidate: it may be the same
    operation under another label, which is how `verify_product` was refused
    while `track_product` returned the whole provenance chain it verifies.

    Each candidate must be adjudicated; *held_refused* is the set of pairs the
    committed adjudication holds refused, and they join the anchor set as they
    are added, so the census runs to a fixed point (refusing a read makes its
    own siblings candidates).

    Returns ``(candidates, refused)``: ``candidates`` is pair -> [(anchor,
    shared names)], ``refused`` is the derived map plus the held pairs, each
    under the route of the anchor it joins (a routed anchor wins the label).
    """
    _route_pairs()
    refused = {tuple(k.split(".", 1)) if isinstance(k, str) else k: v
               for k, v in derived.items()}
    open_reads = sorted({p for a, p in sd.ACTION_MAP.items()
                         if a not in sd._STATE_MODIFYING_ACTIONS})
    candidates: dict = {}
    while True:
        anchors = sorted(p for p in refused if _is_read_anchor(p))
        joined = False
        for pair in open_reads:
            if pair in refused:
                continue
            touched = _private_touch(*pair)
            joins = [(a, sorted(touched & _private_touch(*a))) for a in anchors
                     if a[0] == pair[0] and a != pair and touched & _private_touch(*a)]
            if not joins:
                continue
            candidates[pair] = joins
            if pair in held_refused:
                routed = [a for a, _shared in joins if _routes_naming(a)]
                anchor = routed[0] if routed else joins[0][0]
                refused[pair] = refused[anchor]
                joined = True
        if not joined:
            return candidates, refused


def _routes_naming(pair) -> list[str]:
    """The routes whose handler names *pair* in a literal ``self._call``."""
    _route_pairs()
    return sorted(route for (route, service, method) in _ROUTE_META["literal"]
                  if (service, method) == pair)


def _derived_escapes() -> dict[str, list[str]]:
    from gateway.session_routes import session_may_reach

    pairs = _route_pairs()
    out = {}
    for cap in catalog.CAPABILITIES:
        routes = pairs.get(sd.ACTION_MAP.get(cap["action"]), set())
        if any(not session_may_reach(r) for r in routes):
            out[cap["id"]] = sorted(routes)
    return out


def test_the_escape_set_matches_what_dispatch_actually_reaches():
    from gateway.session_routes import CAPABILITIES_OFF_ALLOWLIST

    derived = _derived_escapes()
    missing = {k: v for k, v in derived.items() if k not in CAPABILITIES_OFF_ALLOWLIST}
    assert not missing, (
        f"{len(missing)} capabilities reach an operator-only route but a session may "
        f"invoke them:\n  " + "\n  ".join(f"{k} -> {v}" for k, v in sorted(missing.items())))
    extra = sorted(set(CAPABILITIES_OFF_ALLOWLIST) - set(derived))
    assert not extra, f"refused to a session with no operator-only route behind them: {extra}"


async def test_a_session_cannot_invoke_any_derived_escape(monkeypatch):
    """Behavioural: through the real auth wall, with an ALLOWING gate so a 403 can
    only be the session refusal, and the dispatcher recorded instead of run."""
    import sys
    import tempfile
    import time

    from aiohttp.test_utils import TestClient, TestServer

    from gateway.server import GatewayServer
    from runtime.capabilities.registry import CapabilityRegistry

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    class _Allow:
        async def evaluate(self, action, context):
            return {"allow": True}

    invoked = []

    async def fake_invoke(self, capability_id, params=None, *, caller_identity=""):
        invoked.append(capability_id)
        return {"status": "ok", "capability_id": capability_id}

    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda: _Allow())
    monkeypatch.setattr(CapabilityRegistry, "invoke", fake_invoke)

    derived = _derived_escapes()
    assert derived, "precondition: some capability reaches an operator-only route"
    scratch = tempfile.mkdtemp(prefix="the-matrix-catalog-truth-")
    server = GatewayServer({**SWEEP_CONFIG, "memory_dir": scratch,
                            "database": {"path": f"{scratch}/s.db"},
                            "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": "k"}})
    reached = []
    async with TestClient(TestServer(server.create_app())) as client:
        now = time.time()
        await server.wallet_sessions.add(token="0xTEST_SESSION", address="apple:sub",
                                         issued_at=now, expires_at=now + 3600)
        for cap_id in sorted(derived):
            resp = await client.post(f"/api/v1/capabilities/{cap_id}/invoke",
                                     headers={"Authorization": "Bearer 0xTEST_SESSION"},
                                     json={"params": {}})
            if resp.status != 403:
                reached.append((cap_id, resp.status, derived[cap_id]))
    assert not reached, (
        "a user session invoked an operation its own route refuses it:\n  "
        + "\n  ".join(f"{c} -> HTTP {s} (route {r})" for c, s, r in reached))
    assert invoked == []


# ── Every session-reachable DISPATCHER, keyed on the pair dispatch runs ───────
#
# bb6635b closed POST /api/v1/capabilities/{id}/invoke and called the boundary
# fixed. It was not: the refusal was keyed on the CATALOG ID and enforced in that
# one handler, and a session reaches the same ServiceDispatcher through two more
# doors that take an ACTION_MAP action name instead of a catalog id:
#
#   POST /bridge/v1/action   — `dispatcher.execute(action, params=...)`, no check.
#                              Measured on bb6635b: every capability in the escape
#                              set answered 403 on invoke and on its own route, and
#                              HTTP 200 here, reaching ServiceDispatcher.execute.
#   POST /bridge/v1/chat     — Trinity's `request_execution` hands any action to
#                              Neo, and her `platform_action` runs reads, with a
#                              model-writable `service` override that changes the
#                              service the pair resolves to.
#
# The refusal is now keyed on the (service, method) PAIR a dispatch resolves to
# (ACTION_MAP plus any service override), which is what the dedicated route's
# `self._call` runs. A catalog id, a bridge action name and a tool call that
# resolve to the same pair get the same answer.


def _derived_refused_pairs() -> dict[tuple[str, str], list[str]]:
    from gateway.session_routes import session_may_reach
    return {pair: sorted(routes) for pair, routes in _route_pairs().items()
            if any(not session_may_reach(r) for r in routes)}


def _actions_reaching_a_refused_pair() -> dict[str, tuple[str, str]]:
    refused = _derived_refused_pairs()
    return {a: p for a, p in sd.ACTION_MAP.items() if p in refused}


def test_the_pair_escape_set_matches_what_the_routes_refuse():
    from gateway.session_routes import SERVICE_METHODS_OFF_ALLOWLIST

    derived = {f"{s}.{m}" for s, m in _derived_refused_pairs()}
    committed = set(SERVICE_METHODS_OFF_ALLOWLIST)
    assert derived - committed == set(), (
        f"operations a session's own route refuses but no dispatcher refuses: {sorted(derived - committed)}")
    assert committed - derived == set(), (
        f"refused to a session with no operator-only route behind them: {sorted(committed - derived)}")


def test_session_refused_route_resolves_the_pair_not_the_label():
    from gateway.session_routes import session_refused_route

    reaching = _actions_reaching_a_refused_pair()
    assert reaching, "precondition: some action reaches an operator-only route"
    assert [a for a in reaching if not session_refused_route(a)] == []
    # A label that is not an action resolves to nothing, and so does a non-string.
    assert session_refused_route("no_such_action") is None
    assert session_refused_route({"action": "send_payment"}) is None
    # The service override is part of the pair: a benign action pointed at a
    # refused service is the refused operation.
    override = [(a, s) for a, (svc, m) in sd.ACTION_MAP.items()
                for (s, rm) in _derived_refused_pairs() if rm == m and s != svc]
    for action, service in override:
        assert session_refused_route(action, service), (action, service)


def _session_server(tmp_path, SWEEP_CONFIG):
    from gateway.server import GatewayServer
    return GatewayServer({**SWEEP_CONFIG, "memory_dir": str(tmp_path / "m"),
                          # The chat control scripts ~100 tool calls in a minute;
                          # URF's rate limit would refuse them before the boundary.
                          "rexhepi": {"rate_limit_max_actions": 100_000},
                          "database": {"path": str(tmp_path / "s.db")},
                          "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": "k"}})


class _RecordingExecute:
    def __init__(self):
        self.calls = []

    def install(self, monkeypatch):
        from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
        calls = self.calls

        async def execute(self, action, service=None, params=None, **kwargs):
            calls.append(action if not service else f"{action}@{service}")
            return '{"status": "ok"}'

        monkeypatch.setattr(ServiceDispatcher, "execute", execute)


async def test_a_session_cannot_reach_a_refused_operation_through_the_bridge_action(monkeypatch, tmp_path):
    """Through the real auth wall, the real noop gate, every ACTION_MAP action whose
    pair backs an operator-only route — catalog capability or not."""
    import sys
    import time

    from aiohttp.test_utils import TestClient, TestServer

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    recorder = _RecordingExecute()
    recorder.install(monkeypatch)
    reaching = _actions_reaching_a_refused_pair()
    # A superset of the catalog escape set bb6635b closed on the invoke route only.
    escape_actions = {catalog.get_by_id(c)["action"] for c in _derived_escapes()}
    assert escape_actions and escape_actions <= set(reaching), escape_actions - set(reaching)
    server = _session_server(tmp_path, SWEEP_CONFIG)
    leaked = []
    async with TestClient(TestServer(server.create_app())) as client:
        now = time.time()
        await server.wallet_sessions.add(token="0xTEST_SESSION", address="apple:sub",
                                         issued_at=now, expires_at=now + 3600)
        for action in sorted(reaching):
            resp = await client.post("/bridge/v1/action",
                                     headers={"Authorization": "Bearer 0xTEST_SESSION"},
                                     json={"action": action, "params": {}, "session_id": "s1"})
            if resp.status != 403:
                leaked.append((action, resp.status))
        assert not leaked, (
            f"{len(leaked)} operations a session's own route refuses answered through "
            "/bridge/v1/action:\n  " + "\n  ".join(f"{a} -> HTTP {s}" for a, s in leaked))
        assert recorder.calls == []

        # The refusal is the SESSION's, not the operation's: the operator key reaches it.
        action = sorted(reaching)[0]
        resp = await client.post("/bridge/v1/action", headers={"Authorization": "Bearer k"},
                                 json={"action": action, "params": {}, "session_id": "s1"})
        assert resp.status == 200 and recorder.calls == [action]


def _scripted_model(server, tool_calls):
    import json

    from runtime.models.model_interface import ModelResponse

    replies = [ModelResponse(tool_calls=[
        {"id": f"c{i}", "function": {"name": name, "arguments": json.dumps(args)}}
        for i, (name, args) in enumerate(tool_calls)])]

    async def complete(**kwargs):
        return replies.pop(0) if replies else ModelResponse(content="done")

    server.react_loop.router.complete = complete


async def test_a_session_cannot_reach_a_refused_operation_through_chat(monkeypatch, tmp_path, caplog):
    """Trinity is all a session can talk to. Her two dispatching tools are
    `request_execution` (any action, executed as Neo) and `platform_action`
    (reads, plus a `service` override the model writes)."""
    import sys
    import time

    from aiohttp.test_utils import TestClient, TestServer

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    class _Allow:
        async def evaluate(self, action, context):
            return {"allow": True}

    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda *a, **k: _Allow())
    recorder = _RecordingExecute()
    recorder.install(monkeypatch)
    reaching = _actions_reaching_a_refused_pair()
    from runtime.access_policy import _is_state_modifying
    state_changing = sorted(a for a in reaching if _is_state_modifying(a))
    reads = sorted(a for a in reaching if not _is_state_modifying(a))
    override = sorted((a, s) for a, (svc, m) in sd.ACTION_MAP.items()
                      for (s, rm) in _derived_refused_pairs() if rm == m and s != svc)
    calls = ([("request_execution", {"action": a, "params": {}}) for a in state_changing]
             + [("platform_action", {"action": a, "params": {}}) for a in reads]
             + [("platform_action", {"action": a, "service": s, "params": {}}) for a, s in override])
    assert reads and state_changing, "precondition: both tools have something to reach"

    server = _session_server(tmp_path, SWEEP_CONFIG)
    async with TestClient(TestServer(server.create_app())) as client:
        # The operator key first: what the script reaches with no session boundary
        # in the way. Anything another gate refuses (Trinity may not execute a
        # state change through platform_action, whatever its service) is not the
        # session boundary's to refuse, and is left out of the comparison.
        _scripted_model(server, calls)
        resp = await client.post("/bridge/v1/chat", headers={"Authorization": "Bearer k"},
                                 json={"message": "do it", "session_id": "operator-run",
                                       "wallet_connected": True})
        assert resp.status == 200, await resp.text()
        operator_reached = list(recorder.calls)
        assert len(operator_reached) >= len(reads) + len(state_changing) - 2, (
            f"the operator's identical chat reached only {operator_reached}: the harness is broken")
        recorder.calls.clear()

        now = time.time()
        await server.wallet_sessions.add(token="0xTEST_SESSION", address="apple:sub",
                                         issued_at=now, expires_at=now + 3600)
        for label, path, headers, body in (
            ("session", "/bridge/v1/chat", {"Authorization": "Bearer 0xTEST_SESSION"}, {}),
            # The chat surfaces are PUBLIC paths: no credential at all reaches the
            # same Trinity, and is refused at least what a session is.
            ("anonymous", "/bridge/v1/chat", {}, {"session_id": "anonymous-run"}),
            ("session /chat", "/chat", {"Authorization": "Bearer 0xTEST_SESSION"},
             {"session_id": "chat-session-run"}),
        ):
            _scripted_model(server, calls)
            caplog.clear()
            import logging
            with caplog.at_level(logging.WARNING, logger="runtime.tools.dispatcher"):
                resp = await client.post(path, headers=headers,
                                         json={"message": "do it", "wallet_connected": True, **body})
            assert resp.status == 200, await resp.text()
            assert recorder.calls == [], (
                f"a {label} chat reached {len(recorder.calls)} operations a session's own "
                f"routes refuse: {recorder.calls}")
            # Refused by the session boundary, not by some other gate that happened
            # to fire first (a URF wallet check did, in the first draft of this test).
            refused_by_boundary = " ".join(r.getMessage() for r in caplog.records
                                           if r.getMessage().startswith(
                                               ("Session DENIED", "Anonymous DENIED")))
            not_by_boundary = [a for a in operator_reached
                               if f"action '{a.split('@')[0]}'" not in refused_by_boundary]
            assert not_by_boundary == [], (label, not_by_boundary)


async def test_a_gateway_context_without_a_caller_kind_is_not_an_operator():
    """The boundary must not depend on every chat surface remembering the field:
    a gateway-built user_context that lacks it is refused like an anonymous
    caller; a run with no user_context at all (A2A, internal) is not an HTTP
    caller and is untouched."""
    from runtime.react_loop import _caller_kind_of
    from runtime.tools.dispatcher import ToolDispatcher

    assert _caller_kind_of({"session_id": "s", "agent": "trinity"}) == "anonymous"
    assert _caller_kind_of({"caller_kind": "operator"}) == "operator"
    assert _caller_kind_of({}) == "" and _caller_kind_of(None) == ""

    ran = []

    async def handler(**kwargs):
        ran.append(kwargs.get("action"))
        return "ran"

    d = ToolDispatcher.__new__(ToolDispatcher)
    d._tools, d._schemas = {"platform_action": handler}, []
    action = sorted(_actions_reaching_a_refused_pair())[0]
    for kind, expect_ran in (("anonymous", False), ("session", False), ("operator", True), ("", True)):
        ran.clear()
        outcome = await d.dispatch("platform_action", {"action": action}, agent_name="neo",
                                   caller_kind=kind)
        assert bool(ran) is expect_ran, (kind, outcome)


async def test_the_operator_batch_still_reaches_the_bridge_dispatchers(monkeypatch, tmp_path):
    """POST /api/v1/batch (operator-only) forwards /bridge/v1/* items to the bridge
    handlers with a synthetic sub-request that carries no credential of its own.
    The boundary must read the batch's credential, not refuse the operator — and
    must not crash on a sub-request that has no query string."""
    import sys

    from aiohttp.test_utils import TestClient, TestServer

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    recorder = _RecordingExecute()
    recorder.install(monkeypatch)
    action = sorted(_actions_reaching_a_refused_pair())[0]
    server = _session_server(tmp_path, SWEEP_CONFIG)
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post("/api/v1/batch", headers={"Authorization": "Bearer k"}, json={
            "requests": [{"id": "a", "method": "POST", "path": "/bridge/v1/action",
                          "body": {"action": action, "params": {}, "session_id": "s1"}}]})
        assert resp.status == 200, await resp.text()
        results = (await resp.json())["results"]
        assert results[0]["status"] == 200, results
        assert recorder.calls == [action]


# ── Round 3: the anonymous tier — one credential down, the same defect ───────
#
# The refusal above models only routes that need the OPERATOR key. The chat
# surfaces (/bridge/v1/chat, /chat, /ws) are PUBLIC paths, so a caller with no
# credential at all reaches Trinity, and her request_execution ran operations
# whose dedicated route answers that caller 401 — measured on 47d18d3:
# transfer_stablecoin, swap_tokens, buy_marketplace, stake and mint_nft each
# reached ServiceDispatcher.execute from an anonymous /bridge/v1/chat, while an
# anonymous POST /api/v1/stablecoin/transfer answered 401.
#
# An anonymous caller is now refused, through every dispatcher, every operation
# whose pair backs a route that is not public (the wall answers it 401 there),
# and every state-changing operation whether or not a route backs it: no public
# route changes state, and there is no identity to attribute the change to.


def _public_paths():
    import tempfile

    from gateway.server import GatewayServer

    scratch = tempfile.mkdtemp(prefix="the-matrix-catalog-truth-")
    return frozenset(GatewayServer({"memory_dir": scratch,
                                    "database": {"path": f"{scratch}/p.db"}})._public_paths)


def _anonymous_adjudications() -> dict:
    """The DECISION on each sibling-read candidate, read from the committed
    module: pair -> (disposition, sibling pair, shared name, why). The class
    itself is re-derived here (§EE): only the disposition — the judgement a
    derivation cannot make — comes from the artifact under test. Read with
    defaults so the census still runs on a tree that predates either table."""
    from gateway import session_routes

    out: dict = {}
    for key, value in getattr(session_routes, "ANONYMOUS_REFUSED_BY_DECISION", {}).items():
        out[tuple(key.split("."))] = ("refused", tuple(value[0].split(".")),
                                      tuple(value[1]), "")
    for key, value in getattr(session_routes, "ANONYMOUS_SIBLING_READS_HELD_OPEN",
                              {}).items():
        out[tuple(key.split("."))] = ("open", tuple(value[0].split(".")),
                                      tuple(value[1]), value[2])
    return out


def _derived_anonymous_refused_pairs() -> dict[tuple[str, str], list[str]]:
    """What the AST derives, plus the sibling reads the committed adjudication
    holds refused, each under the route of the refused read it joins."""
    public = _public_paths()
    derived = {pair: sorted(routes) for pair, routes in _route_pairs().items()
               if any(r not in public for r in routes)}
    held = {p for p, (d, *_rest) in _anonymous_adjudications().items() if d == "refused"}
    _candidates, refused = _sibling_read_census(derived, held)
    return refused


def test_the_anonymous_pair_set_matches_what_the_routes_require():
    from gateway.session_routes import SERVICE_METHODS_OFF_ANONYMOUS

    derived = {f"{s}.{m}" for s, m in _derived_anonymous_refused_pairs()}
    committed = set(SERVICE_METHODS_OFF_ANONYMOUS)
    assert derived - committed == set(), (
        f"operations whose routes an anonymous caller cannot reach but no dispatcher "
        f"refuses it: {sorted(derived - committed)}")
    assert committed - derived == set(), (
        f"refused to an anonymous caller with no credentialed route behind them: "
        f"{sorted(committed - derived)}")
    # Everything a session is refused, an anonymous caller is refused too.
    from gateway.session_routes import SERVICE_METHODS_OFF_ALLOWLIST
    assert set(SERVICE_METHODS_OFF_ALLOWLIST) <= committed


def test_caller_refused_route_by_credential():
    from gateway.session_routes import caller_refused_route

    refused_to_anyone = sorted(_actions_reaching_a_refused_pair())[0]
    anon_pairs = _derived_anonymous_refused_pairs()
    session_only = sorted(a for a, p in sd.ACTION_MAP.items()
                          if p in anon_pairs and p not in _derived_refused_pairs())
    assert session_only, "precondition: some operation backs a session-reachable route"
    unrouted_state_change = sorted(a for a in sd._STATE_MODIFYING_ACTIONS
                                   if a in sd.ACTION_MAP and sd.ACTION_MAP[a] not in _route_pairs())
    assert unrouted_state_change, "precondition: some state change has no dedicated route"

    for action in (refused_to_anyone, session_only[0], unrouted_state_change[0]):
        assert caller_refused_route("anonymous", action), action
        assert caller_refused_route("operator", action) is None
        assert caller_refused_route("", action) is None
        # An unrecognised credential kind is not an operator.
        assert caller_refused_route("superuser", action), action
    assert caller_refused_route("session", refused_to_anyone)
    assert caller_refused_route("session", session_only[0]) is None
    assert caller_refused_route("session", unrouted_state_change[0]) is None


async def test_an_anonymous_chat_is_refused_what_its_routes_refuse_and_a_session_is_not(
        monkeypatch, tmp_path, caplog):
    """Every chat surface, no credential, scripted `request_execution` over every
    state-changing action and `platform_action` over every read whose route needs
    a credential. Nothing may reach ServiceDispatcher.execute. The session run
    of the same script on the same surfaces is the positive control."""
    import json
    import logging
    import sys
    import time

    from aiohttp.test_utils import TestClient, TestServer

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    class _Allow:
        async def evaluate(self, action, context):
            return {"allow": True}

    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda *a, **k: _Allow())
    recorder = _RecordingExecute()
    recorder.install(monkeypatch)

    anon_pairs = _derived_anonymous_refused_pairs()
    state_changing = sorted(a for a in sd._STATE_MODIFYING_ACTIONS if a in sd.ACTION_MAP)
    credentialed_reads = sorted(a for a, p in sd.ACTION_MAP.items()
                                if p in anon_pairs and a not in sd._STATE_MODIFYING_ACTIONS)
    calls = ([("request_execution", {"action": a, "params": {}}) for a in state_changing]
             + [("platform_action", {"action": a, "params": {}}) for a in credentialed_reads])
    # The operations the reviewer probed are in the script.
    for a in ("transfer_stablecoin", "swap_tokens", "buy_marketplace", "stake", "mint_nft"):
        assert a in state_changing, a
    session_refused = set(_actions_reaching_a_refused_pair())

    server = _session_server(tmp_path, SWEEP_CONFIG)

    async def run_ws(client, headers, session_id):
        async with client.ws_connect("/ws", headers=headers) as ws:
            await ws.send_json({"type": "chat", "message": "do it", "agent": "trinity",
                                "session_id": session_id})
            while True:
                frame = json.loads((await ws.receive()).data)
                if frame.get("type") in ("done", "error"):
                    return frame

    async with TestClient(TestServer(server.create_app())) as client:
        _scripted_model(server, calls)
        resp = await client.post("/bridge/v1/chat", headers={"Authorization": "Bearer k"},
                                 json={"message": "do it", "session_id": "operator-run",
                                       "wallet_connected": True})
        assert resp.status == 200, await resp.text()
        operator_reached = [c.split("@")[0] for c in recorder.calls]
        assert len(operator_reached) >= len(calls) // 2, (
            f"the operator's identical chat reached only {len(operator_reached)} of "
            f"{len(calls)}: the harness is broken")
        recorder.calls.clear()

        now = time.time()
        await server.wallet_sessions.add(token="0xTEST_SESSION", address="apple:sub",
                                         issued_at=now, expires_at=now + 3600)
        bearer = {"Authorization": "Bearer 0xTEST_SESSION"}
        expected_for_session = sorted(a for a in operator_reached if a not in session_refused)
        assert expected_for_session, "precondition: a session has something to reach"
        for n, (label, kind, surface, headers) in enumerate((
            ("session /bridge/v1/chat", "session", "/bridge/v1/chat", bearer),
            ("session /ws", "session", "/ws", bearer),
            ("anonymous /bridge/v1/chat", "anonymous", "/bridge/v1/chat", {}),
            ("anonymous /chat", "anonymous", "/chat", {}),
            ("anonymous /ws", "anonymous", "/ws", {}),
        )):
            _scripted_model(server, calls)
            recorder.calls.clear()
            caplog.clear()
            with caplog.at_level(logging.WARNING, logger="runtime.tools.dispatcher"):
                if surface == "/ws":
                    frame = await run_ws(client, headers, f"run-{n}")
                    assert frame.get("type") == "done", frame
                else:
                    resp = await client.post(surface, headers=headers, json={
                        "message": "do it", "wallet_connected": True, "session_id": f"run-{n}"})
                    assert resp.status == 200, await resp.text()
            reached = sorted(c.split("@")[0] for c in recorder.calls)
            if kind == "session":
                # Signed-in callers keep every operation their routes grant them.
                assert reached == expected_for_session, (
                    label, sorted(set(expected_for_session) - set(reached)),
                    sorted(set(reached) - set(expected_for_session)))
                continue
            assert reached == [], (
                f"an {label} chat reached {len(reached)} operations no public route "
                f"grants: {reached}")
            # Refused by the credential boundary, not by another gate that fired first.
            refused = " ".join(r.getMessage() for r in caplog.records
                               if r.getMessage().startswith("Anonymous DENIED"))
            not_by_boundary = [a for a in operator_reached if f"action '{a}'" not in refused]
            assert not_by_boundary == [], (label, not_by_boundary)


# ── Round 4: what the anonymous tier's two tables did not know ───────────────
#
# 03a305e refused an anonymous caller every pair behind a non-public route and
# every action in _STATE_MODIFYING_ACTIONS. Measured at 03a305e, on
# /bridge/v1/chat and /chat with no credential, three dispatches still reached
# ServiceDispatcher.execute:
#   * social_follow (social.follow_wallet), through platform_action AND
#     request_execution. It appends to BOTH wallets' following/followers, with a
#     follower the model writes, and get_feed reads `following` in both modes.
#     It was not in _STATE_MODIFYING_ACTIONS, so neither the anonymous tier nor
#     Trinity's "never a state change through platform_action" rule refused it,
#     at any tier.
#   * selective_disclose (did_identity.selective_disclose): it registers a
#     credential and STORES a presentation under a holder DID the caller names,
#     from a credential the caller need not hold, and verify_presentation later
#     matches against that stored record. Not in the set either.
#   * get_social_feed (social.get_feed), through platform_action: the route
#     /api/v1/social/feed/{wallet} answers an anonymous caller 401, but runs the
#     operation through its get_feed_view wrapper, which the literal-pair
#     derivation could not see.


async def test_an_anonymous_chat_cannot_follow_disclose_or_read_the_wrapped_feed(
        monkeypatch, tmp_path):
    import json
    import sys
    import time

    from aiohttp.test_utils import TestClient, TestServer

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    class _Allow:
        async def evaluate(self, action, context):
            return {"allow": True}

    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda *a, **k: _Allow())
    recorder = _RecordingExecute()
    recorder.install(monkeypatch)

    direct = [("platform_action", {"action": "social_follow",
                                   "params": {"follower": "0xVICTIM", "target": "0xSPAM"}}),
              ("platform_action", {"action": "selective_disclose",
                                   "params": {"did": "did:x", "credential_id": "c", "fields": []}}),
              ("platform_action", {"action": "get_social_feed", "params": {"address": "0xA"}})]
    handoff = [("request_execution", {"action": "social_follow",
                                      "params": {"follower": "0xVICTIM", "target": "0xSPAM"}}),
               ("request_execution", {"action": "selective_disclose",
                                      "params": {"did": "did:x", "credential_id": "c"}})]

    server = _session_server(tmp_path, SWEEP_CONFIG)

    async def chat(client, surface, headers, script, session_id):
        _scripted_model(server, script)
        recorder.calls.clear()
        if surface == "/ws":
            async with client.ws_connect("/ws", headers=headers) as ws:
                await ws.send_json({"type": "chat", "message": "do it", "agent": "trinity",
                                    "session_id": session_id})
                while True:
                    frame = json.loads((await ws.receive()).data)
                    if frame.get("type") in ("done", "error"):
                        assert frame["type"] == "done", frame
                        break
        else:
            resp = await client.post(surface, headers=headers, json={
                "message": "do it", "wallet_connected": True, "session_id": session_id})
            assert resp.status == 200, await resp.text()
        return sorted(c.split("@")[0] for c in recorder.calls)

    async with TestClient(TestServer(server.create_app())) as client:
        now = time.time()
        await server.wallet_sessions.add(token="0xTEST_SESSION", address="apple:sub",
                                         issued_at=now, expires_at=now + 3600)
        operator = {"Authorization": "Bearer k"}
        session = {"Authorization": "Bearer 0xTEST_SESSION"}
        # Positive controls first. Trinity executes no state change through
        # platform_action at any tier; the feed read is a signed-in read, and a
        # signed-in caller's request_execution is not refused either.
        signed_in = (["get_social_feed"], ["selective_disclose", "social_follow"])
        runs = {
            "operator /bridge/v1/chat": ("/bridge/v1/chat", operator, signed_in),
            "session /bridge/v1/chat": ("/bridge/v1/chat", session, signed_in),
            "session /ws": ("/ws", session, signed_in),
            "anonymous /bridge/v1/chat": ("/bridge/v1/chat", {}, ([], [])),
            "anonymous /chat": ("/chat", {}, ([], [])),
            "anonymous /ws": ("/ws", {}, ([], [])),
        }
        reached, expected = {}, {}
        for n, (label, (surface, headers, want)) in enumerate(runs.items()):
            reached[label] = (await chat(client, surface, headers, direct, f"r{n}a"),
                              await chat(client, surface, headers, handoff, f"r{n}b"))
            expected[label] = want
        assert reached == expected, "\n".join(
            f"{k}: platform_action reached {v[0]}, request_execution reached {v[1]}"
            for k, v in reached.items() if v != expected[k])


def test_the_wrapped_feed_read_is_behind_its_route():
    from gateway.session_routes import SERVICE_METHODS_OFF_ANONYMOUS, caller_refused_route

    assert "/api/v1/social/feed/{wallet}" in _route_pairs()[("social", "get_feed")]
    assert SERVICE_METHODS_OFF_ANONYMOUS.get("social.get_feed") == "/api/v1/social/feed/{wallet}"
    assert caller_refused_route("anonymous", "get_social_feed")
    assert caller_refused_route("session", "get_social_feed") is None
    # A helper is not a wrapper: the transfer route computes a fee, and the fee
    # quote stays a read for everyone.
    assert "get_fee" not in _wrapped_methods("stablecoin", "transfer")
    assert caller_refused_route("session", "get_payment_quote") is None


# ── Round 5: the wrapper rule ran one way ────────────────────────────────────
#
# f414a7d's rule saw only what a route's method WRAPS. Measured at f414a7d, an
# anonymous /chat ran platform_action get_price and oracle_price_query, and both
# executed OracleGateway.request("price_feed", {"pair": "BTC/USD"}) — the very
# call GET /api/v1/oracle/price/{pair} makes, and that route answered the same
# caller 401. query_price hands its every argument to request_safe, which hands
# them to request; nothing in the route's method pointed the other way. One
# credential up, cross_border.remit hands everything to send_payment, whose
# route needs the operator key, and a session ran cross_border_remit through
# every dispatcher. Two more reads reach what their sibling's route refuses
# without wrapping it: list_proposals reads the store list_proposals_detailed
# reads, and verify (verify_product) checks the chain verify_authenticity
# checks. Those are decisions, recorded in ANONYMOUS_REFUSED_BY_DECISION and
# held refused to an anonymous caller until a ruling is written.


def test_the_wrapped_price_read_is_behind_its_route():
    from gateway.session_routes import SERVICE_METHODS_OFF_ANONYMOUS, caller_refused_route

    pairs = _route_pairs()
    assert "/api/v1/oracle/price/{pair}" in pairs[("oracle_gateway", "query_price")]
    assert (SERVICE_METHODS_OFF_ANONYMOUS.get("oracle_gateway.query_price")
            == "/api/v1/oracle/price/{pair}")
    for action in ("get_price", "oracle_price_query"):
        assert sd.ACTION_MAP[action] == ("oracle_gateway", "query_price")
        assert caller_refused_route("anonymous", action) == "/api/v1/oracle/price/{pair}"
        assert caller_refused_route("session", action) is None
    # The chain is followed transitively, and the literal fixed two calls up is
    # still a literal where it lands.
    chain = _wrapper_closure("oracle_gateway", "query_price")
    assert chain["request"]["oracle_type"] == ("const", "price_feed"), chain
    # A wrapper that pins the routed method's argument to a DIFFERENT literal is
    # a different operation: neither the weather oracle nor VRF is behind the
    # price route, and the weather read stays what a read with no route is.
    assert ("oracle_gateway", "query_weather") not in pairs
    assert ("oracle_gateway", "request_vrf") not in pairs
    assert caller_refused_route("anonymous", "oracle_weather_query") is None


def test_a_session_is_refused_the_remittance_that_wraps_the_send_its_route_refuses():
    from gateway.session_routes import (
        CAPABILITIES_OFF_ALLOWLIST, SERVICE_METHODS_OFF_ALLOWLIST, caller_refused_route,
    )

    assert "/api/v1/crossborder/send" in _route_pairs()[("cross_border", "remit")]
    assert SERVICE_METHODS_OFF_ALLOWLIST.get("cross_border.remit") == "/api/v1/crossborder/send"
    assert "cross_border_remit" in _actions_reaching_a_refused_pair()
    assert caller_refused_route("session", "cross_border_remit") == "/api/v1/crossborder/send"
    assert caller_refused_route("anonymous", "cross_border_remit")
    assert caller_refused_route("operator", "cross_border_remit") is None
    cap = next(c for c in catalog.CAPABILITIES if c["action"] == "cross_border_remit")
    assert cap["id"] in CAPABILITIES_OFF_ALLOWLIST
    # The label is the pair's OWN route when it has one, not the read it performs
    # on the way: execute_purchase runs get_property, and names /purchase.
    assert (SERVICE_METHODS_OFF_ALLOWLIST["real_estate.execute_purchase"]
            == "/api/v1/realestate/purchase")


# ── Round 6: the wrapper rules stop at the service boundary ──────────────────
#
# c5f2de4 left it unmeasured: "an operation duplicated across services, or
# reached through a component (self.part.x), is not joined". Measured at
# c5f2de4: an anonymous /chat, /bridge/v1/chat and /ws ran platform_action
# get_payment_quote, and the service performed OracleGateway.request(
# "price_feed", {"pair": "USD/EUR"}) — the call GET /api/v1/oracle/price/{pair}
# makes, which answered the same caller 401. cross_border.get_quote reaches it
# through its conversion component, which builds the OracleGateway itself; no
# self.x() crosses the boundary, so neither wrapper rule could see it.


def test_the_quote_that_performs_the_price_read_is_behind_its_route():
    from gateway.session_routes import (
        SERVICE_METHODS_OFF_ALLOWLIST, SERVICE_METHODS_OFF_ANONYMOUS, UNROUTED_STATE_CHANGE,
        caller_refused_route,
    )

    runs = _cross_service_runs("cross_border", "get_quote")
    assert runs[("oracle_gateway", "request")]["oracle_type"] == ("const", "price_feed"), runs
    # Neither wrapper rule joins them: nothing crosses the boundary as self.x().
    assert "get_quote" not in _wrapper_closure("oracle_gateway", "request")
    assert "request" not in _wrapper_closure("cross_border", "get_quote")
    pairs = _route_pairs()
    assert "/api/v1/oracle/price/{pair}" in pairs[("cross_border", "get_quote")]
    assert (SERVICE_METHODS_OFF_ANONYMOUS.get("cross_border.get_quote")
            == "/api/v1/oracle/price/{pair}")
    assert "cross_border.get_quote" not in SERVICE_METHODS_OFF_ALLOWLIST
    assert sd.ACTION_MAP["get_payment_quote"] == ("cross_border", "get_quote")
    assert caller_refused_route("anonymous", "get_payment_quote") == "/api/v1/oracle/price/{pair}"
    assert caller_refused_route("session", "get_payment_quote") is None
    assert caller_refused_route("operator", "get_payment_quote") is None
    # A different literal across the boundary is a different operation: the
    # insurance trigger reads the "weather" and "custom" oracles, never the
    # price, so a claim's auto-settlement stays an unrouted state change.
    trigger = _cross_service_runs("insurance", "auto_settle_claim")[("oracle_gateway", "request")]
    assert trigger["oracle_type"] == ("any", frozenset({"weather", "custom"})), trigger
    assert "/api/v1/oracle/price/{pair}" not in pairs[("insurance", "auto_settle_claim")]
    assert caller_refused_route("anonymous", "claim_auto_settle") == UNROUTED_STATE_CHANGE
    # The passes now repeat; a wrapper that pins the literal differently is
    # still not the route, because the route's literal is lifted onto the
    # wrapper it joins through (request_safe's oracle_type), not dropped.
    assert ("oracle_gateway", "query_weather") not in pairs
    assert caller_refused_route("anonymous", "oracle_weather_query") is None
    # A read that builds no other service stays what a read with no route is.
    assert _cross_service_runs("cross_border", "get_payment") == {}
    assert caller_refused_route("anonymous", "get_cross_border_payment") is None


# ── Round 7: the sibling axis, derived instead of listed ─────────────────────
#
# c5f2de4 held two reads refused by decision — governance.list_proposals and
# supply_chain.verify — and its control pinned the set to exactly those two, so
# nothing could see a third. There was a third, and it gave away more than the
# one recorded: supply_chain.track (track_product) runs the same
# _verify_chain_integrity over the same self._provenance as verify_authenticity
# and returns the ENTIRE provenance chain plus the product record. Measured at
# 492abdd, an anonymous chat on /chat, /bridge/v1/chat and /ws reached
# track_product, get_proposal, get_social_profile and get_activity, while
# verify_product and list_proposals were denied in the same run and
# /api/v1/supply-chain/verify, /api/v1/governance/daos/{daoId}/proposals,
# /api/v1/social/feed/{wallet} and /api/v1/dashboard/{address} all answered that
# caller 401.
#
# So the CLASS is derived here and in the generator, and every member is
# adjudicated: refused, or held open with the reason. Where the census can be
# LOW, in the order it would bite:
#   * the anchors are the refused READS only. A refused WRITE does not anchor —
#     its route needing a credential says nothing about whether the record is
#     publicly readable, and the platform publishes those reads on purpose
#     (get_loan beside create_loan). 60-odd such read/write pairs exist; none is
#     examined here.
#   * the join is within ONE service. The same data reached through another
#     service's store (the dashboard aggregator holds every service) is not a
#     candidate; the cross-service rule of Round 6 covers only what a route's
#     own operation performs.
#   * the join is on the NAME of a private attribute or helper. A store reached
#     through a module-level function, a local bound some other way, or a second
#     object holding the same records is invisible to it.
#   * the candidates are the DISPATCHABLE reads. A public method no ACTION_MAP
#     action names is not one — no dispatcher can be asked for it today — and it
#     joins the census the moment an action maps to it.


def test_every_sibling_read_of_an_anonymous_refused_read_is_adjudicated():
    """The class, not the two instances somebody happened to name.

    c5f2de4 recorded `governance.list_proposals` and `supply_chain.verify` and
    pinned the set to those two, so a third sibling was invisible — and there
    was one: `supply_chain.track` (track_product) runs `_verify_chain_integrity`
    over the same `self._provenance` and returns the whole chain on top of it,
    while an anonymous POST /api/v1/supply-chain/verify answers 401.

    Here the CLASS is derived — every open dispatchable read that touches a
    private name an anonymous-refused READ touches — and every member must be
    adjudicated, refused or open, with what it rests on checked. A new sibling
    fails this test instead of passing silently."""
    from gateway import session_routes
    from gateway.session_routes import (
        SERVICE_METHODS_OFF_ALLOWLIST, SERVICE_METHODS_OFF_ANONYMOUS, caller_refused_route,
    )

    # Read with defaults: on a tree with neither table this test must fail on
    # the unadjudicated CLASS below, not on a missing name.
    refused_by_decision = getattr(session_routes, "ANONYMOUS_REFUSED_BY_DECISION", {})
    held_open = getattr(session_routes, "ANONYMOUS_SIBLING_READS_HELD_OPEN", {})
    public = _public_paths()
    derived = {pair: sorted(routes) for pair, routes in _route_pairs().items()
               if any(r not in public for r in routes)}
    adjudicated = _anonymous_adjudications()
    held = {p for p, (d, *_r) in adjudicated.items() if d == "refused"}
    candidates, refused = _sibling_read_census(derived, held)

    unadjudicated = sorted(f"{s}.{m}" for s, m in set(candidates) - set(adjudicated))
    assert unadjudicated == [], (
        f"{len(unadjudicated)} public reads touch a store or helper an anonymous-refused "
        "READ touches and nothing rules on them. Refuse each in "
        "SAME_STORE_ADJUDICATED, or record there why the store is readable "
        f"without the credential its sibling's route needs:\n  " + "\n  ".join(
            f"{k}: {[(f'{a[0]}.{a[1]}', sh) for a, sh in candidates[tuple(k.split('.'))]]}"
            for k in unadjudicated))
    stale = sorted(f"{s}.{m}" for s, m in set(adjudicated) - set(candidates))
    assert stale == [], f"adjudicated, but no longer a sibling of any refused read: {stale}"
    # The instances this class was named after, and the one the pin hid.
    for key in ("governance.list_proposals", "governance.get_proposal",
                "supply_chain.verify", "supply_chain.track"):
        assert key in SERVICE_METHODS_OFF_ANONYMOUS, key

    for pair, (disposition, sibling, shared, why) in sorted(adjudicated.items()):
        key, service = f"{pair[0]}.{pair[1]}", pair[0]
        joins = candidates[pair]
        assert sibling in [a for a, _sh in joins], (key, sibling, joins)
        assert sibling[0] == service and sibling != pair
        # Still a decision, not a derivation: were a wrapper chain or a route to
        # join them, the pair would be refused without anybody ruling on it.
        assert pair not in derived, f"{key} is derived now; drop the adjudication"
        assert sibling in refused and _is_read_anchor(sibling), sibling
        assert shared, key
        # Every name the record claims they share, they still share — and the
        # record is the WHOLE overlap, so a name dropping out fails here.
        assert set(shared) == _private_touch(*pair) & _private_touch(*sibling), (key, shared)
        assert dict(joins)[sibling] == sorted(shared), (key, joins)
        actions = _actions_of(pair)
        assert actions, key
        if disposition == "refused":
            assert SERVICE_METHODS_OFF_ANONYMOUS[key] == SERVICE_METHODS_OFF_ANONYMOUS[
                f"{sibling[0]}.{sibling[1]}"], key
            # Held one credential down only: a session keeps what its routes grant.
            assert key not in SERVICE_METHODS_OFF_ALLOWLIST
            for action in actions:
                assert (caller_refused_route("anonymous", action)
                        == SERVICE_METHODS_OFF_ANONYMOUS[key]), action
                assert caller_refused_route("session", action) is None, action
        else:
            assert disposition == "open", disposition
            assert why.strip(), f"{key} is held open with no reason recorded"
            assert key not in SERVICE_METHODS_OFF_ANONYMOUS, key
            for action in actions:
                assert caller_refused_route("anonymous", action) is None, action

    assert set(refused_by_decision) | set(held_open) == {f"{s}.{m}" for s, m in adjudicated}
    assert not set(refused_by_decision) & set(held_open), "adjudicated both ways"


def test_the_sibling_census_sees_the_join_it_is_asked_to_rule_out():
    """The detector itself: track and verify_authenticity share the provenance
    store AND the integrity helper; get_proposal and list_proposals_detailed
    share the proposal store, its votes and the quorum component; and a read of
    another service shares nothing, so the census is not joining everything."""
    assert {"_provenance", "_verify_chain_integrity"} <= (
        _private_touch("supply_chain", "track")
        & _private_touch("supply_chain", "verify_authenticity"))
    assert {"_proposals", "_votes", "_quorum"} <= (
        _private_touch("governance", "get_proposal")
        & _private_touch("governance", "list_proposals_detailed"))
    assert not (_private_touch("supply_chain", "track")
                & _private_touch("governance", "get_proposal"))
    # The anchor rule: a refused READ anchors, a refused WRITE does not — which
    # is why get_loan, whose store defi.create_loan writes, is not a candidate.
    assert _is_read_anchor(("supply_chain", "verify_authenticity"))
    assert _is_read_anchor(("governance", "list_proposals_detailed"))  # GET-only route
    assert not _is_read_anchor(("defi", "create_loan"))
    assert not _is_read_anchor(("stablecoin", "transfer"))


async def test_an_anonymous_chat_cannot_read_the_price_proposals_or_provenance_its_routes_refuse(
        monkeypatch, tmp_path):
    """With no credential, on /bridge/v1/chat, /chat and /ws, platform_action
    get_price and oracle_price_query (oracle_gateway.query_price -> request_safe
    -> request("price_feed"), what GET /api/v1/oracle/price/{pair} runs and
    answers 401), get_payment_quote (cross_border.get_quote, whose conversion
    component builds an OracleGateway and performs that same price read for the
    pair the caller names), list_proposals and verify_product (held by decision)
    must reach ServiceDispatcher.execute for nobody. A session on /bridge/v1/chat
    and /ws reaches all five, as its routes grant it. The second script is the session
    tier's leg: request_execution cross_border_remit hands everything to
    send_payment, whose route needs the operator key — the operator reaches it
    and nobody else does. Measured at f414a7d: every anonymous run reached all
    four reads, and both session runs reached the remittance."""
    import json
    import sys
    import time

    from aiohttp.test_utils import TestClient, TestServer

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    class _Allow:
        async def evaluate(self, action, context):
            return {"allow": True}

    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda *a, **k: _Allow())
    recorder = _RecordingExecute()
    recorder.install(monkeypatch)

    reads = [("platform_action", {"action": "get_price", "params": {"pair": "BTC/USD"}}),
             ("platform_action", {"action": "oracle_price_query", "params": {"pair": "BTC/USD"}}),
             ("platform_action", {"action": "get_payment_quote", "params": {
                 "amount": 100, "from_currency": "USD", "to_currency": "EUR"}}),
             ("platform_action", {"action": "list_proposals", "params": {}}),
             ("platform_action", {"action": "verify_product", "params": {"product_id": "p1"}})]
    remit = [("request_execution", {"action": "cross_border_remit", "params": {
        "sender": "0xA", "recipient": "0xB", "amount": 1.0,
        "from_currency": "USD", "to_currency": "EUR"}})]
    all_reads = ["get_payment_quote", "get_price", "list_proposals", "oracle_price_query",
                 "verify_product"]

    server = _session_server(tmp_path, SWEEP_CONFIG)

    async def chat(client, surface, headers, script, session_id):
        _scripted_model(server, script)
        recorder.calls.clear()
        if surface == "/ws":
            async with client.ws_connect("/ws", headers=headers) as ws:
                await ws.send_json({"type": "chat", "message": "do it", "agent": "trinity",
                                    "session_id": session_id})
                while True:
                    frame = json.loads((await ws.receive()).data)
                    if frame.get("type") in ("done", "error"):
                        assert frame["type"] == "done", frame
                        break
        else:
            resp = await client.post(surface, headers=headers, json={
                "message": "do it", "wallet_connected": True, "session_id": session_id})
            assert resp.status == 200, await resp.text()
        return sorted(c.split("@")[0] for c in recorder.calls)

    async with TestClient(TestServer(server.create_app())) as client:
        now = time.time()
        await server.wallet_sessions.add(token="0xTEST_SESSION", address="apple:sub",
                                         issued_at=now, expires_at=now + 3600)
        operator = {"Authorization": "Bearer k"}
        session = {"Authorization": "Bearer 0xTEST_SESSION"}
        runs = {
            "operator /bridge/v1/chat": ("/bridge/v1/chat", operator, (all_reads, ["cross_border_remit"])),
            "session /bridge/v1/chat": ("/bridge/v1/chat", session, (all_reads, [])),
            "session /ws": ("/ws", session, (all_reads, [])),
            "anonymous /bridge/v1/chat": ("/bridge/v1/chat", {}, ([], [])),
            "anonymous /chat": ("/chat", {}, ([], [])),
            "anonymous /ws": ("/ws", {}, ([], [])),
        }
        reached, expected = {}, {}
        for n, (label, (surface, headers, want)) in enumerate(runs.items()):
            reached[label] = (await chat(client, surface, headers, reads, f"p{n}a"),
                              await chat(client, surface, headers, remit, f"p{n}b"))
            expected[label] = want
        assert reached == expected, "\n".join(
            f"{k}: reads reached {v[0]}, remit reached {v[1]}"
            for k, v in reached.items() if v != expected[k])


async def test_an_anonymous_chat_cannot_read_the_chain_proposal_profile_or_activity_of_a_wallet(
        monkeypatch, tmp_path):
    """Round 7: the siblings the pinned pair of decisions hid.

    Measured at 492abdd, with no credential, on /chat, /bridge/v1/chat and /ws:
      * platform_action track_product ran SupplyChainService.track, which runs
        `_verify_chain_integrity` over the same `self._provenance` that
        verify_authenticity runs it over and returns the whole provenance chain
        — every event, handler, location and hash — plus the product record,
        while verify_product and authenticity_verify were DENIED in the same run
        and an anonymous POST /api/v1/supply-chain/verify answered 401.
      * platform_action get_proposal returned the full proposal record while
        list_proposals was denied and GET
        /api/v1/governance/daos/{daoId}/proposals answered 401.
      * platform_action get_social_profile returned the profile record — which
        carries the wallet's followers and following — while GET
        /api/v1/social/feed/{wallet}, whose read resolves who a wallet follows
        out of that same store, answers 401.
      * platform_action get_activity returned the named wallet's cross-component
        activity through the same aggregator GET /api/v1/dashboard/{address}
        runs, and that route answers 401.
    A session reaches all four, as its routes grant it. get_platform_stats is
    the other half of the census — adjudicated OPEN, a count with no wallet in
    it — and every tier still reaches it, so the refusal is the sibling's, not
    a blanket one on the service."""
    import json
    import sys
    import time

    from aiohttp.test_utils import TestClient, TestServer

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    class _Allow:
        async def evaluate(self, action, context):
            return {"allow": True}

    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda *a, **k: _Allow())
    recorder = _RecordingExecute()
    recorder.install(monkeypatch)

    script = [("platform_action", {"action": "track_product", "params": {"product_id": "p1"}}),
              ("platform_action", {"action": "get_proposal", "params": {"proposal_id": "gp1"}}),
              ("platform_action", {"action": "get_social_profile", "params": {"address": "0xA"}}),
              ("platform_action", {"action": "get_activity", "params": {"address": "0xA"}}),
              ("platform_action", {"action": "get_platform_stats", "params": {}})]
    siblings = ["get_activity", "get_proposal", "get_social_profile", "track_product"]
    held_open = ["get_platform_stats"]

    server = _session_server(tmp_path, SWEEP_CONFIG)

    async def chat(client, surface, headers, session_id):
        _scripted_model(server, script)
        recorder.calls.clear()
        if surface == "/ws":
            async with client.ws_connect("/ws", headers=headers) as ws:
                await ws.send_json({"type": "chat", "message": "do it", "agent": "trinity",
                                    "session_id": session_id})
                while True:
                    frame = json.loads((await ws.receive()).data)
                    if frame.get("type") in ("done", "error"):
                        assert frame["type"] == "done", frame
                        break
        else:
            resp = await client.post(surface, headers=headers, json={
                "message": "do it", "wallet_connected": True, "session_id": session_id})
            assert resp.status == 200, await resp.text()
        return sorted(c.split("@")[0] for c in recorder.calls)

    async with TestClient(TestServer(server.create_app())) as client:
        now = time.time()
        await server.wallet_sessions.add(token="0xTEST_SESSION", address="apple:sub",
                                         issued_at=now, expires_at=now + 3600)
        operator = {"Authorization": "Bearer k"}
        session = {"Authorization": "Bearer 0xTEST_SESSION"}
        everything = sorted(siblings + held_open)
        runs = {
            "operator /bridge/v1/chat": ("/bridge/v1/chat", operator, everything),
            "session /bridge/v1/chat": ("/bridge/v1/chat", session, everything),
            "session /ws": ("/ws", session, everything),
            "anonymous /bridge/v1/chat": ("/bridge/v1/chat", {}, held_open),
            "anonymous /chat": ("/chat", {}, held_open),
            "anonymous /ws": ("/ws", {}, held_open),
        }
        reached, expected = {}, {}
        for n, (label, (surface, headers, want)) in enumerate(runs.items()):
            reached[label] = await chat(client, surface, headers, f"s{n}")
            expected[label] = want
        assert reached == expected, "\n".join(
            f"{k}: reached {v}, expected {expected[k]}"
            for k, v in reached.items() if v != expected[k])


async def test_the_routes_those_siblings_read_behind_answer_an_anonymous_caller_401(tmp_path):
    """The other half of the claim: each refused sibling's route really does
    refuse a caller with no credential, so the refusal above is the same wall
    one door down and not a rule invented for the chat."""
    import sys

    from aiohttp.test_utils import TestClient, TestServer

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    server = _session_server(tmp_path, SWEEP_CONFIG)
    async with TestClient(TestServer(server.create_app())) as client:
        for method, path in (("post", "/api/v1/supply-chain/verify"),
                             ("get", "/api/v1/governance/daos/d1/proposals"),
                             ("get", "/api/v1/social/feed/0xA"),
                             ("get", "/api/v1/dashboard/0xA")):
            resp = await getattr(client, method)(path, json={"product_id": "p1"})
            assert resp.status == 401, (path, resp.status, await resp.text())


# ── The class: a "read" that writes must be adjudicated, not assumed ─────────
#
# Membership in _STATE_MODIFYING_ACTIONS decides Trinity's platform_action rule,
# the anonymous tier's unrouted arm, attestation and the gate-fault direction.
# social_follow was missing from it for as long as it existed, because nothing
# checked a read. This walks every ACTION_MAP action OUTSIDE the set, follows its
# method through `self.x(...)` and `self.part.x(...)` calls, and reports each
# write to state the service holds: an assignment or `del` on something reached
# from `self`, a mutating container call on it, or SQL that writes. A read that
# writes is either adjudicated below, with the reason it is not a state change a
# caller makes, or the test fails.
#
# Blind spots, so the census could be LOW: a write through a module-level
# function or an object not reached as `self.part`, a write inside another
# package's client, and a local name bound from a self container by any spelling
# other than subscript, `.get(...)`, `.setdefault(...)`, attribute or a `for`
# over one.

READS_THAT_WRITE: dict[str, str] = {
    # caches and counters: the value served is the same with or without them
    "get_activity": "dashboard aggregate cache",
    "get_dashboard": "dashboard aggregate cache",
    "get_payment_quote": "FX rate cache",
    "get_price": "oracle response cache, hit/miss counters, per-caller rate-limit window",
    "oracle_price_query": "oracle response cache, hit/miss counters, per-caller rate-limit window",
    "oracle_request": "oracle response cache, hit/miss counters, per-caller rate-limit window",
    "oracle_weather_query": "oracle response cache, hit/miss counters, per-caller rate-limit window",
    "get_staking_position": (
        "appends the pool's computed APY to its history: the value comes from pool "
        "state, not the caller, though a caller does choose when a sample is taken; "
        "the calculator refuses while staking is not deployed"),
    # get-or-create of an EMPTY record: nothing the caller supplies is stored
    "get_cashback_balance": "creates an empty per-user ledger on first read",
    "get_spending_summary": "creates an empty per-user ledger on first read",
    "get_loyalty_balance": "creates an empty per-user ledger on first read",
    "get_loyalty_tier": "creates an empty per-user ledger on first read",
    "get_security": "creates an empty order book on first read",
    "get_privacy_commitment": (
        "creates the per-user privacy statement (constant text, no caller content) and "
        "refreshes its derived deletion-request counts; deletion requests are refused "
        "at the service, so the history is empty"),
    # deadline-driven transitions: the clock decides the outcome, a read only
    # materialises it, and the caller chooses nothing about it
    "get_insurance_policy": "marks an active policy expired once expires_at has passed",
    "get_payment": "marks a pending payment expired once expires_at has passed",
    "get_proposal": "marks an active proposal expired once ends_at has passed",
    "get_campaign": ("fails an active campaign past its deadline below goal and computes "
                     "its refunds (calculated_unpaid: nothing is paid)"),
    "list_campaigns": ("fails an active campaign past its deadline below goal and computes "
                       "its refunds (calculated_unpaid: nothing is paid)"),
    "list_proposals": "marks an active proposal expired once ends_at has passed",
}

_MUTATING_CALLS = frozenset({
    "append", "appendleft", "extend", "insert", "remove", "pop", "popitem", "popleft",
    "clear", "update", "setdefault", "add", "discard", "sort", "reverse",
    "__setitem__", "__delitem__",
})


def _state_writes(owner, fn, seen, depth=0) -> list[str]:
    import ast
    import inspect
    import re
    import textwrap

    code = getattr(fn, "__code__", None)
    if code is None or "site-packages" in code.co_filename or depth > 8:
        return []
    key = (id(owner), code.co_filename, code.co_firstlineno)
    if key in seen:
        return []
    seen.add(key)
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError):
        return []
    where = f"{type(owner).__name__}.{fn.__name__}"

    def root(node):
        while isinstance(node, (ast.Attribute, ast.Subscript, ast.Call, ast.Await)):
            node = node.func if isinstance(node, ast.Call) else node.value
        return node.id if isinstance(node, ast.Name) else None

    aliases = {"self"}

    def reaches_state(node):
        if isinstance(node, ast.Await):
            node = node.value
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            return root(node) in aliases
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("get", "setdefault") and root(node.func.value) in aliases)

    for _ in range(3):  # aliases of aliases
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and reaches_state(node.value):
                aliases |= {t.id for t in node.targets if isinstance(t, ast.Name)}
            elif isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.target, ast.Name):
                it = node.iter
                if (isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute)
                        and it.func.attr in ("values", "items")):
                    it = it.func.value
                if reaches_state(it) or (isinstance(it, ast.Name) and it.id in aliases):
                    aliases.add(node.target.id)

    out = []
    for node in ast.walk(tree):
        line = code.co_firstlineno + getattr(node, "lineno", 1) - 1
        targets = (node.targets if isinstance(node, (ast.Assign, ast.Delete))
                   else [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign)) else [])
        for t in targets:
            if isinstance(t, (ast.Attribute, ast.Subscript)) and root(t) in aliases:
                out.append(f"{where}:{line} {ast.unparse(t)}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.match(
                r"\s*(INSERT|UPDATE|DELETE|REPLACE)\b", node.value, re.I):
            out.append(f"{where}:{line} SQL {node.value.strip()[:30]}")
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        receiver = node.func.value
        if node.func.attr in _MUTATING_CALLS and root(receiver) in aliases:
            out.append(f"{where}:{line} {ast.unparse(node.func)}()")
        if isinstance(receiver, ast.Name) and receiver.id == "self":
            out += _state_writes(owner, getattr(type(owner), node.func.attr, None), seen, depth + 1)
        elif (isinstance(receiver, ast.Attribute) and isinstance(receiver.value, ast.Name)
              and receiver.value.id == "self"):
            part = getattr(owner, receiver.attr, None)
            if part is not None:
                out += _state_writes(part, getattr(type(part), node.func.attr, None), seen,
                                     depth + 1)
    return out


def _reads_that_write() -> dict[str, list[str]]:
    registry = service_registry.ServiceRegistry({})
    found = {}
    for action in sorted(sd.ACTION_MAP):
        if action in sd._STATE_MODIFYING_ACTIONS:
            continue
        service, method = sd.ACTION_MAP[action]
        owner = registry.get(service)
        writes = _state_writes(owner, getattr(type(owner), method, None), set())
        if writes:
            found[action] = writes
    return found


def test_the_detector_sees_the_state_changes_it_is_asked_to_rule_out():
    registry = service_registry.ServiceRegistry({})
    for service, method in (("social", "follow_wallet"), ("did_identity", "selective_disclose"),
                            ("stablecoin", "transfer")):
        owner = registry.get(service)
        assert _state_writes(owner, getattr(type(owner), method), set()), (service, method)


def test_no_action_outside_the_state_set_writes_state_unadjudicated():
    found = _reads_that_write()
    unadjudicated = {a: w for a, w in found.items() if a not in READS_THAT_WRITE}
    assert unadjudicated == {}, (
        f"{len(unadjudicated)} actions outside _STATE_MODIFYING_ACTIONS write state. Put "
        "each in the set, or adjudicate it in READS_THAT_WRITE with why it is not a "
        "state change a caller makes:\n  " + "\n  ".join(
            f"{a}: {w[:4]}" for a, w in sorted(unadjudicated.items())))
    stale = sorted(set(READS_THAT_WRITE) - set(found))
    assert stale == [], f"adjudicated as writing, but no write is found any more: {stale}"


def test_social_follow_and_selective_disclose_are_state_changes():
    from runtime.access_policy import default_agent_access

    for action in ("social_follow", "selective_disclose"):
        assert action in sd._STATE_MODIFYING_ACTIONS, action
        allowed, _ = default_agent_access("trinity", "platform_action", action)
        assert not allowed, action


async def test_a_follow_that_wrote_nothing_is_not_attested_as_one():
    """Now that social_follow is attested, a follow between two wallets with no
    profile, which writes nothing, must not report `following`."""
    svc = service_registry.ServiceRegistry({}).get("social")
    result = await svc.follow_wallet("0xNOBODY", "0xNOONE")
    assert sd._outcome_is_real(result) is False, result
