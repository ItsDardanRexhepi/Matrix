"""P4 HARD GATE: the server paymaster digest must equal the on-chain
OpenMatrixVerifyingPaymaster.digest byte-for-byte.

The vector below is produced by the foundry test
contracts/test/OpenMatrixVerifyingPaymaster.t.sol::test_digest_vector (pinned
there too). If these ever disagree, the client/contract/server would sign
different bytes and every sponsored UserOp would be rejected — so this test fails
loud rather than papering over it.
"""

import pytest

pytest.importorskip("eth_abi")
pytest.importorskip("eth_account")

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak

from gateway.paymaster import (
    compute_paymaster_digest, sign_digest, build_paymaster_and_data,
)

# ── The exact fixed inputs from the foundry test ─────────────────────────
V = dict(
    sender="0x000000000000000000000000000000000000dEaD",
    nonce=7,
    init_code=b"",                       # keccak("") -> matches V_INITCODE_HASH
    call_data=bytes.fromhex("010203"),   # keccak(0x010203) -> V_CALLDATA_HASH
    call_gas_limit=100000,
    verification_gas_limit=200000,
    pre_verification_gas=21000,
    max_fee_per_gas=1000000000,
    max_priority_fee_per_gas=1000000000,
    chain_id=84532,
    paymaster="0x00000000000000000000000000000000caFe0001",
    valid_until=2000000000,
    valid_after=1000000000,
)

FOUNDRY_VECTOR = "0x978d6c5d7846b0d99849405a912ceaeef2e8cfc6059f1befa7f0a7a6e273c3a4"


def test_digest_matches_foundry_vector_byte_for_byte():
    d = compute_paymaster_digest(**V)
    assert "0x" + d.hex() == FOUNDRY_VECTOR, (
        f"server digest {d.hex()} != foundry vector {FOUNDRY_VECTOR}"
    )


def test_signature_recovers_to_signer():
    # Same key the foundry test uses (0xA11CE) -> the contract's verifyingSigner.
    key = "0x" + "0" * 59 + "A11CE"[-5:].lower()  # 0x...a11ce (32 bytes)
    key = "0x" + hex(0xA11CE)[2:].rjust(64, "0")
    acct = Account.from_key(key)
    d = compute_paymaster_digest(**V)
    sig = sign_digest(d, key)
    assert len(sig) == 65
    # Recover via the same EIP-191 personal-sign the contract checks.
    recovered = Account.recover_message(encode_defunct(primitive=d), signature=sig)
    assert recovered.lower() == acct.address.lower()


def test_paymaster_and_data_layout():
    d = compute_paymaster_digest(**V)
    key = "0x" + hex(0xA11CE)[2:].rjust(64, "0")
    sig = sign_digest(d, key)
    pnd = build_paymaster_and_data(V["paymaster"], V["valid_until"], V["valid_after"], sig)
    raw = bytes.fromhex(pnd[2:])
    assert len(raw) == 20 + 64 + 65
    assert "0x" + raw[:20].hex() == V["paymaster"].lower()
    assert raw[84:] == sig
