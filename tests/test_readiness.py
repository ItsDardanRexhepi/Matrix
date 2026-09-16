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

# NEW-26 makes a production boot with no API key a refusal. Tests below that
# exercise PRODUCTION READINESS (not the auth wall) must therefore configure a
# key — otherwise they would fail on the wall before reaching the thing under
# test. The refusal itself is covered by
# test_production_refuses_to_start_with_authentication_disabled.
PROD_CONFIG = {**SWEEP_CONFIG, "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": "test-key"}}


def _with_live_security(monkeypatch):
    """Force SECURITY_BACKEND to the real value for construction.

    Without this, these tests are green ONLY when the private
    `morpheus_security` package happens to be importable. In a checkout without
    it — the documented normal state for dev and CI — H2's production guard
    fires during `GatewayServer.__init__` and the test never reaches the thing
    it means to exercise. That made the tests depend on an ambient condition
    they do not control, which is the same class of defect this engagement is
    about: a result that reflects the environment rather than the code.
    """
    monkeypatch.setattr("runtime.security.SECURITY_BACKEND", "morpheus_security",
                        raising=False)


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
    assert body["ready"] is False


async def test_ready_is_200_when_at_least_one_provider_is_reachable():
    """Fail-closed must not mean fail-always: one working provider is enough
    to serve, and a fallback chain exists precisely for this."""
    server = GatewayServer(SWEEP_CONFIG)
    server.react_loop.router.health_check = AsyncMock(
        return_value={"ollama": False, "anthropic": True}
    )
    status, body = await _get(server, "/ready")

    assert status == 200, f"ready refused with a working provider: {body}"
    assert body["ready"] is True


# ── condition 2: no-op security backend in production ──────────────────────

async def test_ready_is_503_when_security_backend_is_noop_in_production(monkeypatch):
    """`noop` means morpheus_security failed to load and NOTHING is enforcing.

    That is a normal local state and an unacceptable production one, so it is
    fatal only under MATRIX_ENV=production.
    """
    monkeypatch.setenv("MATRIX_ENV", "production")
    _with_live_security(monkeypatch)
    server = GatewayServer(PROD_CONFIG)
    server.react_loop.router.health_check = AsyncMock(return_value={"ollama": True})
    server._security_backend = "noop"

    status, body = await _get(server, "/ready")

    assert status == 503, f"production + noop security was reported ready: {body}"
    assert body["ready"] is False


async def test_noop_security_is_not_fatal_outside_production(monkeypatch):
    """The other direction — otherwise no developer could ever be ready."""
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    server = GatewayServer(SWEEP_CONFIG)
    server.react_loop.router.health_check = AsyncMock(return_value={"ollama": True})
    server._security_backend = "noop"

    status, body = await _get(server, "/ready")

    assert status == 200, f"dev refused readiness for a dev-normal state: {body}"
    assert body["ready"] is True


async def test_real_security_backend_is_ready_in_production(monkeypatch):
    monkeypatch.setenv("MATRIX_ENV", "production")
    _with_live_security(monkeypatch)
    server = GatewayServer(PROD_CONFIG)
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
    assert health_body["status"] == "ok"  # noqa: liveness keeps its own shape
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


# ── /ready must not leak posture (the critic finding against RUN-7 itself) ──

async def test_ready_body_carries_no_operator_detail(monkeypatch):
    """A readiness probe answers ready-or-not, never why.

    RUN-7's first version returned each check with its values. An adversarial
    review of that very fix caught the problem: `"backend": "noop"` tells the
    caller that NOTHING IS ENFORCING, and `"probed"` hands over the full
    model-provider inventory. That is a targeting signal wearing a health
    signal's clothes — and per NEW-26 the caller need not be authenticated.

    The detail is not destroyed; it is logged against the same ref, exactly as
    RUN-5 relocates error detail rather than deleting it.
    """
    import json as _json

    monkeypatch.setenv("MATRIX_ENV", "production")
    _with_live_security(monkeypatch)
    server = GatewayServer(PROD_CONFIG)
    server.react_loop.router.health_check = AsyncMock(
        return_value={"ollama": False, "anthropic": False}
    )
    server._security_backend = "noop"

    status, body = await _get(server, "/ready")
    assert status == 503

    rendered = _json.dumps(body)
    for forbidden in ("noop", "morpheus_security", "ollama", "anthropic",
                      "production", "backend", "probed", "reachable", "checks"):
        assert forbidden not in rendered, (
            f"/ready disclosed {forbidden!r} in {rendered}"
        )
    assert set(body) == {"ready", "ref"}, f"unexpected keys: {sorted(body)}"


async def test_ready_failure_still_gives_the_operator_a_handle():
    """Redaction that destroys the operator's ability to debug is not a win —
    the same correction RUN-5 needed when its ref was a placeholder."""
    server = GatewayServer(SWEEP_CONFIG)
    server.react_loop.router.health_check = AsyncMock(return_value={"ollama": False})

    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.get("/ready", headers={"Authorization": "Bearer k"})
        body = await resp.json()
        assert resp.status == 503
        assert body["ref"] == resp.headers.get("X-Request-ID"), (
            f"ref {body['ref']!r} does not correlate with the log line"
        )


# ── NEW-26: production must not boot with the credential wall down ─────────

