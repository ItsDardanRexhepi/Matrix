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


def _call_pairs(fn_source: str, where: str) -> dict:
    """Every (service, method) a handler's body passes to ``self._call``, with the
    keyword arguments the handler FIXES on it: ``{(service, method): {kw: b}}``
    where ``b`` is ``("const", value)`` for a literal and ``("other",)`` for
    anything else. The literals are what make a route one operation and not
    another (``oracle_type="price_feed"``), so the wrapper rules below compare
    them.

    Read from the AST, not a regex: a comment between ``self._call(`` and its
    first literal (NEW-89 left one in _handle_provenance_log) made the regex miss
    the call, and the capability behind it with it. EVERY literal call is kept,
    not only the first. A ``self._call`` whose service or method is not a string
    literal cannot be attributed to a pair, so it stops the generator rather than
    silently leaving an operation off the refusal set. The same pair called twice
    with different literals keeps neither: a mismatch must never exclude.
    """
    import ast as _ast
    import textwrap as _textwrap

    out: dict = {}
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
        fixed = {k.arg: (("const", k.value.value) if isinstance(k.value, _ast.Constant)
                         else ("other",))
                 for k in node.keywords if k.arg is not None}
        pair = (head[0].value, head[1].value)
        if pair in out:
            prev = out[pair]
            fixed = {k: (prev[k] if k in prev and k in fixed and prev[k] == fixed[k]
                         else ("other",))
                     for k in set(prev) | set(fixed)}
        out[pair] = fixed
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
    """canonical route -> {(service, method): fixed kwargs} from the REAL app's router.

    Routes are read from the router the gateway builds, not regexed out of
    service_routes.py: the regex only knew ``app.router.add_x("/path",
    self._handle_x)``, and the P2 routes registered from a
    ``(method, path, handler)`` table were invisible to it — including two whose
    operation a session is refused.

    A route runs more than the literal pair, in BOTH directions:
      * what its method WRAPS. /api/v1/social/feed/{wallet} calls
        social.get_feed_view, which hands every argument to social.get_feed; the
        literal pair alone left get_social_feed readable by an anonymous chat
        while the route answered it 401.
      * what WRAPS its method. /api/v1/oracle/price/{pair} calls
        oracle_gateway.request(oracle_type="price_feed", ...); query_price — the
        method behind get_price and oracle_price_query — hands its every argument
        to request_safe, which hands them to request with that same literal. The
        first rule could not see it, and an anonymous chat read the price its
        route refused it. cross_border.remit is the same shape one credential
        up: it hands everything to send_payment, whose route needs the operator
        key, and a session ran cross_border_remit.
      * what performs its method ACROSS the service boundary. cross_border.get_quote
        asks its conversion component for a rate, and that component builds an
        OracleGateway and calls request("price_feed", {"pair": ...}) on it — the
        price route's own call, for the pair the caller names. No self.x() joins
        two services, so neither wrapper rule could see it, and an anonymous
        chat ran get_payment_quote (cross_service_runs).
    All three follow their chains transitively and compose the literals down
    them, so a wrapper or a cross-service caller that pins the routed method's
    argument to a DIFFERENT literal (request_vrf: "random_vrf"; the insurance
    trigger's "weather") is a different operation and is not included. The
    passes repeat until nothing joins, so a wrapper of a cross-service caller,
    or a cross-service caller of a wrapper, is joined too.
    """
    import inspect as _inspect

    if "pairs" in _LIVE:
        return _LIVE["pairs"]
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
            out.setdefault(resource.canonical, {}).update(pairs)
    _LIVE["literal"] = {route: frozenset(pairs) for route, pairs in out.items()}
    for pairs in out.values():
        # Forward, from the literal pairs only: the route runs everything its
        # method wraps, with the route's literals carried through the chain.
        # Not chained from what joins below: a wrapper's OTHER wrappees are not
        # run by the route.
        for (service, method), fixed in list(pairs.items()):
            for wrapped, chain in wrapper_closure(service, method).items():
                pairs.setdefault((service, wrapped), _through(fixed, chain))
        while True:
            before = len(pairs)
            # Across services: every public method of ANY service that builds
            # a service the route runs and calls the routed method on it, with
            # literals that do not contradict the route's, performs the route's
            # operation. It joins with no literal of its own to carry.
            for (service, method), fixed in list(pairs.items()):
                for other, name, chain in cross_service_runners(service, method):
                    if (other, name) not in pairs and _consistent(chain, fixed):
                        pairs[(other, name)] = {}
            # Reverse: every public method that wraps something the route runs,
            # with literals that do not contradict the route's, runs the route's
            # operation. It joins carrying the route's literals lifted onto its
            # own parameters, so a wrapper of it that pins one differently
            # (query_weather -> request_safe -> request) is still not the route.
            for (service, method), fixed in list(pairs.items()):
                for name in _public_methods(service):
                    if (service, name) in pairs:
                        continue
                    chain = wrapper_closure(service, name).get(method)
                    if chain is not None and _consistent(chain, fixed):
                        pairs[(service, name)] = _lift(chain, fixed)
            # Until nothing joins: a wrapper of a cross-service caller, and a
            # cross-service caller of a wrapper, are both the route's operation.
            if len(pairs) == before:
                break
    _LIVE["pairs"] = out
    return out


