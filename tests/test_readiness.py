"""RUN-7 — /health is liveness, /ready is readiness, and they must differ.

The audit described `/ready` as answering 200 when it should not. Reading the
code found something worse: **there was no readiness endpoint at all.** There
was only `/health`, which returns a literal `"status": "ok"` regardless of what
its own `model_health` probe says — and every Kubernetes probe (liveness,
readiness AND startup) pointed at it, along with the Compose healthcheck that
gates Caddy's `depends_on: condition: service_healthy`.

The consequence: readiness could never fail, so an instance with zero reachable
model providers stayed in rotation and took traffic it could not serve. The
evidence was already in the response body; nothing consulted it.

These tests pin the split in both directions — that `/ready` goes red on each
condition, AND that `/health` stays green on them, because a liveness probe that
fails on a provider outage causes restart loops that fix nothing.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "tests")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from gateway.server import GatewayServer  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402


async def _get(server: GatewayServer, path: str):
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.get(path, headers={"Authorization": "Bearer k"})
        return resp.status, await resp.json()


# ── the endpoint exists at all ─────────────────────────────────────────────

async def test_ready_endpoint_exists():
    """It did not. Every probe shared the always-ok liveness route."""
    server = GatewayServer(SWEEP_CONFIG)
    status, _ = await _get(server, "/ready")
    assert status in (200, 503), f"/ready is not routed (got {status})"


# ── condition 1: no reachable model provider ───────────────────────────────

async def test_ready_is_503_when_no_model_provider_is_reachable():
    """The condition that could not previously be expressed."""
    server = GatewayServer(SWEEP_CONFIG)
    server.react_loop.router.health_check = AsyncMock(
        return_value={"ollama": False, "anthropic": False}
    )
    status, body = await _get(server, "/ready")

    assert status == 503, f"ready with zero providers: {body}"
    assert body["status"] == "not_ready"
    assert body["checks"]["model_providers"]["ok"] is False
    assert body["checks"]["model_providers"]["reachable"] == []


async def test_ready_is_200_when_at_least_one_provider_is_reachable():
    """Fail-closed must not mean fail-always: one working provider is enough
    to serve, and a fallback chain exists precisely for this."""
    server = GatewayServer(SWEEP_CONFIG)
    server.react_loop.router.health_check = AsyncMock(
        return_value={"ollama": False, "anthropic": True}
    )
    status, body = await _get(server, "/ready")

    assert status == 200, f"ready refused with a working provider: {body}"
    assert body["checks"]["model_providers"]["reachable"] == ["anthropic"]


# ── condition 2: no-op security backend in production ──────────────────────

async def test_ready_is_503_when_security_backend_is_noop_in_production(monkeypatch):
    """`noop` means morpheus_security failed to load and NOTHING is enforcing.

    That is a normal local state and an unacceptable production one, so it is
    fatal only under OPNMATRX_ENV=production.
    """
    monkeypatch.setenv("OPNMATRX_ENV", "production")
    server = GatewayServer(SWEEP_CONFIG)
    server.react_loop.router.health_check = AsyncMock(return_value={"ollama": True})
    server._security_backend = "noop"

    status, body = await _get(server, "/ready")

    assert status == 503, f"production + noop security was reported ready: {body}"
    assert body["checks"]["security_backend"]["ok"] is False
    assert body["checks"]["security_backend"]["production"] is True


async def test_noop_security_is_not_fatal_outside_production(monkeypatch):
    """The other direction — otherwise no developer could ever be ready."""
    monkeypatch.delenv("OPNMATRX_ENV", raising=False)
    server = GatewayServer(SWEEP_CONFIG)
    server.react_loop.router.health_check = AsyncMock(return_value={"ollama": True})
    server._security_backend = "noop"

    status, body = await _get(server, "/ready")

    assert status == 200, f"dev refused readiness for a dev-normal state: {body}"
    assert body["checks"]["security_backend"]["ok"] is True


async def test_real_security_backend_is_ready_in_production(monkeypatch):
    monkeypatch.setenv("OPNMATRX_ENV", "production")
    server = GatewayServer(SWEEP_CONFIG)
    server.react_loop.router.health_check = AsyncMock(return_value={"ollama": True})
    server._security_backend = "morpheus_security"

    status, body = await _get(server, "/ready")
    assert status == 200, body


# ── /health must NOT move ──────────────────────────────────────────────────

async def test_health_stays_200_when_providers_are_down():
    """Liveness answers "should I restart this process?".

    Restarting will not make an unreachable provider reachable, so a liveness
    probe that goes red on a provider outage produces a restart loop that fixes
    nothing and destroys in-flight work. This asserts the two endpoints
    genuinely disagree — which is the whole point of splitting them.
    """
    server = GatewayServer(SWEEP_CONFIG)
    server.react_loop.router.health_check = AsyncMock(return_value={"ollama": False})

    health_status, health_body = await _get(server, "/health")
    ready_status, _ = await _get(server, "/ready")

    assert health_status == 200, "liveness must not fail on a dependency outage"
    assert health_body["status"] == "ok"
    assert ready_status == 503
    assert health_status != ready_status, (
        "the endpoints answer identically — the split is decorative"
    )


# ── the deployment must actually consult it ────────────────────────────────

def test_deployment_probes_point_at_the_right_endpoints():
    """A correct /ready that nothing probes is worth nothing.

    This is the load-bearing half: the original defect was not a missing check,
    it was every probe pointing at the wrong route. Liveness and startup stay on
    /health (a provider outage is not a restart reason, and a startup probe tied
    to readiness could stop a pod ever coming up during a transient outage);
    readiness moves to /ready.
    """
    import pathlib

    import yaml

    root = pathlib.Path(__file__).resolve().parents[1]
    spec = yaml.safe_load((root / "k8s" / "deployment.yaml").read_text())
    containers = spec["spec"]["template"]["spec"]["containers"]
    probes = {}
    for c in containers:
        for kind in ("livenessProbe", "readinessProbe", "startupProbe"):
            if kind in c:
                probes[kind] = c[kind]["httpGet"]["path"]

    assert probes.get("readinessProbe") == "/ready", (
        f"readiness probes {probes.get('readinessProbe')} — the always-ok route"
    )
    assert probes.get("livenessProbe") == "/health", (
        "liveness must not depend on a downstream provider"
    )
    assert probes.get("startupProbe") == "/health", (
        "a startup probe on /ready could prevent a pod starting during an outage"
    )


def test_container_healthchecks_gate_on_readiness():
    """Compose's healthcheck gates `depends_on: service_healthy` — a routing
    decision — so it must ask /ready, not /health."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]

    compose = (root / "docker-compose.yml").read_text()
    assert "18790/ready" in compose, "compose healthcheck still probes /health"
    assert "18790/health" not in compose, "a /health healthcheck remains in compose"

    dockerfile = (root / "Dockerfile").read_text()
    assert "18790/ready" in dockerfile, "Dockerfile HEALTHCHECK still probes /health"
