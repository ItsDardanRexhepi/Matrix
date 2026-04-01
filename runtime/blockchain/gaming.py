"""
Gaming — on-chain gaming assets and interactions on Base L2.

Manage game items (ERC-1155), achievements, leaderboards, and in-game economies.
All gas covered by the platform.
"""

import json
import logging

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)

ERC1155_ABI = [
    {"inputs": [{"name": "account", "type": "address"}, {"name": "id", "type": "uint256"}, {"name": "amount", "type": "uint256"}, {"name": "data", "type": "bytes"}], "name": "mint", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "from", "type": "address"}, {"name": "to", "type": "address"}, {"name": "id", "type": "uint256"}, {"name": "amount", "type": "uint256"}, {"name": "data", "type": "bytes"}], "name": "safeTransferFrom", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}, {"name": "id", "type": "uint256"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]


class Gaming(BlockchainInterface):

    @property
    def name(self) -> str:
        return "gaming"

    @property
    def description(self) -> str:
        return "On-chain gaming: manage game items (ERC-1155), achievements, transfers. Gas covered by platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["mint_item", "transfer_item", "get_inventory", "record_achievement"]},
                "contract_address": {"type": "string"},
                "player_address": {"type": "string"},
                "item_id": {"type": "integer"},
                "amount": {"type": "integer", "default": 1},
                "to": {"type": "string"},
                "achievement": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "mint_item":
            return await self._mint_item(kwargs)
        elif action == "transfer_item":
            return await self._transfer_item(kwargs)
        elif action == "get_inventory":
            return await self._get_inventory(kwargs)
        elif action == "record_achievement":
            return await self._record_achievement(kwargs)
        return f"Unknown gaming action: {action}"

    async def _mint_item(self, params: dict) -> str:
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["contract_address"]),
                abi=ERC1155_ABI,
            )
            account = Account.from_key(bc["paymaster_private_key"])
            player = params.get("player_address", bc["platform_wallet"])

            tx = contract.functions.mint(
                Web3.to_checksum_address(player),
                params.get("item_id", 1),
                params.get("amount", 1),
                b"",
            ).build_transaction({
                "from": bc["platform_wallet"],
                "chainId": self.chain_id,
                "gas": 200000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "minted" if receipt["status"] == 1 else "failed",
                "item_id": params.get("item_id", 1),
                "amount": params.get("amount", 1),
                "player": player,
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Mint failed: {e}"

    async def _transfer_item(self, params: dict) -> str:
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["contract_address"]),
                abi=ERC1155_ABI,
            )
            account = Account.from_key(bc["paymaster_private_key"])

            tx = contract.functions.safeTransferFrom(
                Web3.to_checksum_address(params.get("player_address", bc["platform_wallet"])),
                Web3.to_checksum_address(params["to"]),
                params.get("item_id", 1),
                params.get("amount", 1),
                b"",
            ).build_transaction({
                "from": bc["platform_wallet"],
                "chainId": self.chain_id,
                "gas": 200000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "transferred" if receipt["status"] == 1 else "failed",
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Transfer failed: {e}"

    async def _get_inventory(self, params: dict) -> str:
        try:
            from web3 import Web3
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["contract_address"]),
                abi=ERC1155_ABI,
            )
            player = params.get("player_address", self.platform_wallet)
            item_id = params.get("item_id", 1)
            balance = contract.functions.balanceOf(Web3.to_checksum_address(player), item_id).call()
            return json.dumps({"player": player, "item_id": item_id, "balance": balance})
        except Exception as e:
            return f"Inventory check failed: {e}"

    async def _record_achievement(self, params: dict) -> str:
        from runtime.blockchain.eas_client import EASClient
        client = EASClient(self.config)
        result = await client.attest(
            action="gaming_achievement",
            agent="neo",
            details={
                "player": params.get("player_address", ""),
                "achievement": params.get("achievement", ""),
            },
            recipient=params.get("player_address", "0x0000000000000000000000000000000000000000"),
        )
        return json.dumps(result, indent=2, default=str)