def _service_class(service: str):
    import importlib as _importlib

    from runtime.blockchain.services import registry as _registry

    if service not in _registry._SERVICE_MAP:
        return None
    module_path, class_name = _registry._SERVICE_MAP[service]
    return getattr(_importlib.import_module(module_path, package=_registry._PACKAGE), class_name)


def _public_methods(service: str) -> list:
    import inspect as _inspect

    cls = _service_class(service)
    if cls is None:
        return []
    return sorted(n for n, _ in _inspect.getmembers(cls, predicate=_inspect.isfunction)
                  if not n.startswith("_"))


def _function_def(cls, name: str):
    """The AST of method *name* on *cls*, or None when it has no source."""
    import ast as _ast
    import inspect as _inspect
    import textwrap as _textwrap

    fn = getattr(cls, name, None)
    if not callable(fn):
        return None
    try:
        return _ast.parse(_textwrap.dedent(_inspect.getsource(fn))).body[0]
    except (OSError, TypeError, IndexError):
        return None


def _signature(fdef):
    """(positional names, keyword-only names, required names, *args/**kwargs names)."""
    a = fdef.args
    positional = [x.arg for x in a.posonlyargs + a.args if x.arg != "self"]
    kwonly = [x.arg for x in a.kwonlyargs]
    required = set(positional[:len(positional) - len(a.defaults)])
    required |= {k.arg for k, d in zip(a.kwonlyargs, a.kw_defaults) if d is None}
    var = [v.arg for v in (a.vararg, a.kwarg) if v is not None]
    return positional, kwonly, required, var


def _bindings(callee_fdef, call, own: set) -> dict:
    """How *call* binds the callee's parameters: ``("const", v)`` for a literal,
    ``("param", name)`` for one of the caller's own parameters, ``("other",)``
    for anything else. A parameter the call leaves unbound takes the callee's
    default, which is never compared."""
    import ast as _ast

    positional, kwonly, _required, _var = _signature(callee_fdef)

    def binding(node):
        if isinstance(node, _ast.Constant):
            return ("const", node.value)
        if isinstance(node, _ast.Name) and node.id in own:
            return ("param", node.id)
        return ("other",)

    out = {}
    for i, arg in enumerate(call.args):
        if not isinstance(arg, _ast.Starred) and i < len(positional):
            out[positional[i]] = binding(arg)
    for kw in call.keywords:
        if kw.arg is not None and (kw.arg in positional or kw.arg in kwonly):
            out[kw.arg] = binding(kw.value)
    return out


def wrapped_methods(service: str, method: str) -> dict:
    """Public methods of *service* that *method* WRAPS, each mapped to how the
    call binds the callee's parameters. A wrapper passes EVERY one of its own
    required parameters (and any *args / **kwargs) on, and at least one of its
    parameters at all; with none to pass, only a sole public self-call counts. A
    helper (the fee a transfer computes) receives only some of the caller's
    arguments and is not the route's operation, so it is not included. A
    parameter with a default that the wrapper keeps for itself (request_safe's
    stale_max_age, which only its fallback uses) does not stop it being one."""
    import ast as _ast

    cls = _service_class(service)
    fdef = _function_def(cls, method) if cls is not None else None
    if fdef is None:
        return {}
    positional, kwonly, required, var = _signature(fdef)
    own = set(positional) | set(kwonly) | set(var)
    must = required | set(var)
    calls = [n for n in _ast.walk(fdef)
             if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
             and isinstance(n.func.value, _ast.Name) and n.func.value.id == "self"
             and not n.func.attr.startswith("_") and callable(getattr(cls, n.func.attr, None))]
    out = {}
    for call in calls:
        passed = {x.id for arg in [*call.args, *(k.value for k in call.keywords)]
                  for x in _ast.walk(arg) if isinstance(x, _ast.Name)}
        callee = _function_def(cls, call.func.attr)
        if callee is not None and must <= passed and ((own & passed) or len(calls) == 1):
            out[call.func.attr] = _bindings(callee, call, own)
    return out


