"""
Dashboard — blockchain analytics and monitoring for 0pnMatrx.

Query wallet balances, transaction history, gas prices, block info,
and platform activity. All read operations — no gas required.
"""

import json
import logging
import time

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)


class Dashboard(BlockchainInterface):

    @property
    def name(self) -> str:
        return "dashboard"

    @property
    def description(self) -> str:
        return "Blockchain dashboard: wallet balances, tx history, gas prices, network stats. Read-only, no gas needed."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["wallet_overview", "tx_history", "gas_price", "block_info", "platform_stats"]},
                "address": {"type": "string"},
                "tx_hash": {"type": "string"},
                "block_number": {"type": "integer"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "wallet_overview":
            return await self._wallet_overview(kwargs)
        elif action == "tx_history":
            return await self._tx_history(kwargs)
        elif action == "gas_price":
            return await self._gas_price(kwargs)
        elif action == "block_info":
            return await self._block_info(kwargs)
        elif action == "platform_stats":
            return await self._platform_stats(kwargs)
        return f"Unknown dashboard action: {action}"

    async def _wallet_overview(self, params: dict) -> str:
        """Get a complete wallet overview."""
        try:
            from web3 import Web3
            addr = params.get("address", self.platform_wallet)
            balance_wei = self.web3.eth.get_balance(addr)
            code = self.web3.eth.get_code(addr)
            tx_count = self.web3.eth.get_transaction_count(addr)

            return json.dumps({
                "address": addr,
                "balance_eth": str(self.web3.from_wei(balance_wei, "ether")),
                "balance_wei": str(balance_wei),
                "transaction_count": tx_count,
                "is_contract": len(code) > 0,
                "network": self.network,
                "chain_id": self.chain_id,
            }, indent=2)
        except Exception as e:
            return f"Wallet overview failed: {e}"

    async def _tx_history(self, params: dict) -> str:
        """Get transaction details."""
        try:
            tx_hash = params.get("tx_hash", "")
            if tx_hash:
                tx = self.web3.eth.get_transaction(tx_hash)
                receipt = self.web3.eth.get_transaction_receipt(tx_hash)
                return json.dumps({
                    "tx_hash": tx_hash,
                    "from": tx["from"],
                    "to": tx["to"],
                    "value_eth": str(self.web3.from_wei(tx["value"], "ether")),
                    "gas_used": receipt["gasUsed"],
                    "status": "success" if receipt["status"] == 1 else "failed",
                    "block_number": receipt["blockNumber"],
                }, indent=2)
            return json.dumps({"note": "Provide tx_hash to look up specific transaction"})
        except Exception as e:
            return f"TX lookup failed: {e}"

    async def _gas_price(self, params: dict) -> str:
        """Get current gas price."""
        try:
            gas_price = self.web3.eth.gas_price
            return json.dumps({
                "gas_price_wei": str(gas_price),
                "gas_price_gwei": str(self.web3.from_wei(gas_price, "gwei")),
                "eth_transfer_cost": str(self.web3.from_wei(gas_price * 21000, "ether")),
                "note": "All gas is covered by the platform — users never pay",
                "network": self.network,
            }, indent=2)
        except Exception as e:
            return f"Gas price check failed: {e}"

    async def _block_info(self, params: dict) -> str:
        """Get block information."""
        try:
            block_num = params.get("block_number")
            if block_num:
                block = self.web3.eth.get_block(block_num)
            else:
                block = self.web3.eth.get_block("latest")

            return json.dumps({
                "block_number": block["number"],
                "timestamp": block["timestamp"],
                "transactions": len(block["transactions"]),
                "gas_used": block["gasUsed"],
                "gas_limit": block["gasLimit"],
                "hash": block["hash"].hex(),
                "network": self.network,
            }, indent=2)
        except Exception as e:
            return f"Block info failed: {e}"

    async def _platform_stats(self, params: dict) -> str:
        """Get platform blockchain statistics."""
        try:
            balance = self.web3.eth.get_balance(self.platform_wallet) if self.platform_wallet else 0
            latest_block = self.web3.eth.block_number
            gas_price = self.web3.eth.gas_price

            return json.dumps({
                "platform": "0pnMatrx",
                "network": self.network,
                "chain_id": self.chain_id,
                "platform_wallet": self.platform_wallet,
                "platform_balance_eth": str(self.web3.from_wei(balance, "ether")),
                "latest_block": latest_block,
                "gas_price_gwei": str(self.web3.from_wei(gas_price, "gwei")),
                "gas_policy": "All gas fees covered by platform — users never pay",
            }, indent=2)
        except Exception as e:
            return f"Platform stats failed: {e}"
