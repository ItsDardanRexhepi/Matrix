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
        "platform": "The Matrix", "memory_dir": str(tmp_path / "m"),
        "workspace": str(tmp_path), "timezone": "UTC",
        "model": {"provider": "ollama", "providers": {}},
        "agents": {"neo": {"enabled": True}},
        "gateway": {"api_key": "", "rate_limit_rpm": 60, "rate_limit_burst": 10},
        "security": {}, "blockchain": {"chain_id": 84532, "paymaster": block},
        "database": {"path": str(tmp_path / "db" / "the-matrix.db")},
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


# ── the classifier is bounded by the bytes it is given ───────────────────
#
# Round-1 review: classify_user_operation called eth_abi.decode on caller bytes,
# on every sign request, before any policy check and with no policy configured.
# ABI dynamic arrays let every bytes[] element point at ONE shared blob, and
# eth_abi copies that blob once per element — so a ~1 MiB request allocated
# gigabytes. These controls send exactly that payload.

def _word(n: int) -> bytes:
    return int(n).to_bytes(32, "big")


def _aliased_batch(elements: int, blob_len: int) -> bytes:
    """executeBatch(address[],bytes[]) whose every bytes[] offset points at the
    same blob — accepted by a permissive ABI decoder, one copy per element."""
    blob = _word(blob_len) + _sel("transfer(address,uint256)") + b"\x00" * (blob_len - 4)
    blob += b"\x00" * ((-blob_len) % 32)
    dests = _word(elements) + b"".join(_word(0xBEEF) for _ in range(elements))
    funcs = _word(elements) + b"".join(_word(32 * elements) for _ in range(elements)) + blob
    return (_sel("executeBatch(address[],bytes[])")
            + _word(64) + _word(64 + len(dests)) + dests + funcs)


def _peak_mb(fn):
    import tracemalloc

    tracemalloc.start()
    try:
        result = fn()
        return result, tracemalloc.get_traced_memory()[1] / 1e6
    finally:
        tracemalloc.stop()


def test_an_aliased_offset_batch_is_refused_without_copying_the_blob():
    from runtime.blockchain.sponsorship import classify_user_operation

    payload = _aliased_batch(200, 200000)          # ~206 KB of call data, 200 elements (under the batch limit)
    labels, peak = _peak_mb(lambda: classify_user_operation(payload))
    assert peak < 5, (f"classifying {len(payload)} bytes peaked at {peak:.1f} MB — "
                      f"the decoder is copying one shared blob per element")
    assert labels == ["unrecognized_call_data"], labels[:3]


def test_non_canonical_offsets_are_not_described():
    """Only the canonical encoding is described. A decoder that accepts other
    offset layouts has to agree with Solidity's on every one of them; refusing
    them is the only reading that cannot disagree."""
    from runtime.blockchain.sponsorship import classify_user_operation

    good = bytes.fromhex(_execute(RECIPIENT, 1, b"")[2:])
    assert classify_user_operation(good) == ["transfer"]
    # Same call, bytes offset moved one word later with a gap word inserted.
    moved = good[:4 + 64] + _word(128) + _word(0) + good[4 + 96:]
    assert classify_user_operation(moved) == ["unrecognized_call_data"]
    # Dirty upper bits in the address word: Solidity reverts, so nothing is described.
    dirty = good[:4] + b"\x01" + good[5:]
    assert classify_user_operation(dirty) == ["unrecognized_call_data"]
    # Bytes length running past the end of the call data.
    truncated = good[:4 + 96] + _word(10**6)
    assert classify_user_operation(truncated) == ["unrecognized_call_data"]


def test_the_three_array_batch_the_client_encodes_is_described():
    from runtime.blockchain.sponsorship import classify_user_operation

    call = (_sel("executeBatch(address[],uint256[],bytes[])")
            + encode(["address[]", "uint256[]", "bytes[]"],
                     [[TOKEN, RECIPIENT, NFT], [0, 5, 0],
                      [_erc20_transfer(RECIPIENT, 5), b"", _nft_mint(RECIPIENT)]]))
    assert classify_user_operation(call) == ["transfer", "transfer", "mint_nft"]


# The documented limit, written as a literal so these tests observe behaviour
# on a tree where the constant does not exist, rather than an ImportError.
BATCH_LIMIT = 256


