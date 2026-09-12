"""T5 / EA-1 — ``POST /api/v1/capabilities/{id}/invoke`` behind the gate.

Measured at the pin (register entry::EA-1): the ``/api/v1/*`` funnel
(``ServiceRoutes._call``) consults the Morpheus gate before every service
method, but the capability-invoke route reached the SAME dispatcher through
``CapabilityRegistry.invoke`` without it — ``settle_auction`` and every other
catalog write were reachable ungated there.

Driven through aiohttp's test client with the gate doubled at the public seam
(``runtime.security.get_morpheus_security``): a blocking gate answers the
generic denial before the dispatcher runs; an allowing one lets the invoke
proceed; the label the gate sees is the capability's ACTION_MAP verb.
"""

from __future__ import annotations

import sys
import tempfile

import pytest

sys.path.insert(0, "tests")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from gateway.server import GatewayServer  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

CAPABILITY = "settle_auction"


def _server() -> GatewayServer:
    scratch = tempfile.mkdtemp(prefix="opnmatrx-t5-")
    config = {**SWEEP_CONFIG, "memory_dir": scratch,
              "database": {**SWEEP_CONFIG.get("database", {}), "path": f"{scratch}/t5.db"}}
    return GatewayServer(config)


class _Gate:
    def __init__(self, allow: bool):
        self.allow = allow
        self.seen = []

    async def evaluate(self, action, context):
        self.seen.append((action, context))
        return {"allow": self.allow, "would_block": not self.allow, "route": "test", "reason": "test"}


@pytest.fixture
def invoked(monkeypatch):
    """Record every dispatcher-bound invoke instead of running it."""
    calls = []

    async def fake_invoke(self, capability_id, params=None, *, caller_identity=""):
        calls.append((capability_id, params, caller_identity))
        return {"status": "ok", "capability_id": capability_id}

    from runtime.capabilities.registry import CapabilityRegistry
    monkeypatch.setattr(CapabilityRegistry, "invoke", fake_invoke)
    return calls


async def test_a_blocking_gate_stops_the_invoke_before_the_dispatcher(monkeypatch, invoked):
    gate = _Gate(allow=False)
    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda: gate)
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post(f"/api/v1/capabilities/{CAPABILITY}/invoke",
                                 json={"params": {"auction_id": "0xTEST_A"}})
        assert resp.status == 403, await resp.text()
        body = await resp.json()
        assert "error" in body and "test" not in body["error"], "the internal reason must not leak"
    assert invoked == [], "the dispatcher ran despite the gate's deny"
    (action, _context), = gate.seen
    assert action["action_type"] == CAPABILITY
    assert action["parameters"] == {"auction_id": "0xTEST_A"}


async def test_an_allowing_gate_lets_the_invoke_proceed(monkeypatch, invoked):
    gate = _Gate(allow=True)
    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda: gate)
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post(f"/api/v1/capabilities/{CAPABILITY}/invoke", json={"params": {}})
        assert resp.status == 200, await resp.text()
    assert len(gate.seen) == 1
    assert [c[0] for c in invoked] == [CAPABILITY]


async def test_the_gate_sees_the_catalog_verb_not_the_route(monkeypatch, invoked):
    """A capability whose id and ACTION_MAP verb differ: the verb is the label."""
    from runtime.capabilities import catalog
    differing = next((c for c in catalog.CAPABILITIES if c.get("action") and c["action"] != c["id"]), None)
    if differing is None:
        pytest.skip("every catalog id equals its action verb")
    gate = _Gate(allow=False)
    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda: gate)
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post(f"/api/v1/capabilities/{differing['id']}/invoke", json={"params": {}})
        assert resp.status == 403
    assert gate.seen[0][0]["action_type"] == differing["action"]


async def test_an_unknown_capability_is_still_answered_by_the_registry(monkeypatch):
    """The gate runs on the id when there is no descriptor; the registry's
    unknown_capability answer is unchanged for an allowing gate."""
    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda: _Gate(allow=True))
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post("/api/v1/capabilities/no_such_capability/invoke", json={"params": {}})
        assert resp.status == 400
        assert (await resp.json()).get("error") == "unknown_capability"
