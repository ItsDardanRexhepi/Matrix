"""P1-5: /api/v1/security/preflight — the send-path gate consult.

Under the noop backend the gate allows, so the route returns 200 {"allow": true}
(never 404). Once a real backend is installed a blocked decision surfaces as
403 {"error": ...}, which the iOS client maps to MTRXAPIError.securityBlocked.
"""

import pytest

from tests.test_gateway import _build_mock_server


def _config(tmp_path):
    return {
        "platform": "0pnMatrx",
        "memory_dir": str(tmp_path / "memory"),
        "workspace": str(tmp_path),
        "timezone": "UTC",
        "max_steps": 5,
        "model": {"provider": "ollama", "providers": {}},
        "agents": {"neo": {"enabled": True}},
        "gateway": {"api_key": "", "rate_limit_rpm": 60, "rate_limit_burst": 10},
        "security": {},
    }


@pytest.fixture
async def client(aiohttp_client, tmp_path):
    server = _build_mock_server(_config(tmp_path))
    server._app_attest = None
    server._security_backend = "noop"
    app = server.create_app()
    return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_preflight_allows_under_noop(client):
    resp = await client.post(
        "/api/v1/security/preflight",
        json={"to": "0xabc", "value_usd": "12.5", "chain_id": "84532",
              "action_type": "transfer"},
    )
    assert resp.status == 200  # never 404 — the deny path is now reachable
    body = await resp.json()
    assert body["allow"] is True
    assert body["mode"] == "observe"


@pytest.mark.asyncio
async def test_preflight_coerces_string_values(client):
    # value_usd/chain_id arrive as strings from the Swift client; must not 500.
    resp = await client.post(
        "/api/v1/security/preflight",
        json={"to": "0xabc", "value_usd": "not-a-number", "chain_id": ""},
    )
    assert resp.status == 200
