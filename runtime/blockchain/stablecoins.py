from __future__ import annotations

"""
Stablecoins — interact with stablecoins (USDC, DAI, USDT) on Base L2.

Transfer, approve, check balances, and manage stablecoin operations.
All gas fees covered by the platform.
"""

import json
import logging

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)

STABLECOIN_ADDRESSES = {
    "base-sepolia": {
        "USDC": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        "DAI": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
    },
    "base": {
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "DAI": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
        "USDT": "0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2",
    },
}

ERC20_ABI = [
    {"inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
]


class Stablecoins(BlockchainInterface):

    @property
    def name(self) -> str:
        return "stablecoin"

    @property
    def description(self) -> str:
        return "Stablecoin operations: transfer USDC/DAI/USDT, check balances, approve spending. Gas covered by platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["transfer", "balance", "approve", "list"]},
                "token": {"type": "string", "description": "USDC, DAI, or USDT"},
                "to": {"type": "string"},
                "amount": {"type": "string", "description": "Amount in token units"},
                "address": {"type": "string", "description": "Address to check balance for"},
                "spender": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "transfer":
            return await self._transfer(kwargs)
        elif action == "balance":
            return await self._balance(kwargs)
        elif action == "approve":
            return await self._approve(kwargs)
        elif action == "list":
            return await self._list(kwargs)
        return f"Unknown stablecoin action: {action}"

    def _get_token_address(self, token: str) -> str | None:
        network_tokens = STABLECOIN_ADDRESSES.get(self.network, {})
        return network_tokens.get(token.upper())

    async def _transfer(self, params: dict) -> str:
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            token = params.get("token", "USDC").upper()
            token_addr = self._get_token_address(token)
            if not token_addr:
                return f"Unknown stablecoin: {token} on {self.network}"

            contract = self.web3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI)
            decimals = contract.functions.decimals().call()
            amount = int(float(params.get("amount", "0")) * 10**decimals)
            account = Account.from_key(bc["paymaster_private_key"])

            tx = contract.functions.transfer(
                Web3.to_checksum_address(params["to"]), amount
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
                "status": "transferred" if receipt["status"] == 1 else "failed",
                "token": token,
                "amount": params.get("amount"),
                "to": params["to"],
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Transfer failed: {e}"

    async def _balance(self, params: dict) -> str:
        try:
            from web3 import Web3
            token = params.get("token", "USDC").upper()
            token_addr = self._get_token_address(token)
            if not token_addr:
                return f"Unknown stablecoin: {token}"

            contract = self.web3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI)
            decimals = contract.functions.decimals().call()
            addr = params.get("address", self.platform_wallet)
            balance = contract.functions.balanceOf(Web3.to_checksum_address(addr)).call()
            return json.dumps({"token": token, "balance": str(balance / 10**decimals), "address": addr})
        except Exception as e:
            return f"Balance check failed: {e}"

    async def _approve(self, params: dict) -> str:
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            token = params.get("token", "USDC").upper()
            token_addr = self._get_token_address(token)
            if not token_addr:
                return f"Unknown stablecoin: {token}"

            contract = self.web3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI)
            decimals = contract.functions.decimals().call()
            amount = int(float(params.get("amount", "0")) * 10**decimals)
            account = Account.from_key(bc["paymaster_private_key"])

            tx = contract.functions.approve(
                Web3.to_checksum_address(params["spender"]), amount
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
                "status": "approved" if receipt["status"] == 1 else "failed",
                "token": token,
                "spender": params["spender"],
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Approve failed: {e}"

    async def _list(self, params: dict) -> str:
        tokens = STABLECOIN_ADDRESSES.get(self.network, {})
        return json.dumps({"network": self.network, "stablecoins": tokens}, indent=2)
