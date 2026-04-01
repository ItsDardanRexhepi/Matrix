"""
Governance — on-chain governance tools beyond DAOs.

Multi-sig operations, timelock management, access control, and role management.
All gas covered by the platform.
"""

import json
import logging

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)

TIMELOCK_ABI = [
    {"inputs": [{"name": "target", "type": "address"}, {"name": "value", "type": "uint256"}, {"name": "data", "type": "bytes"}, {"name": "predecessor", "type": "bytes32"}, {"name": "salt", "type": "bytes32"}, {"name": "delay", "type": "uint256"}], "name": "schedule", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "target", "type": "address"}, {"name": "value", "type": "uint256"}, {"name": "data", "type": "bytes"}, {"name": "predecessor", "type": "bytes32"}, {"name": "salt", "type": "bytes32"}], "name": "execute", "outputs": [], "stateMutability": "payable", "type": "function"},
    {"inputs": [], "name": "getMinDelay", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]


class Governance(BlockchainInterface):

    @property
    def name(self) -> str:
        return "governance"

    @property
    def description(self) -> str:
        return "On-chain governance: timelock operations, access control, role management. Gas covered by platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["schedule_operation", "execute_operation", "get_delay", "grant_role", "revoke_role"]},
                "timelock_address": {"type": "string"},
                "target": {"type": "string"},
                "value": {"type": "string", "default": "0"},
                "data": {"type": "string"},
                "delay": {"type": "integer"},
                "role": {"type": "string"},
                "account": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "schedule_operation":
            return await self._schedule(kwargs)
        elif action == "execute_operation":
            return await self._execute_op(kwargs)
        elif action == "get_delay":
            return await self._get_delay(kwargs)
        elif action == "grant_role":
            return await self._grant_role(kwargs)
        elif action == "revoke_role":
            return await self._revoke_role(kwargs)
        return f"Unknown governance action: {action}"

    async def _schedule(self, params: dict) -> str:
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            timelock = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["timelock_address"]),
                abi=TIMELOCK_ABI,
            )
            account = Account.from_key(bc["paymaster_private_key"])

            data = bytes.fromhex(params.get("data", "0x").replace("0x", "")) if params.get("data") else b""
            delay = params.get("delay", 86400)

            tx = timelock.functions.schedule(
                Web3.to_checksum_address(params.get("target", bc["platform_wallet"])),
                int(params.get("value", "0")),
                data,
                b"\x00" * 32,
                b"\x00" * 32,
                delay,
            ).build_transaction({
                "from": bc["platform_wallet"],
                "chainId": self.chain_id,
                "gas": 300000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "scheduled" if receipt["status"] == 1 else "failed",
                "delay_seconds": delay,
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Schedule failed: {e}"

    async def _execute_op(self, params: dict) -> str:
        return json.dumps({
            "status": "execution_prepared",
            "note": "Operation must have passed its timelock delay before execution. Gas covered by platform.",
        })

    async def _get_delay(self, params: dict) -> str:
        try:
            from web3 import Web3
            timelock = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["timelock_address"]),
                abi=TIMELOCK_ABI,
            )
            delay = timelock.functions.getMinDelay().call()
            return json.dumps({"min_delay_seconds": delay, "min_delay_hours": delay / 3600})
        except Exception as e:
            return f"Delay check failed: {e}"

    async def _grant_role(self, params: dict) -> str:
        return json.dumps({
            "status": "role_grant_prepared",
            "role": params.get("role", ""),
            "account": params.get("account", ""),
            "note": "Role management requires AccessControl contract. Gas covered by platform.",
        })

    async def _revoke_role(self, params: dict) -> str:
        return json.dumps({
            "status": "role_revoke_prepared",
            "role": params.get("role", ""),
            "account": params.get("account", ""),
            "note": "Role revocation requires AccessControl contract. Gas covered by platform.",
        })
