"""
Staking — stake and unstake tokens on Base L2.

Supports staking to validator contracts and staking pools.
All gas fees covered by the platform.
"""

import json
import logging

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)

STAKING_ABI = [
    {"inputs": [{"name": "amount", "type": "uint256"}], "name": "stake", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "amount", "type": "uint256"}], "name": "unstake", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [], "name": "claimRewards", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "stakedBalance", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "earned", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]


class Staking(BlockchainInterface):

    @property
    def name(self) -> str:
        return "stake"

    @property
    def description(self) -> str:
        return "Stake and unstake tokens, claim rewards on Base L2. Gas covered by platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["stake", "unstake", "claim_rewards", "get_staked", "get_rewards"]},
                "staking_contract": {"type": "string"},
                "amount": {"type": "string"},
                "address": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "stake":
            return await self._stake(kwargs)
        elif action == "unstake":
            return await self._unstake(kwargs)
        elif action == "claim_rewards":
            return await self._claim_rewards(kwargs)
        elif action == "get_staked":
            return await self._get_staked(kwargs)
        elif action == "get_rewards":
            return await self._get_rewards(kwargs)
        return f"Unknown staking action: {action}"

    async def _stake(self, params: dict) -> str:
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["staking_contract"]),
                abi=STAKING_ABI,
            )
            amount = int(float(params.get("amount", "0")) * 10**18)
            account = Account.from_key(bc["paymaster_private_key"])

            tx = contract.functions.stake(amount).build_transaction({
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
                "status": "staked" if receipt["status"] == 1 else "failed",
                "amount": params.get("amount"),
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Stake failed: {e}"

    async def _unstake(self, params: dict) -> str:
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["staking_contract"]),
                abi=STAKING_ABI,
            )
            amount = int(float(params.get("amount", "0")) * 10**18)
            account = Account.from_key(bc["paymaster_private_key"])

            tx = contract.functions.unstake(amount).build_transaction({
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
                "status": "unstaked" if receipt["status"] == 1 else "failed",
                "amount": params.get("amount"),
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Unstake failed: {e}"

    async def _claim_rewards(self, params: dict) -> str:
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["staking_contract"]),
                abi=STAKING_ABI,
            )
            account = Account.from_key(bc["paymaster_private_key"])

            tx = contract.functions.claimRewards().build_transaction({
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
                "status": "claimed" if receipt["status"] == 1 else "failed",
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Claim failed: {e}"

    async def _get_staked(self, params: dict) -> str:
        try:
            from web3 import Web3
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["staking_contract"]),
                abi=STAKING_ABI,
            )
            addr = params.get("address", self.platform_wallet)
            staked = contract.functions.stakedBalance(Web3.to_checksum_address(addr)).call()
            return json.dumps({"staked": str(staked / 10**18), "address": addr})
        except Exception as e:
            return f"Staked balance check failed: {e}"

    async def _get_rewards(self, params: dict) -> str:
        try:
            from web3 import Web3
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["staking_contract"]),
                abi=STAKING_ABI,
            )
            addr = params.get("address", self.platform_wallet)
            rewards = contract.functions.earned(Web3.to_checksum_address(addr)).call()
            return json.dumps({"pending_rewards": str(rewards / 10**18), "address": addr})
        except Exception as e:
            return f"Rewards check failed: {e}"