def test_a_batch_over_the_limit_is_one_label():
    from runtime.blockchain.sponsorship import classify_user_operation

    n = BATCH_LIMIT + 1
    inners = [_sel(f"f{i}()") for i in range(n)]
    call = (_sel("executeBatch(address[],bytes[])")
            + encode(["address[]", "bytes[]"], [[TOKEN] * n, inners]))
    assert classify_user_operation(call) == ["oversized_batch"]
    at_limit = (_sel("executeBatch(address[],bytes[])")
                + encode(["address[]", "bytes[]"],
                         [[TOKEN] * BATCH_LIMIT, inners[:BATCH_LIMIT]]))
    assert len(classify_user_operation(at_limit)) == BATCH_LIMIT


def test_the_module_limit_is_the_documented_one():
    from runtime.blockchain.sponsorship import MAX_BATCH_CALLS

    assert MAX_BATCH_CALLS == BATCH_LIMIT


@pytest.mark.asyncio
async def test_the_route_refuses_an_aliased_batch_with_bounded_memory(aiohttp_client,
                                                                        tmp_path):
    client = await _client(aiohttp_client, tmp_path, policy=TRANSFER_ONLY)
    body = _body("0x" + _aliased_batch(200, 200000).hex())

    async def _post():
        r = await client.post("/api/v1/paymaster/sign", json=body)
        return r.status, await r.text()

    import tracemalloc
    tracemalloc.start()
    try:
        status, text = await _post()
        peak = tracemalloc.get_traced_memory()[1] / 1e6
    finally:
        tracemalloc.stop()
    assert status == 403, text[:300]
    assert peak < 20, f"one sign request peaked at {peak:.1f} MB"


@pytest.mark.asyncio
async def test_with_no_allowlist_the_call_data_is_not_classified(aiohttp_client,
                                                                  tmp_path, monkeypatch):
    """Nothing reads the labels when no allowlist is configured, so the caller's
    bytes are not decoded at all — only hex-decoded and hashed, as before."""
    import runtime.blockchain.sponsorship as sponsorship

    def _must_not_run(*_a, **_k):
        raise AssertionError("classify_user_operation ran with no allowlist configured")

    monkeypatch.setattr(sponsorship, "classify_user_operation", _must_not_run)
    client = await _client(aiohttp_client, tmp_path)
    r = await client.post("/api/v1/paymaster/sign",
                          json=_body("0x" + _aliased_batch(200, 200000).hex()))
    assert r.status == 200, (await r.text())[:300]


@pytest.mark.asyncio
async def test_a_refusal_does_not_echo_an_unbounded_label_list(aiohttp_client, tmp_path):
    client = await _client(aiohttp_client, tmp_path, policy=TRANSFER_ONLY)
    for n in (64, BATCH_LIMIT, 1000):
        inners = [_sel(f"f{i}()") for i in range(n)]
        call = (_sel("executeBatch(address[],bytes[])")
                + encode(["address[]", "bytes[]"], [[TOKEN] * n, inners]))
        r = await client.post("/api/v1/paymaster/sign", json=_body("0x" + call.hex()))
        text = await r.text()
        assert r.status == 403, text[:300]
        assert len(text) < 2048, f"a {n}-call refusal echoed {len(text)} bytes"


# ── what the daily cap bounds, stated as measured ────────────────────────

@pytest.mark.asyncio
async def test_the_daily_cap_is_per_address_and_without_a_session_the_caller_names_it(
        aiohttp_client, tmp_path, monkeypatch):
    """The disclosure in sponsorship.py (WHAT IT CANNOT KNOW), gateway/paymaster.py
    and the config example says the cap bounds spend per address, not per caller.
    This pins that reading: a second request from one address crosses the cap,
    and each address the caller writes into X-Wallet-Address / `sender` starts
    with a fresh one. If this ever fails because rotation is refused, the
    disclosure is out of date, not the test."""
    from runtime.blockchain import price_feed

    async def _eth_usd(self, *, now=None):
        return {"price": 1000.0, "source": "test"}

    monkeypatch.setattr(price_feed.PriceFeed, "eth_usd", _eth_usd)
    # 1 gwei x 321,000 gas at $1000/ETH is about $0.32 a request.
    client = await _client(aiohttp_client, tmp_path, policy={"daily_cap_usd": 0.5})

    async def _sign(sender):
        r = await client.post("/api/v1/paymaster/sign",
                              json=_body(_execute(RECIPIENT, 1, b""), sender=sender),
                              headers={"X-Wallet-Address": sender})
        return r.status

    one = "0x" + "11" * 20
    assert [await _sign(one), await _sign(one)] == [200, 403]
    fresh = ["0x" + f"{i:040x}" for i in range(3, 7)]
    assert [await _sign(a) for a in fresh] == [200, 200, 200, 200]
