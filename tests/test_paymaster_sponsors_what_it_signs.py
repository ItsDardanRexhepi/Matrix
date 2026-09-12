"""§EE — the sponsorship allowlist decides on what is signed, not on a label.

THE DEFECT. `/api/v1/paymaster/sign` read `action_type` out of the request body,
defaulted it to "transfer" when absent, and checked THAT against
`paymaster.policy.allowed_actions`. `call_data` — the bytes the paymaster digest
actually commits to, and therefore the only thing the signature sponsors —
entered the handler only as digest input. So the one sponsorship policy the
route enforced keyed on prose the caller writes about its own request:

    allowed_actions = ["transfer"]
    body = {"action_type": "transfer", "call_data": <mint an NFT>}   -> 200, signed
    body = {                           "call_data": <anything at all>} -> 200, signed

The MTRX client hardcodes "transfer" for every send, so the label was never
information even from the honest caller.

Each test below drives the real route and reads the real status. The first
three failed against the label-keyed handler; they are listed in both
directions, because a check that only ever denies could still be a label check
with a stricter default.
"""

from __future__ import annotations

import pytest

pytest.importorskip("eth_account")
pytest.importorskip("eth_abi")

from eth_abi import encode
from eth_utils import keccak

from tests.test_gateway import _build_mock_server

SIGNER_KEY = "0x" + hex(0xA11CE)[2:].rjust(64, "0")
PAYMASTER = "0x00000000000000000000000000000000caFe0001"
FACTORY = "0x62a31367C97A5fB3E36839fbB64268F3De4fC943"
RECIPIENT = "0x000000000000000000000000000000000000bEEF"
TOKEN = "0x0000000000000000000000000000000000001234"
NFT = "0x0000000000000000000000000000000000005678"


def _sel(sig: str) -> bytes:
    return keccak(text=sig)[:4]


def _execute(dest: str, value: int, inner: bytes) -> str:
    return "0x" + (_sel("execute(address,uint256,bytes)")
                   + encode(["address", "uint256", "bytes"], [dest, value, inner])).hex()


def _execute_batch(dests: list, inners: list) -> str:
    return "0x" + (_sel("executeBatch(address[],bytes[])")
                   + encode(["address[]", "bytes[]"], [dests, inners])).hex()


def _erc20_transfer(to: str, amount: int) -> bytes:
    return _sel("transfer(address,uint256)") + encode(["address", "uint256"], [to, amount])


def _nft_mint(to: str) -> bytes:
    return _sel("mint(address,string,uint96)") + encode(
        ["address", "string", "uint96"], [to, "ipfs://x", 500])


def _config(tmp_path, policy=None, account_factory=None):
    block = {"address": PAYMASTER, "signer_key": SIGNER_KEY}
    if policy is not None:
        block["policy"] = policy
    if account_factory is not None:
        block["account_factory"] = account_factory
    return {
        "platform": "0pnMatrx", "memory_dir": str(tmp_path / "m"),
        "workspace": str(tmp_path), "timezone": "UTC",
        "model": {"provider": "ollama", "providers": {}},
        "agents": {"neo": {"enabled": True}},
        "gateway": {"api_key": "", "rate_limit_rpm": 60, "rate_limit_burst": 10},
        "security": {}, "blockchain": {"chain_id": 84532, "paymaster": block},
        "database": {"path": str(tmp_path / "db" / "0pnmatrx.db")},
    }


async def _client(aiohttp_client, tmp_path, **kw):
    server = _build_mock_server(_config(tmp_path, **kw))
    server._app_attest = None
    server._security_backend = "noop"
    return await aiohttp_client(server.create_app())


def _body(call_data: str, *, init_code: str = "", **extra) -> dict:
    body = {
        "sender": "0x000000000000000000000000000000000000dEaD", "nonce": 7,
        "init_code": init_code, "call_data": call_data,
        "call_gas_limit": 100000, "verification_gas_limit": 200000,
        "pre_verification_gas": 21000, "max_fee_per_gas": 1000000000,
        "max_priority_fee_per_gas": 1000000000, "chain_id": 84532,
        "valid_until": 2000000000, "valid_after": 1000000000,
    }
    body.update(extra)
    return body


TRANSFER_ONLY = {"allowed_actions": ["transfer"]}


# ── the label no longer decides, in either direction ─────────────────────

@pytest.mark.asyncio
async def test_a_mint_declared_as_a_transfer_is_not_sponsored(aiohttp_client, tmp_path):
    """The attack the finding names: say "transfer", sign something else."""
    client = await _client(aiohttp_client, tmp_path, policy=TRANSFER_ONLY)
    r = await client.post("/api/v1/paymaster/sign", json=_body(
        _execute(NFT, 0, _nft_mint(RECIPIENT)), action_type="transfer"))
    assert r.status == 403, (
        f"{r.status}: the platform sponsored an NFT mint because the body called "
        f"it a transfer — the allowlist is still keyed on the caller's label")
    payload = await r.json()
    assert payload["code"] == "action_not_allowed"
    assert payload["policy"]["action"] == "mint_nft", payload


@pytest.mark.asyncio
async def test_omitting_the_label_no_longer_defaults_to_allowed(aiohttp_client, tmp_path):
    """The default: no action_type at all used to read as "transfer"."""
    client = await _client(aiohttp_client, tmp_path, policy=TRANSFER_ONLY)
    r = await client.post("/api/v1/paymaster/sign",
                          json=_body(_execute(TOKEN, 0, _sel("burn(uint256)")
                                              + encode(["uint256"], [1]))))
    assert r.status == 403, await r.text()


