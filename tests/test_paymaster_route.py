"""P4: /api/v1/paymaster/sign gateway route."""

import pytest

pytest.importorskip("eth_account")

from tests.test_gateway import _build_mock_server

SIGNER_KEY = "0x" + hex(0xA11CE)[2:].rjust(64, "0")
PAYMASTER = "0x00000000000000000000000000000000caFe0001"


def _config(tmp_path, paymaster=None, blockchain_paymaster=None, flat_key=None):
    cfg = {
        "platform": "0pnMatrx", "memory_dir": str(tmp_path / "m"),
        "workspace": str(tmp_path), "timezone": "UTC",
        "model": {"provider": "ollama", "providers": {}},
        "agents": {"neo": {"enabled": True}},
        "gateway": {"api_key": "", "rate_limit_rpm": 60, "rate_limit_burst": 10},
        "security": {}, "blockchain": {"chain_id": 84532},
    }
    if paymaster:
        cfg["paymaster"] = paymaster                       # top-level (legacy/test)
    if blockchain_paymaster:
        cfg["blockchain"]["paymaster"] = blockchain_paymaster   # documented location
    if flat_key:
        cfg["blockchain"]["paymaster_private_key"] = flat_key   # env-bridge shape
    return cfg


async def _client(aiohttp_client, tmp_path, **kw):
    server = _build_mock_server(_config(tmp_path, **kw))
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


# ── config-path reconciliation: the block is filled at the DOCUMENTED location ──
# (openmatrix.config.json.example + DEPLOYMENT_GUIDE put it at blockchain.paymaster;
#  the env-bridge lands the key at blockchain.paymaster_private_key). Before the fix
#  the reader looked only at top-level `paymaster`, so both of these 503'd.

@pytest.mark.asyncio
async def test_blockchain_paymaster_location_signs(aiohttp_client, tmp_path):
    client = await _client(aiohttp_client, tmp_path,
                           blockchain_paymaster={"address": PAYMASTER, "signer_key": SIGNER_KEY})
    r = await client.post("/api/v1/paymaster/sign", json=_BODY)
    assert r.status == 200, await r.text()
    raw = bytes.fromhex((await r.json())["paymasterAndData"][2:])
    assert len(raw) == 20 + 64 + 65


@pytest.mark.asyncio
async def test_flat_private_key_env_bridge_signs(aiohttp_client, tmp_path):
    # address from blockchain.paymaster; signer_key from the env-bridged flat key.
    client = await _client(aiohttp_client, tmp_path,
                           blockchain_paymaster={"address": PAYMASTER}, flat_key=SIGNER_KEY)
    r = await client.post("/api/v1/paymaster/sign", json=_BODY)
    assert r.status == 200, await r.text()


@pytest.mark.asyncio
async def test_blockchain_location_policy_still_enforced(aiohttp_client, tmp_path):
    # The policy gate must ride along when the block lives under blockchain.paymaster.
    client = await _client(aiohttp_client, tmp_path, blockchain_paymaster={
        "address": PAYMASTER, "signer_key": SIGNER_KEY,
        "policy": {"allowed_actions": ["transfer"]},
    })
    r = await client.post("/api/v1/paymaster/sign", json=dict(_BODY, action_type="mint_nft"))
    assert r.status == 403


def test_doctor_agrees_across_all_locations():
    from gateway.doctor import check_paymaster, READY, UNCONFIGURED
    assert check_paymaster({})[1] == UNCONFIGURED
    assert check_paymaster({"paymaster": {"signer_key": SIGNER_KEY}})[1] == READY
    assert check_paymaster({"blockchain": {"paymaster": {"signer_key": SIGNER_KEY}}})[1] == READY
    assert check_paymaster({"blockchain": {"paymaster_private_key": SIGNER_KEY}})[1] == READY


def test_resolver_hardening_and_no_mutation():
    from gateway.paymaster import paymaster_config
    # top-level signer_key wins; flat does not override it
    src = {"paymaster": {"signer_key": "TOP", "address": PAYMASTER},
           "blockchain": {"paymaster_private_key": "FLAT"}}
    assert paymaster_config(src)["signer_key"] == "TOP"
    # source config is never mutated by the flat-key fallback
    src2 = {"blockchain": {"paymaster": {"address": PAYMASTER},
                           "paymaster_private_key": "FLAT"}}
    out = paymaster_config(src2)
    assert out["signer_key"] == "FLAT"
    assert "signer_key" not in src2["blockchain"]["paymaster"]  # copy, not in-place
    # malformed non-dict shapes degrade to {} (honest 503), never crash
    assert paymaster_config({"blockchain": "oops"}) == {}
    assert paymaster_config({"paymaster": "oops"}) == {}
    assert paymaster_config(None) == {}