def wrapper_closure(service: str, method: str) -> dict:
    """Every public method *method* reaches through wrappers, transitively —
    query_price -> request_safe -> request — mapped to how the reached method's
    parameters are bound in terms of *method*'s OWN parameters and literals,
    composed down the chain: a literal fixed two calls up is still a literal."""
    reached: dict = {}
    frontier = [(method, None)]
    while frontier:
        current, bindings = frontier.pop()
        for callee, cb in wrapped_methods(service, current).items():
            if callee in reached or callee == method:
                continue
            composed = cb if bindings is None else _through(bindings, cb)
            reached[callee] = composed
            frontier.append((callee, composed))
    return reached


def _through(outer: dict, inner: dict) -> dict:
    """Compose bindings: *inner* binds a callee's parameters in terms of the
    caller's; *outer* binds the caller's. A caller parameter *outer* leaves
    unbound is the caller's default."""
    return {p: (outer.get(b[1], ("default",)) if b[0] == "param" else b)
            for p, b in inner.items()}


def _consistent(chain: dict, fixed: dict) -> bool:
    """False only when the route and the chain pin the SAME parameter to
    DIFFERENT literals — or, for a chain that pins it to one of several
    literals (``("any", {...})``, the insurance trigger's "weather" or
    "custom"), to none of them. Anything less than that — a default, a
    variable, a parameter the caller chooses — cannot exclude: that direction
    would be a silent grant."""
    for p, b in fixed.items():
        if b[0] != "const":
            continue
        c = chain.get(p, ("other",))
        if (c[0] == "const" and c[1] != b[1]) or (c[0] == "any" and b[1] not in c[1]):
            return False
    return True


def _lift(chain: dict, fixed: dict) -> dict:
    """The route's literals as constraints on a WRAPPER's own parameters:
    *chain* binds the routed method's parameters in terms of the wrapper's, so
    a routed parameter the route pins and the wrapper passes through becomes a
    pin on the wrapper's parameter of that name. One the wrapper fixes itself,
    or leaves to a default, carries nothing further."""
    return {chain[p][1]: b for p, b in fixed.items()
            if b[0] == "const" and chain.get(p, ("other",))[0] == "param"}


_CROSS: dict = {}


def _live_registry():
    """A registry on an empty config: the cross-service walk resolves
    ``self.part`` through the REAL component objects, as the write census in
    tests/test_capability_catalog_truth.py does."""
    if "registry" not in _CROSS:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from runtime.blockchain.services import registry as _registry

        _CROSS["registry"] = _registry.ServiceRegistry({})
    return _CROSS["registry"]


def _service_of_class() -> dict:
    """registry class name -> service name (the first name, when two share one)."""
    from runtime.blockchain.services import registry as _registry

    out: dict = {}
    for name, (_module, cls) in _registry._SERVICE_MAP.items():
        out.setdefault(cls, name)
    return out


def _walk(owner, fn, seen, depth=0) -> list:
    """Every function *fn* reaches on *owner* through ``self.x(...)`` and
    ``self.part.x(...)`` calls, itself first, as ``(tree, module)`` pairs."""
    import ast as _ast
    import inspect as _inspect
    import textwrap as _textwrap

    code = getattr(fn, "__code__", None)
    if code is None or "site-packages" in code.co_filename or depth > 8:
        return []
    key = (id(owner), code.co_filename, code.co_firstlineno)
    if key in seen:
        return []
    seen.add(key)
    try:
        tree = _ast.parse(_textwrap.dedent(_inspect.getsource(fn)))
    except (OSError, TypeError):
        return []
    out = [(tree, _inspect.getmodule(fn))]
    for node in _ast.walk(tree):
        if not (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)):
            continue
        receiver = node.func.value
        if isinstance(receiver, _ast.Name) and receiver.id == "self":
            out += _walk(owner, getattr(type(owner), node.func.attr, None), seen, depth + 1)
        elif (isinstance(receiver, _ast.Attribute) and isinstance(receiver.value, _ast.Name)
              and receiver.value.id == "self"):
            part = getattr(owner, receiver.attr, None)
            if part is not None:
                out += _walk(part, getattr(type(part), node.func.attr, None), seen, depth + 1)
    return out


