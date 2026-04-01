"""
EAS Deployment Attestor — creates attestations for every deployment and action.
Uses EAS contract on Base Sepolia/Mainnet.
"""

import asyncio
import json
import logging
import time
from typing import Any

from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.exceptions import TransactionNotFound
from eth_account import Account
from eth_abi import encode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# EAS contract addresses (canonical deployments)
# ---------------------------------------------------------------------------
EAS_CONTRACT_ADDRESSES: dict[int, str] = {
    84532: "0x4200000000000000000000000000000000000021",   # Base Sepolia
    8453:  "0x4200000000000000000000000000000000000021",   # Base Mainnet
}

# Schema 348 UID — the OpenMatrix deployment attestation schema
DEFAULT_SCHEMA_UID = (
    "0x"
    "a1bf4c0d5e4e4e0e5e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d"
)

# ---------------------------------------------------------------------------
# Minimal EAS ABI (attest + getAttestation)
# ---------------------------------------------------------------------------
EAS_ABI: list[dict] = [
    {
        "name": "attest",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "request",
                "type": "tuple",
                "components": [
                    {"name": "schema", "type": "bytes32"},
                    {
                        "name": "data",
                        "type": "tuple",
                        "components": [
                            {"name": "recipient", "type": "address"},
                            {"name": "expirationTime", "type": "uint64"},
                            {"name": "revocable", "type": "bool"},
                            {"name": "refUID", "type": "bytes32"},
                            {"name": "data", "type": "bytes"},
                            {"name": "value", "type": "uint256"},
                        ],
                    },
                ],
            }
        ],
        "outputs": [{"name": "", "type": "bytes32"}],
    },
    {
        "name": "getAttestation",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "uid", "type": "bytes32"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "uid", "type": "bytes32"},
                    {"name": "schema", "type": "bytes32"},
                    {"name": "time", "type": "uint64"},
                    {"name": "expirationTime", "type": "uint64"},
                    {"name": "revocationTime", "type": "uint64"},
                    {"name": "refUID", "type": "bytes32"},
                    {"name": "recipient", "type": "address"},
                    {"name": "attester", "type": "address"},
                    {"name": "revocable", "type": "bool"},
                    {"name": "data", "type": "bytes"},
                ],
            }
        ],
    },
]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def _get_eas_address(config: dict) -> str:
    """Resolve the EAS contract address for the configured chain."""
    chain_id = int(config["chain_id"])
    if "eas_contract_address" in config:
        return config["eas_contract_address"]
    if chain_id not in EAS_CONTRACT_ADDRESSES:
        raise ValueError(
            f"No known EAS contract for chain {chain_id}. "
            "Set eas_contract_address in config."
        )
    return EAS_CONTRACT_ADDRESSES[chain_id]


def _get_schema_uid(config: dict) -> bytes:
    """Return schema UID as bytes32."""
    uid_hex = config.get("eas_schema_uid", DEFAULT_SCHEMA_UID)
    return bytes.fromhex(uid_hex.removeprefix("0x"))


def _encode_attestation_data(action_type: str, data: dict) -> bytes:
    """
    ABI-encode the attestation payload.

    Schema 348 layout:
        string actionType, string jsonPayload, uint256 timestamp
    """
    json_payload = json.dumps(data, separators=(",", ":"), sort_keys=True)
    timestamp = int(time.time())
    return encode(
        ["string", "string", "uint256"],
        [action_type, json_payload, timestamp],
    )


async def _build_web3(config: dict) -> tuple[AsyncWeb3, Account]:
    """Return an (AsyncWeb3, Account) pair from config."""
    w3 = AsyncWeb3(AsyncHTTPProvider(config["rpc_url"]))
    account = Account.from_key(config["private_key"])
    return w3, account


