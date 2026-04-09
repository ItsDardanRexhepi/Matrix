"""
Insurance — on-chain insurance policy management on Base L2.

Create policies, file claims, process payouts via smart contracts.
All gas covered by the platform.
"""

import json
import logging
import time

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)


class Insurance(BlockchainInterface):

    @property
    def name(self) -> str:
        return "insurance"

    @property
    def description(self) -> str:
        return "On-chain insurance: create policies, file claims, process payouts. Gas covered by platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create_policy", "file_claim", "get_policy", "process_payout"]},
                "policy_contract": {"type": "string"},
                "policy_id": {"type": "string"},
                "coverage_amount": {"type": "string"},
                "premium": {"type": "string"},
                "beneficiary": {"type": "string"},
                "claim_details": {"type": "object"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "create_policy":
            return await self._create_policy(kwargs)
        elif action == "file_claim":
            return await self._file_claim(kwargs)
        elif action == "get_policy":
            return await self._get_policy(kwargs)
        elif action == "process_payout":
            return await self._process_payout(kwargs)
        return f"Unknown insurance action: {action}"

    async def _create_policy(self, params: dict) -> str:
        """Create an insurance policy attested on-chain."""
        from runtime.blockchain.eas_client import EASClient
        client = EASClient(self.config)
        result = await client.attest(
            action="insurance_policy_create",
            agent="neo",
            details={
                "coverage_amount": params.get("coverage_amount", "0"),
                "premium": params.get("premium", "0"),
                "beneficiary": params.get("beneficiary", ""),
                "created_at": int(time.time()),
            },
            recipient=params.get("beneficiary", "0x0000000000000000000000000000000000000000"),
        )
        return json.dumps(result, indent=2, default=str)

    async def _file_claim(self, params: dict) -> str:
        """File an insurance claim attested on-chain."""
        from runtime.blockchain.eas_client import EASClient
        client = EASClient(self.config)
        result = await client.attest(
            action="insurance_claim",
            agent="neo",
            details={
                "policy_id": params.get("policy_id", ""),
                "claim_details": params.get("claim_details", {}),
                "filed_at": int(time.time()),
            },
        )
        return json.dumps(result, indent=2, default=str)

    async def _get_policy(self, params: dict) -> str:
        """Query an insurance policy by verifying its EAS attestation on-chain."""
        try:
            policy_id = params.get("policy_id", "")
            if not policy_id:
                return json.dumps({"status": "error", "error": "policy_id (EAS attestation UID) is required"})

            from runtime.blockchain.eas_client import EASClient
            client = EASClient(self.config)
            result = await client.verify(policy_id)

            return json.dumps({
                "policy_id": policy_id,
                "attestation": result,
                "network": self.network,
            }, indent=2, default=str)
        except Exception as e:
            return json.dumps({
                "policy_id": params.get("policy_id", ""),
                "status": "error",
                "error": str(e),
                "hint": "Ensure blockchain.eas_contract and blockchain.rpc_url are configured.",
            }, indent=2)

    async def _process_payout(self, params: dict) -> str:
        """Process an insurance payout by sending ETH to the beneficiary. Gas covered by platform."""
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            beneficiary = params.get("beneficiary", "")
            amount = params.get("coverage_amount", "0")
            policy_id = params.get("policy_id", "")

            if not beneficiary:
                return json.dumps({"status": "error", "error": "beneficiary address is required for payout"})
            if not amount or float(amount) <= 0:
                return json.dumps({"status": "error", "error": "coverage_amount must be greater than 0"})

            amount_wei = self.web3.to_wei(float(amount), "ether")
            account = Account.from_key(bc["paymaster_private_key"])

            tx = {
                "from": bc["platform_wallet"],
                "to": Web3.to_checksum_address(beneficiary),
                "value": amount_wei,
                "chainId": self.chain_id,
                "gas": 21000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            }

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            # Attest the payout for audit trail
            from runtime.blockchain.eas_client import EASClient
            client = EASClient(self.config)
            attestation = await client.attest(
                action="insurance_payout",
                agent="neo",
                details={
                    "policy_id": policy_id,
                    "beneficiary": beneficiary,
                    "amount_eth": amount,
                    "payout_tx": tx_hash.hex(),
                    "paid_at": int(time.time()),
                },
                recipient=beneficiary,
            )

            return json.dumps({
                "status": "paid" if receipt["status"] == 1 else "failed",
                "policy_id": policy_id,
                "beneficiary": beneficiary,
                "amount_eth": amount,
                "tx_hash": tx_hash.hex(),
                "attestation": attestation,
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2, default=str)
        except Exception as e:
            return f"Payout failed: {e}"