def cross_service_runs(service: str, method: str) -> dict:
    """``{(other service, public method): bindings}`` — every operation of
    ANOTHER registry service that *method* of *service* performs on an instance
    it builds itself. The third direction: no ``self.x(...)`` joins two
    services, so neither wrapper rule can see it.

    cross_border.get_quote asks its conversion component for a rate, and the
    component does ``OracleGateway(self._config).request("price_feed",
    {"pair": ...})`` — the call GET /api/v1/oracle/price/{pair} makes, which
    answers an anonymous caller 401. Measured at c5f2de4: an anonymous chat ran
    get_payment_quote and the service performed that read for the pair the
    caller named.

    The walk follows ``self.x(...)`` and ``self.part.x(...)`` through the real
    component objects, the way the write census does. Over everything reached:
    a call ``Cls(...)`` whose name is the class the registry maps to another
    service, and resolves to it (in the module, or imported inside the body),
    BUILDS that service; a call ``x.m(...)`` on any receiver but ``self``, with
    ``m`` a public method of a built service, PERFORMS (that service, m), with
    the literals the call fixes on m's parameters and ``("other",)`` for the
    rest, so only a different literal can exclude. The union over the closure
    is coarse on purpose: building the service in one helper and calling the
    method in another still joins, which errs toward the visible refusal.
    """
    import ast as _ast

    key = (service, method)
    if key in _CROSS:
        return _CROSS[key]
    by_class = _service_of_class()
    try:
        owner = _live_registry().get(service)
    except Exception as exc:
        raise SystemExit(f"cross_service_runs: {service} did not construct on an empty "
                         f"config ({exc}); the cross-service rule cannot walk it")
    built: set = set()
    calls: list = []
    for tree, module in _walk(owner, getattr(type(owner), method, None), set()):
        imported = {alias.asname or alias.name for node in _ast.walk(tree)
                    if isinstance(node, _ast.ImportFrom)
                    and (node.module or "").startswith("runtime.blockchain.services")
                    for alias in node.names}
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Call):
                continue
            if isinstance(node.func, _ast.Name) and node.func.id in by_class:
                other = by_class[node.func.id]
                if other != service and (node.func.id in imported or getattr(
                        module, node.func.id, None) is _service_class(other)):
                    built.add(other)
            elif isinstance(node.func, _ast.Attribute) and not (
                    isinstance(node.func.value, _ast.Name) and node.func.value.id == "self"):
                calls.append(node)
    out: dict = {}
    for other in sorted(built):
        cls = _service_class(other)
        public = set(_public_methods(other))
        for call in calls:
            name = call.func.attr
            fdef = _function_def(cls, name) if name in public else None
            if fdef is None:
                continue
            bindings = _literal_bindings(fdef, call)
            prev = out.get((other, name))
            # The same method called twice: a parameter pinned to different
            # literals on the two calls keeps the SET (the trigger manager's
            # "weather" and "custom" are still neither "price_feed"); one not
            # pinned on either call is the caller's.
            out[(other, name)] = bindings if prev is None else {
                p: _either(prev.get(p, ("other",)), bindings.get(p, ("other",)))
                for p in set(prev) | set(bindings)}
    _CROSS[key] = out
    return out


def _either(a: tuple, b: tuple) -> tuple:
    """The binding of a parameter that is *a* on one call and *b* on another."""
    if a[0] == "other" or b[0] == "other":
        return ("other",)
    literals = (set(a[1]) if a[0] == "any" else {a[1]}) | (set(b[1]) if b[0] == "any" else {b[1]})
    return ("const", next(iter(literals))) if len(literals) == 1 else ("any", frozenset(literals))


def _literal_bindings(callee_fdef, call) -> dict:
    """How *call* binds the callee's parameters: ``("const", v)`` for a literal
    and ``("other",)`` for anything else. A caller's own parameters are not
    composed across a service boundary; a value the caller chooses cannot
    exclude."""
    import ast as _ast

    positional, kwonly, _required, _var = _signature(callee_fdef)

    def binding(node):
        return ("const", node.value) if isinstance(node, _ast.Constant) else ("other",)

    out = {}
    for i, arg in enumerate(call.args):
        if not isinstance(arg, _ast.Starred) and i < len(positional):
            out[positional[i]] = binding(arg)
    for kw in call.keywords:
        if kw.arg is not None and (kw.arg in positional or kw.arg in kwonly):
            out[kw.arg] = binding(kw.value)
    return out


