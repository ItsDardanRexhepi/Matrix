"""P4: /api/v1/paymaster/sign gateway route."""

import pytest

pytest.importorskip("eth_account")

from tests.test_gateway import _build_mock_server

SIGNER_KEY = "0x" + hex(0xA11CE)[2:].rjust(64, "0")
PAYMASTER = "0x00000000000000000000000000000000caFe0001"


def _config(tmp_path, paymaster=None):
    cfg = {
        "platform": "0pnMatrx", "memory_dir": str(tmp_path / "m"),
        "workspace": str(tmp_path), "timezone": "UTC",
        "model": {"provider": "ollama", "providers": {}},
        "agents": {"neo": {"enabled": True}},
        "gateway": {"api_key": "", "rate_limit_rpm": 60, "rate_limit_burst": 10},
        "security": {}, "blockchain": {"chain_id": 84532},
    }
    if paymaster:
        cfg["paymaster"] = paymaster
    return cfg


async def _client(aiohttp_client, tmp_path, paymaster=None):
    server = _build_mock_server(_config(tmp_path, paymaster))
    server._app_attest = None
    server._security_backend = "noop"
    return await aiohttp_client(server.create_app())


_BODY = {
    "sender": "0x000000000000000000000000000000000000dEaD", "nonce": 7,
    "init_code": "", "call_data": "0x010203",
    "call_gas_limit": 100000, "verification_gas_limit": 200000,
    "pre_verification_gas": 21000, "max_fee_per_gas": 1000000000,
    "max_priority_fee_per_gas": 1000000000, "chain_id": 84532,
    "valid_until": 2000000000, "valid_after": 1000000000, "action_type": "transfer",
}


@pytest.mark.asyncio
async def test_unconfigured_returns_503(aiohttp_client, tmp_path):
    client = await _client(aiohttp_client, tmp_path)  # no paymaster config
    r = await client.post("/api/v1/paymaster/sign", json=_BODY)
    assert r.status == 503


@pytest.mark.asyncio
async def test_configured_signs_valid_paymasterAndData(aiohttp_client, tmp_path):
    client = await _client(aiohttp_client, tmp_path,
                           paymaster={"address": PAYMASTER, "signer_key": SIGNER_KEY})
    r = await client.post("/api/v1/paymaster/sign", json=_BODY)
    assert r.status == 200
    pnd = (await r.json())["paymasterAndData"]
    raw = bytes.fromhex(pnd[2:])
    assert len(raw) == 20 + 64 + 65               # addr + timestamps + sig
    assert "0x" + raw[:20].hex() == PAYMASTER.lower()


@pytest.mark.asyncio
async def test_policy_denies_disallowed_action(aiohttp_client, tmp_path):
    client = await _client(aiohttp_client, tmp_path, paymaster={
        "address": PAYMASTER, "signer_key": SIGNER_KEY,
        "policy": {"allowed_actions": ["transfer"]},
    })
    body = dict(_BODY, action_type="mint_nft")
    r = await client.post("/api/v1/paymaster/sign", json=body)
    assert r.status == 403
