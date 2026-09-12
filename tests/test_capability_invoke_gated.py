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


# ── the allowlist is about OPERATIONS, not URLs ───────────────────────────────

async def test_a_session_cannot_reach_a_refused_route_through_a_capability(invoked):
    """`/api/v1/capabilities/{id}/invoke` is a dispatcher: allowlisting the URL
    is not allowlisting the operation. A session gets 403 on
    /api/v1/nft/collection/create and must not get 200 on the capability that
    calls the identical nft_services.create_collection."""
    import time

    from gateway.session_routes import CAPABILITIES_OFF_ALLOWLIST
    assert CAPABILITIES_OFF_ALLOWLIST, "the escape set must be derived, not empty"

    server = GatewayServer({**SWEEP_CONFIG, "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": "k"}})
    async with TestClient(TestServer(server.create_app())) as client:
        now = time.time()
        await server.wallet_sessions.add(token="0xTEST_SESSION", address="apple:sub",
                                         issued_at=now, expires_at=now + 3600)
        for cap_id in CAPABILITIES_OFF_ALLOWLIST:
            resp = await client.post(f"/api/v1/capabilities/{cap_id}/invoke",
                                     headers={"Authorization": "Bearer 0xTEST_SESSION"},
                                     json={"params": {}})
            assert resp.status == 403, (cap_id, resp.status)
    assert invoked == [], "no escaping capability reached the dispatcher"


async def test_the_operator_key_still_invokes_them(monkeypatch, invoked):
    from gateway.session_routes import CAPABILITIES_OFF_ALLOWLIST
    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda: _Gate(allow=True))
    server = GatewayServer({**SWEEP_CONFIG, "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": "k"}})
    async with TestClient(TestServer(server.create_app())) as client:
        cap_id = sorted(CAPABILITIES_OFF_ALLOWLIST)[0]
        resp = await client.post(f"/api/v1/capabilities/{cap_id}/invoke",
                                 headers={"Authorization": "Bearer k"}, json={"params": {}})
        assert resp.status == 200, await resp.text()
    assert [c[0] for c in invoked] == [cap_id]


def test_the_escape_set_is_current():
    """Regenerate and compare — a new capability whose route is off the allowlist
    must land in the set rather than silently becoming reachable."""
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, "scripts/generate_session_routes.py", "--check"],
                       cwd=root, capture_output=True, text=True, timeout=120)
    if "client not found" in (r.stderr or ""):
        import pytest
        pytest.skip("MTRX checkout not present (CI): the committed module is used as is")
    assert r.returncode == 0, r.stderr or r.stdout
