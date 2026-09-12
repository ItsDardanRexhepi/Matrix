"""
EAS Client — Ethereum Attestation Service integration.

Attestations provide a permanent, verifiable record of what was done, by
whom, and when. The platform key signs them. An attestation a user's tool call
asks for (`operation` given) is metered by the sponsorship policy like any
other platform-signed operation; one the platform writes as its own record
(`operation` omitted) is listed in UNMETERED_PLATFORM_OPERATIONS and is not
counted against any user's cap.
"""

import json
import logging
import time
from typing import Any

from runtime.blockchain.sponsorship import SponsorshipDenied
from runtime.blockchain.web3_manager import Web3Manager, is_placeholder_value

logger = logging.getLogger(__name__)

# The most attestations one batch request may ask the platform to sign. A batch
# list comes from the caller (the `eas` tool's `attestations`, the
# `batch_attest` capability's), and every entry is a platform-signed write; an
# unbounded list was an unbounded number of writes from one request.
MAX_ATTESTATIONS_PER_BATCH = 20

# EAS contract ABI (attest function)
EAS_ATTEST_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "schema", "type": "bytes32"},
                    {
                        "components": [
                            {"name": "recipient", "type": "address"},
                            {"name": "expirationTime", "type": "uint64"},
                            {"name": "revocable", "type": "bool"},
                            {"name": "refUID", "type": "bytes32"},
                            {"name": "data", "type": "bytes"},
                            {"name": "value", "type": "uint256"},
                        ],
                        "name": "data",
                        "type": "tuple",
                    },
                ],
                "name": "request",
                "type": "tuple",
            }
        ],
        "name": "attest",
        "outputs": [{"name": "", "type": "bytes32"}],
        "stateMutability": "payable",
        "type": "function",
    }
]