def cross_service_runners(service: str, method: str) -> list:
    """``[(other service, public method, bindings)]``: every public method of
    every registry service that performs (*service*, *method*) across the
    service boundary. Indexed once over every service's public methods."""
    if "index" not in _CROSS:
        from runtime.blockchain.services import registry as _registry

        index: dict = {}
        for other in sorted(_registry._SERVICE_MAP):
            for name in _public_methods(other):
                for target, bindings in cross_service_runs(other, name).items():
                    index.setdefault(target, []).append((other, name, bindings))
        _CROSS["index"] = index
    return _CROSS["index"].get((service, method), [])


# Two public READS the wrapper rules cannot relate — neither hands its arguments
# to the other, so no chain joins them — that read the same store, one of which
# backs a route the auth wall answers an anonymous caller 401. Whether they are
# the same operation is the owner's call; until it is made they are held
# refused to an ANONYMOUS caller under the routed sibling's route, the direction
# the module docstring says to err in. A session keeps what its routes grant it:
# /api/v1/governance/daos/{daoId}/proposals is app-called, and
# /api/v1/supply-chain/verify is operator-only only because the app never calls
# it, which is not a decision about verify_product. Each entry names the store
# both methods read; tests/test_capability_catalog_truth.py pins that both still
# do and that the derivation still cannot see it, so a stale entry fails loudly.
SAME_STORE_AS_ROUTED: dict = {
    ("governance", "list_proposals"): (
        ("governance", "list_proposals_detailed"), "_proposals",
        "both iterate self._proposals and apply the same active->expired transition"),
    ("supply_chain", "verify"): (
        ("supply_chain", "verify_authenticity"), "_provenance",
        "both run _verify_chain_integrity over self._provenance[product_id]"),
}


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
    return _refused_by(lambda route: (route.rstrip("/") or "/") in allowed)


def _refused_by(reachable) -> dict:
    """``"service.method"`` -> the first route (sorted) that runs it and that
    *reachable* rejects. A route that names the pair LITERALLY is its own route
    and wins the label over one that only reaches it through a wrapper, so the
    refusal message names /api/v1/realestate/purchase for execute_purchase, not
    the property read it performs on the way."""
    live_route_pairs()
    literal = _LIVE["literal"]
    out: dict = {}
    own: set = set()
    for route, pairs in sorted(live_route_pairs().items()):
        if reachable(route):
            continue
        for service, method in sorted(pairs):
            key = f"{service}.{method}"
            if (service, method) in literal.get(route, ()):
                if key not in own:
                    own.add(key)
                    out[key] = route
            else:
                out.setdefault(key, route)
    return out


def anonymous_refused_pairs() -> dict:
    """``"service.method"`` -> a route whose handler runs it and that the auth
    wall does not let a caller with NO credential reach.

    The chat surfaces are public paths: an anonymous caller reaches Trinity, and
    through her dispatching tools the same ServiceDispatcher. The session set
    above models only the operator tier, so an anonymous chat ran operations
    whose own route answers it 401. Public is read from the real server's
    ``_public_paths`` — the set the wall itself consults. Same tie-break: a pair
    behind ANY non-public route is refused. The SAME_STORE_AS_ROUTED reads join
    under their routed sibling's route; an entry the derivation now sees, or
    whose sibling is no longer refused, stops the generator.
    """
    server, _app = _live_server()
    public = set(server._public_paths)
    out = _refused_by(lambda route: route in public)
    for (service, method), ((_s, sibling), _store, _why) in SAME_STORE_AS_ROUTED.items():
        key, routed = f"{service}.{method}", f"{_s}.{sibling}"
        if key in out:
            raise SystemExit(f"SAME_STORE_AS_ROUTED: {key} is derived now — drop the entry")
        if routed not in out:
            raise SystemExit(f"SAME_STORE_AS_ROUTED: {routed} is not behind a non-public "
                             f"route — the entry for {key} is stale")
        out[key] = out[routed]
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
        "# Of those, the reads refused by DECISION rather than derivation: a public read",
        "# no wrapper chain joins to its routed sibling, held refused to an anonymous",
        "# caller because both read the named store, until a ruling on it is written.",
        "# A session is not refused these. Each: pair -> (routed sibling, shared store).",
        "ANONYMOUS_REFUSED_BY_DECISION: dict[str, tuple[str, str]] = {",
    ]
    for (service, method), ((s2, sibling), store, why) in sorted(SAME_STORE_AS_ROUTED.items()):
        lines += [f"    # {why}",
                  f'    "{service}.{method}": ("{s2}.{sibling}", "{store}"),']
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
          f"to an anonymous caller {len(anonymous)} ({len(SAME_STORE_AS_ROUTED)} by decision) "
          f"+ every unrouted state change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
