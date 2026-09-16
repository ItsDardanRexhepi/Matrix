"""P4: verifying-paymaster signing (server half of MatrixVerifyingPaymaster).

The platform's off-chain signer approves gas sponsorship by signing a digest over
a UserOperation's material fields. The digest MUST match the on-chain
`MatrixVerifyingPaymaster.digest` byte-for-byte (two-level keccak) — proven by
tests/test_paymaster_digest.py against a foundry-produced vector.

paymasterAndData layout the client expects:
    [0:20]   paymaster address
    [20:84]  abi.encode(uint48 validUntil, uint48 validAfter)
    [84:]    65-byte signature over eth_sign(digest)

NON-CUSTODIAL, AND THE SIGNER KEY IS NOT NECESSARILY GAS-ONLY. These are two
different claims and this paragraph used to make them as one: "the signer key
is a PLATFORM key that only authorizes gas sponsorship — it never signs
anything the user's account does, never moves user funds."

Non-custodial holds, and it is a statement about the CONTRACT's role for this
signer: MatrixVerifyingPaymaster recovers it only over the sponsorship digest,
so nothing it signs here is the account's own signature and nothing it signs
here moves a user's funds.

"Only authorizes gas sponsorship" is a statement about the KEY, and about the
key it is false on the shipped configuration. ``paymaster_config`` falls back
to ``blockchain.paymaster_private_key`` when no dedicated
``paymaster.signer_key`` is set, and that value is the platform's general
signing key: some twenty modules under ``runtime/blockchain/`` use it to sign
and BROADCAST arbitrary value-moving transactions (defi supply/borrow, DAO
treasury calls, ERC-20 approvals to a caller-named spender, contract
deployment). Sponsorship is then one of the things that key authorizes, not
the only one, and a leak of it costs far more than sponsored gas. The fallback
warns when it is taken; set ``paymaster.signer_key`` to a key that does
nothing else and the sentence becomes true of the key as well.

Sponsorship policy (action allowlist + per-identity daily USD cap) is
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


def _keccak(data: bytes) -> bytes:
    from eth_utils import keccak
    return keccak(data)


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
            # This fallback is where "the signer key only authorizes gas
            # sponsorship" stops being true of the key, and it used to be
            # silent. The value never appears in the message.
            logger.warning(
                "paymaster signer resolved from blockchain.paymaster_private_key "
                "— the platform's general signing key, which runtime/blockchain/* "
                "also uses to sign and broadcast value-moving transactions. Set "
                "paymaster.signer_key to a key dedicated to gas sponsorship.")
    return resolved


def signer_configured(config: dict) -> bool:
    pk = paymaster_config(config).get("signer_key", "")
    return bool(pk) and not str(pk).startswith("YOUR_")
