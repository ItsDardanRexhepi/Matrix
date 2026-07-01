"""P1-4c: gateway App Attest routes under the noop security backend.

Challenge -> 503 (unavailable); attest -> 200 with verified:false + reason, so
the iOS client's decode path always works. Once the private morpheus_security
backend is installed these bind to the real verifier.
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
async def client_noop_attest(aiohttp_client, tmp_path):
    server = _build_mock_server(_config(tmp_path))
    # Simulate the noop security backend (private package not installed).
    server._app_attest = None
    server._security_backend = "noop"
    app = server.create_app()
    return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_challenge_503_under_noop(client_noop_attest):
    resp = await client_noop_attest.get(
        "/security/appattest/challenge", params={"identity": "0xabc"})
    assert resp.status == 503
    body = await resp.json()
    assert "not installed" in body["error"]


@pytest.mark.asyncio
async def test_attest_returns_verified_false_under_noop(client_noop_attest):
    resp = await client_noop_attest.post(
        "/security/appattest/attest",
        json={"key_id": "k", "attestation_obj_b64": "AA==", "challenge": "abcd"},
    )
    assert resp.status == 200  # clean rejection, not a 4xx
    body = await resp.json()
    assert body["verified"] is False
    assert body["reason"] == "security backend not installed"


@pytest.mark.asyncio
async def test_attest_400_on_missing_fields(client_noop_attest):
    resp = await client_noop_attest.post(
        "/security/appattest/attest", json={"key_id": "k"})
    assert resp.status == 400