class EASClient:
    """Client for creating on-chain attestations via Ethereum Attestation Service."""

    def __init__(self, config: dict):
        self.config = config
        bc = config.get("blockchain", {})
        self.rpc_url = bc.get("rpc_url", "")
        self.eas_contract = bc.get("eas_contract", "")
        self.eas_schema = bc.get("eas_schema", "")
        self.paymaster_key = bc.get("paymaster_private_key", "")
        self.platform_wallet = bc.get("platform_wallet", "")
        self.chain_id = bc.get("chain_id", 84532)
        self._manager = Web3Manager.get_shared(config)

    def _is_configured(self) -> bool:
        """Return True only if EAS is fully configured and the manager is online."""
        if not self._manager.available:
            return False
        for val in (self.eas_contract, self.eas_schema, self.paymaster_key):
            if is_placeholder_value(val):
                return False
        return True

    @property
    def web3(self):
        return self._manager.w3

    async def attest(
        self,
        action: str,
        agent: str,
        details: dict,
        recipient: str = "0x0000000000000000000000000000000000000000",
        *,
        operation: str | None = None,
    ) -> dict:
        """
        Create an on-chain attestation for a blockchain action, signed with the
        platform key.

        `operation` decides who the gas is charged against. A model-facing tool
        that attests because a user asked it to passes its own
        `<capability>.<method>` name: the signature then goes through
        `platform_signer`, so the allowlist, the per-identity daily cap and the
        identity requirement apply, and a refusal raises SponsorshipDenied. With
        no `operation`, the write is the platform's own record
        (`eas.attest` in UNMETERED_PLATFORM_OPERATIONS) and is not metered.

        Args:
            action: The action being attested (e.g., "deploy_contract")
            agent: Which agent performed the action (e.g., "neo")
            details: Key-value details about the action
            recipient: Ethereum address of the recipient (default: zero address)
            operation: the metered operation name, keyword-only
        """
        if not self._is_configured():
            logger.warning(
                "EAS attestation skipped — blockchain not configured (action=%s)",
                action,
            )
            return {
                "status": "skipped",
                "reason": "blockchain not configured",
                "action": action,
                "agent": agent,
            }

        try:
            from web3 import Web3
            from eth_account import Account
            from runtime.blockchain.sponsorship import (
                platform_signer, unmetered_platform_signer,
            )
            from eth_abi import encode

            self._validate_config()

            # Encode attestation data
            attestation_data = {
                "platform": "0pnMatrx",
                "action": action,
                "agent": agent,
                "timestamp": int(time.time()),
                "details": details,
            }
            encoded_data = encode(
                ["string", "string", "string", "uint256"],
                [
                    attestation_data["platform"],
                    attestation_data["action"],
                    attestation_data["agent"],
                    attestation_data["timestamp"],
                ],
            )

            # Build EAS attest transaction
            eas = self.web3.eth.contract(
                address=Web3.to_checksum_address(self.eas_contract),
                abi=EAS_ATTEST_ABI,
            )

            schema_bytes = bytes.fromhex(self.eas_schema.replace("0x", ""))
            tx = eas.functions.attest(
                (
                    schema_bytes,
                    (
                        Web3.to_checksum_address(recipient),
                        0,  # no expiration
                        True,  # revocable
                        b"\x00" * 32,  # no reference
                        encoded_data,
                        0,  # no value
                    ),
                )
            ).build_transaction({
                "from": self.platform_wallet,
                "chainId": self.chain_id,
                "gas": 300000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(self.platform_wallet),
            })

            # Sign and send with the platform key: metered when a user's tool
            # call asked for it, listed as the platform's own record otherwise.
            if operation:
                account = await platform_signer(self.config, operation,
                                                key=self.paymaster_key)
            else:
                account = unmetered_platform_signer(self.paymaster_key, "eas.attest")
            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            logger.info(f"EAS attestation created: {tx_hash.hex()} for action={action}")

            return {
                "attestation_tx": tx_hash.hex(),
                "status": "attested" if receipt["status"] == 1 else "failed",
                "action": action,
                "agent": agent,
                "block_number": receipt["blockNumber"],
                "gas_paid_by": "platform (0pnMatrx)",
            }

        except SponsorshipDenied:
            # A refusal is not a failure to report as "failed": the caller (and
            # the tool dispatcher) renders the policy's reason.
            raise
        except ImportError as e:
            logger.warning(f"EAS attestation skipped — missing dependency: {e}")
            return {
                "status": "skipped",
                "reason": f"Missing dependency: {e}",
                "action": action,
                "agent": agent,
            }
        except Exception as e:
            logger.error(f"EAS attestation failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "action": action,
                "agent": agent,
            }

    async def verify(self, attestation_uid: str) -> dict:
        """Verify an existing attestation on-chain by querying the EAS contract."""
        try:
            from web3 import Web3

            self._validate_config()

            # EAS getAttestation ABI
            get_attestation_abi = [{
                "inputs": [{"name": "uid", "type": "bytes32"}],
                "name": "getAttestation",
                "outputs": [{
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
                    "name": "",
                    "type": "tuple",
                }],
                "stateMutability": "view",
                "type": "function",
            }]

            eas = self.web3.eth.contract(
                address=Web3.to_checksum_address(self.eas_contract),
                abi=get_attestation_abi,
            )

            uid_bytes = bytes.fromhex(attestation_uid.replace("0x", ""))
            attestation = eas.functions.getAttestation(uid_bytes).call()

            # attestation[4] is revocationTime — 0 means not revoked
            is_revoked = attestation[4] != 0
            # attestation[2] is the creation time — 0 means attestation doesn't exist
            exists = attestation[2] != 0

            return {
                "uid": attestation_uid,
                "verified": exists and not is_revoked,
                "exists": exists,
                "revoked": is_revoked,
                "schema": "0x" + attestation[1].hex() if isinstance(attestation[1], bytes) else str(attestation[1]),
                "attester": attestation[7],
                "recipient": attestation[6],
                "time": attestation[2],
                "network": self.config.get("blockchain", {}).get("network", "base-sepolia"),
            }
        except ValueError as e:
            return {"uid": attestation_uid, "verified": False, "error": str(e),
                    "hint": "Ensure blockchain.eas_contract and blockchain.rpc_url are configured."}
        except Exception as e:
            return {"uid": attestation_uid, "verified": False, "error": str(e)}

    def _validate_config(self):
        missing = []
        for key, val in [
            ("rpc_url", self.rpc_url),
            ("eas_contract", self.eas_contract),
            ("eas_schema", self.eas_schema),
            ("paymaster_private_key", self.paymaster_key),
            ("platform_wallet", self.platform_wallet),
        ]:
            if not val or str(val).startswith("YOUR_"):
                missing.append(key)
        if missing:
            raise ValueError(f"Missing EAS config: {', '.join(missing)}")
