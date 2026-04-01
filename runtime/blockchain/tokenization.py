"""
Tokenization — create and manage ERC-20 tokens on Base L2.

Deploy custom tokens, transfer, approve, and check balances.
All gas fees are covered by the platform.
"""

import json
import logging

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)

ERC20_ABI = [
    {"inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "mint", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
]


class Tokenization(BlockchainInterface):

    @property
    def name(self) -> str:
        return "tokenize"

    @property
    def description(self) -> str:
        return "Create and manage ERC-20 tokens on Base L2. Deploy, transfer, approve, mint. All gas fees covered by the platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["deploy", "transfer", "approve", "balance", "info", "mint"],
                },
                "token_name": {"type": "string"},
                "token_symbol": {"type": "string"},
                "initial_supply": {"type": "string", "description": "Initial supply in whole tokens"},
                "contract_address": {"type": "string"},
                "to": {"type": "string"},
                "amount": {"type": "string"},
                "spender": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        handlers = {
            "deploy": self._deploy,
            "transfer": self._transfer,
            "approve": self._approve,
            "balance": self._balance,
            "info": self._info,
            "mint": self._mint,
        }
        handler = handlers.get(action)
        if not handler:
            return f"Unknown tokenization action: {action}"
        return await handler(kwargs)

    async def _deploy(self, params: dict) -> str:
        """Deploy a new ERC-20 token. Gas covered by platform."""
        name = params.get("token_name", "MatrixToken")
        symbol = params.get("token_symbol", "MTRX")
        supply = params.get("initial_supply", "1000000")

        source = f'''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract {symbol}Token is ERC20, Ownable {{
    constructor() ERC20("{name}", "{symbol}") Ownable(msg.sender) {{
        _mint(msg.sender, {supply} * 10 ** decimals());
    }}

    function mint(address to, uint256 amount) public onlyOwner {{
        _mint(to, amount);
    }}
}}'''
        return json.dumps({
            "status": "source_generated",
            "name": name,
            "symbol": symbol,
            "initial_supply": supply,
            "source": source,
            "note": "Use smart_contract deploy action to deploy this contract. Gas covered by platform.",
        }, indent=2)

    async def _transfer(self, params: dict) -> str:
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["contract_address"]),
                abi=ERC20_ABI,
            )
            amount = int(float(params.get("amount", "0")) * 10**18)
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
                "to": params["to"],
                "amount": params.get("amount"),
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Transfer failed: {e}"

    async def _approve(self, params: dict) -> str:
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["contract_address"]),
                abi=ERC20_ABI,
            )
            amount = int(float(params.get("amount", "0")) * 10**18)
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
                "spender": params["spender"],
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Approve failed: {e}"

    async def _balance(self, params: dict) -> str:
        try:
            from web3 import Web3
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["contract_address"]),
                abi=ERC20_ABI,
            )
            addr = params.get("to", self.platform_wallet)
            balance = contract.functions.balanceOf(Web3.to_checksum_address(addr)).call()
            return json.dumps({"balance_raw": str(balance), "balance": str(balance / 10**18)})
        except Exception as e:
            return f"Balance check failed: {e}"

    async def _info(self, params: dict) -> str:
        try:
            from web3 import Web3
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["contract_address"]),
                abi=ERC20_ABI,
            )
            name = contract.functions.name().call()
            symbol = contract.functions.symbol().call()
            supply = contract.functions.totalSupply().call()
            return json.dumps({"name": name, "symbol": symbol, "total_supply": str(supply / 10**18)})
        except Exception as e:
            return f"Info failed: {e}"

    async def _mint(self, params: dict) -> str:
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["contract_address"]),
                abi=ERC20_ABI,
            )
            amount = int(float(params.get("amount", "0")) * 10**18)
            to = params.get("to", bc["platform_wallet"])
            account = Account.from_key(bc["paymaster_private_key"])

            tx = contract.functions.mint(
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
                "status": "minted" if receipt["status"] == 1 else "failed",
                "to": to,
                "amount": params.get("amount"),
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Mint failed: {e}"
