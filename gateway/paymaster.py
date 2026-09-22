"""P4: verifying-paymaster signing (server half of MatrixVerifyingPaymaster).

The platform's off-chain signer approves gas sponsorship by signing a digest over
a UserOperation's material fields. The digest MUST match the on-chain
`MatrixVerifyingPaymaster.digest` byte-for-byte (two-level keccak) — proven by
tests/test_paymaster_digest.py against a foundry-produced vector.

paymasterAndData layout the client expects:
    [0:20]   paymaster address
    [20:84]  abi.encode(uint48 validUntil, uint48 validAfter)
    [84:]    65-byte signature over eth_sign(digest)

Non-custodial: the signer key is a PLATFORM key that only authorizes gas
sponsorship — it never signs anything the user's account does, never moves user
funds. Sponsorship policy (action allowlist + per-identity daily USD cap) is
enforced before signing; unconfigured signer -> the route returns 503. The
allowlist is checked against the actions decoded from the userOp's own
callData/initCode (runtime.blockchain.sponsorship.classify_user_operation), never
against a label the requester supplies. It constrains which ABI function names
the call data invokes, not what code runs: the target contract, a value
recipient and the sender account are not verified (see that module's WHAT IT
CANNOT KNOW). The daily cap does not bound such a caller either: it is metered
per address, and without a session the address is the X-Wallet-Address header
or body `sender` the caller writes, so each new address gets a fresh cap.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_ZERO32 = b"\x00" * 32

#: EntryPoint v0.6 charges the PAYMASTER for the verification gas limit three
#: times, not once: the same limit also bounds the paymaster's postOp call, and
#: the security model may run postOp twice. Straight from the revision this repo
#: pins at ``contracts/lib/account-abstraction`` — ``EntryPoint.sol``::
#:
#:     uint256 mul = mUserOp.paymaster != address(0) ? 3 : 1;
#:     uint256 requiredGas = mUserOp.callGasLimit
#:                         + mUserOp.verificationGasLimit * mul
#:                         + mUserOp.preVerificationGas;
#:     requiredPrefund = requiredGas * mUserOp.maxFeePerGas;
#:
#: tests/test_paymaster_prefund_is_the_entrypoint_formula.py reads that literal
#: back out of the pinned source, so a pin that moves to a different EntryPoint
#: fails loudly instead of quietly letting the cap under-reserve.
PAYMASTER_VERIFICATION_GAS_MULTIPLIER = 3


def _keccak(data: bytes) -> bytes:
    from eth_utils import keccak
    return keccak(data)


def required_prefund_wei(
    *,
    call_gas_limit: int,
    verification_gas_limit: int,
    pre_verification_gas: int,
    max_fee_per_gas: int,
    has_paymaster: bool = True,
) -> int:
    """Wei EntryPoint v0.6 reserves for one UserOperation — ``_getRequiredPrefund``.

    This is what a sponsorship cap has to be measured against: the EntryPoint
    takes this much from the paymaster's deposit before execution, so it is the
    most real money one signature can commit. Summing the three gas limits once
    each — which is what this route's cap used to meter — under-states it by
    ``2 * verificationGasLimit * maxFeePerGas`` whenever a paymaster is present,
    and a paymaster is present on every operation this module signs.

    ``has_paymaster`` mirrors the upstream ``mul`` so the formula is the whole
    line rather than one of its branches; the sign route always passes the
    default, because it returns 503 before signing when no paymaster address is
    configured.
    """
    mul = PAYMASTER_VERIFICATION_GAS_MULTIPLIER if has_paymaster else 1
    gas = (int(call_gas_limit)
           + int(verification_gas_limit) * mul
           + int(pre_verification_gas))
    return gas * int(max_fee_per_gas)


def compute_paymaster_digest(
    *,
    sender: str,
    nonce: int,
    init_code: bytes,
    call_data: bytes,
    call_gas_limit: int,
    verification_gas_limit: int,
    pre_verification_gas: int,
    max_fee_per_gas: int,
    max_priority_fee_per_gas: int,
    chain_id: int,
    paymaster: str,
    valid_until: int,
    valid_after: int,
) -> bytes:
    """Mirror of MatrixVerifyingPaymaster.digest (two-level keccak).

    opHash = keccak(abi.encode(sender,nonce,keccak(initCode),keccak(callData),
                    callGasLimit,verificationGasLimit,preVerificationGas,
                    maxFeePerGas,maxPriorityFeePerGas))
    digest = keccak(abi.encode(opHash, chainId, paymaster, validUntil, validAfter))
    """
    from eth_abi import encode

    op_hash = _keccak(encode(
        ["address", "uint256", "bytes32", "bytes32",
         "uint256", "uint256", "uint256", "uint256", "uint256"],
        [sender, nonce, _keccak(init_code), _keccak(call_data),
         call_gas_limit, verification_gas_limit, pre_verification_gas,
         max_fee_per_gas, max_priority_fee_per_gas],
    ))
    return _keccak(encode(
        ["bytes32", "uint256", "address", "uint48", "uint48"],
        [op_hash, chain_id, paymaster, valid_until, valid_after],
    ))


def sign_digest(digest: bytes, signer_key: str) -> bytes:
    """Return the 65-byte EIP-191 personal-sign signature the contract recovers
    via ECDSA.recover(toEthSignedMessageHash(digest), sig)."""
    from eth_account import Account
    from eth_account.messages import encode_defunct
    signed = Account.sign_message(encode_defunct(primitive=digest), private_key=signer_key)
    return bytes(signed.signature)


def build_paymaster_and_data(paymaster: str, valid_until: int, valid_after: int,
                             signature: bytes) -> str:
    """paymaster(20) || abi.encode(validUntil, validAfter) || sig(65) -> 0x hex."""
    from eth_abi import encode
    from eth_utils import to_bytes
    addr = to_bytes(hexstr=paymaster)
    ts = encode(["uint48", "uint48"], [valid_until, valid_after])
    return "0x" + (addr + ts + signature).hex()


def paymaster_config(config: dict) -> dict:
    """Resolve the paymaster block from any of its documented homes, without
    mutating the source. Precedence:

      1. top-level ``paymaster``            (test/legacy shape)
      2. ``blockchain.paymaster``           (matrix.config.json.example + DEPLOYMENT_GUIDE)

    Then, if ``signer_key`` is still absent, fall back to the env-bridged
    ``blockchain.paymaster_private_key`` (runtime/config/validation.py
    SECRET_FIELDS, fed by ``MATRIX_PAYMASTER_KEY``). ``address``/``policy``
    come from the resolved block. This is why an operator who fills the
    *documented* location no longer gets a permanent 503 on /paymaster/sign.
    """
    cfg = config if isinstance(config, dict) else {}
    blockchain = cfg.get("blockchain")
    blockchain = blockchain if isinstance(blockchain, dict) else {}
    block = cfg.get("paymaster") or blockchain.get("paymaster") or {}
    if not isinstance(block, dict):
        block = {}
    resolved = dict(block)  # copy — never mutate the source config
    if not resolved.get("signer_key"):
        flat = blockchain.get("paymaster_private_key")
        if flat:
            resolved["signer_key"] = flat
    return resolved


def signer_configured(config: dict) -> bool:
    pk = paymaster_config(config).get("signer_key", "")
    return bool(pk) and not str(pk).startswith("YOUR_")