def test_production_refuses_to_start_with_authentication_disabled(monkeypatch):
    """`auth_enabled = bool(api_key)`, and `_auth_middleware` opens with
    `if not self.auth_enabled: return await handler(request)` — it waves EVERY
    protected route through. The shipped matrix.config.json carries
    `"api_key": ""`, so an operator who copies the example and starts without
    MATRIX_API_KEY serves the whole surface anonymously, having chosen
    nothing. Same fail-open shape as H2, one layer up.
    """
    monkeypatch.setenv("MATRIX_ENV", "production")
    monkeypatch.delenv("MATRIX_API_KEY", raising=False)
    # Isolate NEW-26 from H2: with a noop backend, H2's guard would raise first
    # and this test would pass for the wrong reason.
    _with_live_security(monkeypatch)
    config = {**SWEEP_CONFIG, "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": ""}}

    # Match text only NEW-26 can produce. `match="Refusing to start"` passed
    # against pre-fix code because H2's security-backend guard raises first with
    # the same phrase — the test would have been green without the fix existing.
    with pytest.raises(RuntimeError, match="no gateway API key is configured"):
        GatewayServer(config)


def test_production_starts_when_a_key_is_configured(monkeypatch):
    monkeypatch.setenv("MATRIX_ENV", "production")
    _with_live_security(monkeypatch)
    config = {**SWEEP_CONFIG, "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": "k"}}
    server = GatewayServer(config)
    assert server.auth_enabled is True


def test_development_still_runs_open(monkeypatch):
    """Anonymous in dev is useful and intended; anonymous in production that
    nobody selected is the bug. Fail-closed must not become fail-always."""
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    monkeypatch.delenv("MATRIX_API_KEY", raising=False)
    config = {**SWEEP_CONFIG, "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": ""}}
    server = GatewayServer(config)
    assert server.auth_enabled is False


def test_the_shipped_example_config_still_has_no_key():
    """Deliberate non-fix, pinned so nobody 'helpfully' adds one.

    Putting a key in a public example config is its own vulnerability — a
    published credential — and would trade one hole for another. The example
    stays empty; production refuses to boot instead.
    """
    import json as _json
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    # The SHIPPED file is the .example; matrix.config.json is gitignored
    # (the wizard writes it), so reading that one passed only on a machine
    # that had run setup — and failed in every fresh clone and in CI.
    cfg = _json.loads((root / "matrix.config.json.example").read_text())
    assert not cfg.get("gateway", {}).get("api_key"), (
        "a credential was committed to the example config"
    )


def test_ready_is_reachable_without_credentials():
    """A kubelet probe carries no Authorization header.

    Found by RUN-7's own tests once NEW-26 forced a key into the production
    config: with auth enabled and /ready NOT public, every readiness probe would
    get 401 and no pod would ever become ready — the fix would have silently
    broken the deployment it was written to protect. /ready is therefore public,
    which is exactly why its body must disclose nothing.
    """
    server = GatewayServer(PROD_CONFIG)
    assert server.auth_enabled is True
    assert "/ready" in server._public_paths, (
        "/ready sits behind auth; probes cannot authenticate and the pod would "
        "never become ready"
    )


# ── T1.1 / T1.2: a security service that fails to construct must not be swallowed
#    in production, and H2's refusal must name the cause it refused for ──────────

def test_production_refuses_to_start_when_otp_services_fail_to_initialise(monkeypatch):
    """`OTPService(self.config)` is constructed inside `try/except Exception`
    with `self._otp = None` on failure. Morpheus's own production guard
    ("MATRIX_OTP_PEPPER is not set under production") raises there — and was
    swallowed: the boot continued, /security/phone/* answered 503 and owner OTP
    was silently unavailable. H2's principle on the OTP branch: in production,
    refuse, naming the cause. (Driven in the census: entry::OTP-PEPPER-SWALLOWED.)
    """
    monkeypatch.setenv("MATRIX_ENV", "production")
    _with_live_security(monkeypatch)

    def _pepper_missing(*_a, **_k):
        raise RuntimeError(
            "MATRIX_OTP_PEPPER is not set under production. A stable pepper is required."
        )
    monkeypatch.setattr("runtime.security.OTPService", _pepper_missing, raising=False)

    with pytest.raises(RuntimeError, match=r"OTP.*MATRIX_OTP_PEPPER|MATRIX_OTP_PEPPER.*OTP"):
        GatewayServer(PROD_CONFIG)


def test_development_runs_without_otp_when_its_service_fails_to_initialise(monkeypatch):
    """The other direction — a developer without the pepper still gets a gateway,
    with the OTP surface honestly unavailable (503), not a refusal."""
    monkeypatch.delenv("MATRIX_ENV", raising=False)

    def _pepper_missing(*_a, **_k):
        raise RuntimeError("MATRIX_OTP_PEPPER is not set under production.")
    monkeypatch.setattr("runtime.security.OTPService", _pepper_missing, raising=False)

    server = GatewayServer(SWEEP_CONFIG)
    assert server._otp is None and server._owner is None


def test_h2_refusal_names_the_cause_that_flipped_the_backend_to_noop(monkeypatch):
    """When the App Attest verifier's own production guard raises (for example
    "MATRIX_STATE_BACKEND=memory under production"), the gateway relabels the
    backend `noop` and H2 refuses — but its message said "morpheus_security is
    not installed or failed to load", naming the wrong cause at the loudest
    moment. The refusal is right; the message must carry the real reason.
    (Driven in the census: entry::DEPLOY-DRIVE.)
    """
    monkeypatch.setenv("MATRIX_ENV", "production")
    _with_live_security(monkeypatch)

    def _store_refused(*_a, **_k):
        raise RuntimeError(
            "MATRIX_STATE_BACKEND=memory under production. The in-memory store is "
            "single-node and loses state on restart. Set MATRIX_STATE_BACKEND=redis or sql."
        )
    monkeypatch.setattr("runtime.security.get_app_attest_verifier", _store_refused, raising=False)

    with pytest.raises(RuntimeError, match=r"MATRIX_STATE_BACKEND=memory"):
        GatewayServer(PROD_CONFIG)
