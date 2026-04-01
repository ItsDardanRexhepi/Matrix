"""
Payments — send and receive ETH and tokens on Base L2.

Handles native ETH transfers, ERC-20 token payments, and batch transfers.
All gas fees covered by the platform.
"""

import json
import logging

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)

ERC20_TRANSFER_ABI = [
    {"inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
]


class Payments(BlockchainInterface):

    @property
    def name(self) -> str:
        return "payment"

    @property
    def description(self) -> str:
        return "Send ETH and token payments on Base L2. All gas fees covered by the platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["send_eth", "send_token", "get_balance", "estimate_fee"]},
                "to": {"type": "string", "description": "Recipient address"},
                "amount": {"type": "string", "description": "Amount to send"},
                "token_address": {"type": "string", "description": "ERC-20 token address (for send_token)"},
                "address": {"type": "string", "description": "Address to check balance"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "send_eth":
            return await self._send_eth(kwargs)
        elif action == "send_token":
            return await self._send_token(kwargs)
        elif action == "get_balance":
            return await self._get_balance(kwargs)
        elif action == "estimate_fee":
            return await self._estimate_fee(kwargs)
        return f"Unknown payment action: {action}"

    async def _send_eth(self, params: dict) -> str:
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            to = params.get("to", "")
            amount_eth = float(params.get("amount", "0"))
            amount_wei = self.web3.to_wei(amount_eth, "ether")

            account = Account.from_key(bc["paymaster_private_key"])
            tx = {
                "from": bc["platform_wallet"],
                "to": Web3.to_checksum_address(to),
                "value": amount_wei,
                "chainId": self.chain_id,
                "gas": 21000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            }

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "sent" if receipt["status"] == 1 else "failed",
                "to": to,
                "amount_eth": str(amount_eth),
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"ETH send failed: {e}"

    async def _send_token(self, params: dict) -> str:
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            token_addr = params.get("token_address", "")
            to = params.get("to", "")
            amount = int(float(params.get("amount", "0")) * 10**18)

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(token_addr),
                abi=ERC20_TRANSFER_ABI,
            )
            account = Account.from_key(bc["paymaster_private_key"])

            tx = contract.functions.transfer(
                Web3.to_checksum_address(to), amount
            ).build_transaction({
                "from": bc["platform_wallet"],
                "chainId": self.chain_id,
                "gas": 100000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "sent" if receipt["status"] == 1 else "failed",
                "to": to,
                "token": token_addr,
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Token send failed: {e}"

    async def _get_balance(self, params: dict) -> str:
        try:
            addr = params.get("address", self.platform_wallet)
            balance_wei = self.web3.eth.get_balance(addr)
            return json.dumps({
                "address": addr,
                "balance_eth": str(self.web3.from_wei(balance_wei, "ether")),
                "balance_wei": str(balance_wei),
                "network": self.network,
            })
        except Exception as e:
            return f"Balance check failed: {e}"

    async def _estimate_fee(self, params: dict) -> str:
        try:
            gas_price = self.web3.eth.gas_price
            eth_cost = self.web3.from_wei(gas_price * 21000, "ether")
            return json.dumps({
                "gas_price_gwei": str(self.web3.from_wei(gas_price, "gwei")),
                "estimated_eth_transfer_cost": str(eth_cost),
                "paid_by": "platform (0pnMatrx) — users never pay gas",
                "network": self.network,
            })
        except Exception as e:
            return f"Fee estimation failed: {e}"