async def _wait_for_receipt(
    w3: AsyncWeb3, tx_hash_hex: str, timeout: int = 180, poll: int = 2
) -> dict:
    """Poll for transaction receipt."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            receipt = await w3.eth.get_transaction_receipt(tx_hash_hex)
            if receipt is not None:
                return receipt
        except TransactionNotFound:
            pass
        await asyncio.sleep(poll)
    raise TimeoutError(f"Tx {tx_hash_hex} not confirmed within {timeout}s")


# ---------------------------------------------------------------------------
# attest_action
# ---------------------------------------------------------------------------

async def attest_action(
    config: dict,
    action_type: str,
    data: dict,
    recipient: str,
) -> dict:
    """
    Create an on-chain EAS attestation for an arbitrary platform action.

    Parameters
    ----------
    config      : deployer config dict (rpc_url, chain_id, private_key, ...)
    action_type : e.g. "contract_deployment", "revenue_transfer", "governance_vote"
    data        : arbitrary JSON-serialisable dict stored in the attestation
    recipient   : Ethereum address that the attestation references

    Returns
    -------
    {
        "uid": str,          # attestation UID (bytes32 hex)
        "tx_hash": str,
        "attester": str,
        "recipient": str,
        "action_type": str,
    }
    """
    w3, account = await _build_web3(config)
    eas_address = _get_eas_address(config)
    schema_uid = _get_schema_uid(config)
    chain_id = int(config["chain_id"])

    eas = w3.eth.contract(address=eas_address, abi=EAS_ABI)

    encoded_data = _encode_attestation_data(action_type, data)

    # Build AttestationRequest struct
    attestation_request = (
        schema_uid,                                # schema (bytes32)
        (
            recipient,                             # recipient
            0,                                     # expirationTime (0 = never)
            True,                                  # revocable
            b"\x00" * 32,                          # refUID (none)
            encoded_data,                          # data
            0,                                     # value (no ETH attached)
        ),
    )

    nonce = await w3.eth.get_transaction_count(account.address)
    tx = await eas.functions.attest(attestation_request).build_transaction(
        {
            "from": account.address,
            "nonce": nonce,
            "chainId": chain_id,
            "maxPriorityFeePerGas": w3.to_wei(
                config.get("max_priority_fee_gwei", 0.1), "gwei"
            ),
        }
    )

    # Estimate gas
    estimated = await w3.eth.estimate_gas(tx)
    tx["gas"] = int(estimated * 1.2)

    signed = account.sign_transaction(tx)
    tx_hash = await w3.eth.send_raw_transaction(signed.raw_transaction)
    tx_hash_hex = tx_hash.hex()

    logger.info("EAS attest tx sent: %s", tx_hash_hex)

    receipt = await _wait_for_receipt(w3, tx_hash_hex)

    if receipt["status"] != 1:
        raise RuntimeError(f"EAS attestation tx reverted: {tx_hash_hex}")

    # The UID is the return value of attest(); extract from logs or receipt.
    # The EAS contract emits Attested(address indexed recipient, address indexed attester,
    #   bytes32 uid, bytes32 indexed schema).  uid is in topic[0] after the event sig.
    # For simplicity, we decode the first log's data field which contains the UID.
    uid_hex = "0x"
    if receipt.get("logs"):
        first_log = receipt["logs"][0]
        if first_log.get("data") and len(first_log["data"]) >= 32:
            uid_hex = "0x" + first_log["data"].hex()[:64]

    result = {
        "uid": uid_hex,
        "tx_hash": tx_hash_hex,
        "attester": account.address,
        "recipient": recipient,
        "action_type": action_type,
    }

    logger.info("Attestation created — UID %s", uid_hex)
    return result


# ---------------------------------------------------------------------------
# verify_attestation
# ---------------------------------------------------------------------------

async def verify_attestation(config: dict, uid: str) -> dict:
    """
    Read an existing attestation from EAS by its UID.

    Parameters
    ----------
    config : deployer config dict
    uid    : attestation UID (bytes32, 0x-prefixed hex)

    Returns
    -------
    {
        "uid": str,
        "schema": str,
        "time": int,
        "recipient": str,
        "attester": str,
        "revocable": bool,
        "data_hex": str,
        "exists": bool,
    }
    """
    w3, _ = await _build_web3(config)
    eas_address = _get_eas_address(config)

    eas = w3.eth.contract(address=eas_address, abi=EAS_ABI)

    uid_bytes = bytes.fromhex(uid.removeprefix("0x").zfill(64))

    try:
        att = await eas.functions.getAttestation(uid_bytes).call()
    except Exception as exc:
        logger.warning("Could not fetch attestation %s: %s", uid, exc)
        return {"uid": uid, "exists": False}

    # att is a tuple matching the ABI output components
    (
        att_uid,
        att_schema,
        att_time,
        att_expiration,
        att_revocation,
        att_ref_uid,
        att_recipient,
        att_attester,
        att_revocable,
        att_data,
    ) = att

    exists = att_time > 0

    result = {
        "uid": "0x" + att_uid.hex(),
        "schema": "0x" + att_schema.hex(),
        "time": att_time,
        "expiration_time": att_expiration,
        "revocation_time": att_revocation,
        "recipient": att_recipient,
        "attester": att_attester,
        "revocable": att_revocable,
        "data_hex": "0x" + att_data.hex(),
        "exists": exists,
    }

    if exists:
        logger.info("Attestation %s verified — attester %s at %d", uid, att_attester, att_time)
    else:
        logger.warning("Attestation %s does not exist or was revoked", uid)

    return result