@pytest.mark.asyncio
async def test_a_real_transfer_mislabelled_is_still_sponsored(aiohttp_client, tmp_path):
    """The other direction. A check that merely got stricter about labels would
    deny this; one that reads the call data sees a native value transfer."""
    client = await _client(aiohttp_client, tmp_path, policy=TRANSFER_ONLY)
    r = await client.post("/api/v1/paymaster/sign", json=_body(
        _execute(RECIPIENT, 10**15, b""), action_type="mint_nft"))
    assert r.status == 200, await r.text()
    assert (await r.json())["paymasterAndData"].startswith("0x")


@pytest.mark.asyncio
async def test_an_erc20_transfer_is_a_transfer(aiohttp_client, tmp_path):
    client = await _client(aiohttp_client, tmp_path, policy=TRANSFER_ONLY)
    r = await client.post("/api/v1/paymaster/sign", json=_body(
        _execute(TOKEN, 0, _erc20_transfer(RECIPIENT, 5))))
    assert r.status == 200, await r.text()


# ── sibling axes of the same class ───────────────────────────────────────

@pytest.mark.asyncio
async def test_a_batch_is_sponsored_only_if_every_call_in_it_is_allowed(aiohttp_client,
                                                                         tmp_path):
    """One allowed call must not carry a disallowed one through."""
    client = await _client(aiohttp_client, tmp_path, policy=TRANSFER_ONLY)
    mixed = _execute_batch([TOKEN, NFT],
                           [_erc20_transfer(RECIPIENT, 5), _nft_mint(RECIPIENT)])
    r = await client.post("/api/v1/paymaster/sign", json=_body(mixed))
    assert r.status == 403, await r.text()

    clean = _execute_batch([TOKEN, TOKEN],
                           [_erc20_transfer(RECIPIENT, 5), _erc20_transfer(RECIPIENT, 6)])
    r = await client.post("/api/v1/paymaster/sign", json=_body(clean))
    assert r.status == 200, await r.text()


@pytest.mark.asyncio
async def test_undecodable_call_data_is_not_sponsored_under_an_allowlist(aiohttp_client,
                                                                          tmp_path):
    client = await _client(aiohttp_client, tmp_path, policy=TRANSFER_ONLY)
    r = await client.post("/api/v1/paymaster/sign",
                          json=_body("0x010203", action_type="transfer"))
    assert r.status == 403, await r.text()


@pytest.mark.asyncio
async def test_init_code_through_an_unknown_factory_is_not_sponsored(aiohttp_client,
                                                                      tmp_path):
    """initCode is sponsored too: the EntryPoint runs it on the paymaster's gas.
    A transfer riding on a deployment through someone else's factory is not
    only a transfer."""
    client = await _client(aiohttp_client, tmp_path, policy=TRANSFER_ONLY,
                           account_factory=FACTORY)
    call = _execute(RECIPIENT, 10**15, b"")
    rogue = "0x" + "11" * 20 + "5fbfb9cf" + "00" * 64
    r = await client.post("/api/v1/paymaster/sign", json=_body(call, init_code=rogue))
    assert r.status == 403, await r.text()

    ours = "0x" + FACTORY[2:].lower() + "5fbfb9cf" + "00" * 64
    r = await client.post("/api/v1/paymaster/sign", json=_body(call, init_code=ours))
    assert r.status == 200, await r.text()


# ── the rollback posture: no allowlist, no new denial ────────────────────

@pytest.mark.asyncio
async def test_no_allowlist_configured_signs_exactly_as_before(aiohttp_client, tmp_path):
    client = await _client(aiohttp_client, tmp_path)
    for call_data in ("0x010203", _execute(NFT, 0, _nft_mint(RECIPIENT)), ""):
        r = await client.post("/api/v1/paymaster/sign", json=_body(
            call_data, init_code="0x" + "11" * 24))
        assert r.status == 200, (call_data, await r.text())


@pytest.mark.asyncio
async def test_malformed_call_data_hex_is_still_a_400(aiohttp_client, tmp_path):
    """Caller input that is not hex at all is a bad request with or without a
    policy — the classification must not turn it into a policy denial."""
    for policy in (None, TRANSFER_ONLY):
        client = await _client(aiohttp_client, tmp_path, policy=policy)
        r = await client.post("/api/v1/paymaster/sign", json=_body("0xnothex"))
        assert r.status == 400, (policy, await r.text())


# ── the classifier, directly ─────────────────────────────────────────────

def test_the_classifier_reads_the_bytes_not_a_declaration():
    from runtime.blockchain.sponsorship import classify_user_operation

    assert classify_user_operation(bytes.fromhex(_execute(RECIPIENT, 1, b"")[2:])) == ["transfer"]
    assert classify_user_operation(
        bytes.fromhex(_execute(TOKEN, 0, _sel("swap(uint256,address,uint256)")
                               + encode(["uint256", "address", "uint256"],
                                        [1, TOKEN, 5]))[2:])) == ["swap"]
    # An unnamed inner selector is reported as itself, so an operator can
    # allowlist one exact function rather than a category.
    burn = _sel("burn(uint256)")
    assert classify_user_operation(
        bytes.fromhex(_execute(TOKEN, 0, burn + encode(["uint256"], [1]))[2:])
    ) == ["call:0x" + burn.hex()]
    # A zero-value call with no data moves nothing; it is not a transfer.
    assert classify_user_operation(bytes.fromhex(_execute(RECIPIENT, 0, b"")[2:])) != ["transfer"]
    # Not an account call at all.
    assert classify_user_operation(b"\x01\x02\x03") == ["unrecognized_call_data"]
    assert classify_user_operation(b"") == ["empty_call_data"]
