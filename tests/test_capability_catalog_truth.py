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


@functools.lru_cache(maxsize=1)
def _route_pairs():
    """(service, method) -> {canonical route} from the REAL app: its registered
    routes, and the `self._call(service, method, ...)` in each handler's own
    source — found on the AST, so a comment inside the call cannot hide it."""
    import ast
    import collections
    import inspect
    import tempfile
    import textwrap

    from gateway.server import GatewayServer

    scratch = tempfile.mkdtemp(prefix="opnmatrx-catalog-truth-")
    app = GatewayServer({"memory_dir": scratch,
                         "database": {"path": f"{scratch}/t.db"}}).create_app()
    pairs = collections.defaultdict(set)
    for route in app.router.routes():
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
            pairs[(head[0].value, head[1].value)].add(route.resource.canonical)
    return pairs


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
    scratch = tempfile.mkdtemp(prefix="opnmatrx-catalog-truth-")
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
                                           if r.getMessage().startswith("Session DENIED"))
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
