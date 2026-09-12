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
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_call" and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self" and len(node.args) >= 2
                    and all(isinstance(a, ast.Constant) and isinstance(a.value, str)
                            for a in node.args[:2])):
                pairs[(node.args[0].value, node.args[1].value)].add(route.resource.canonical)
                break
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
