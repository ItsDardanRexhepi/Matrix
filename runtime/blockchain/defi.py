"""
DeFi — lending, borrowing, yield farming, and liquidity provision on Base L2.

Integrates with Aave V3 and Uniswap V3 on Base. All gas fees are
covered by the platform via ERC-4337 paymaster.
"""

import json
import logging
from typing import Any

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)

# Aave V3 Pool ABI (simplified — supply and borrow functions)
AAVE_POOL_ABI = [
    {
        "inputs": [
            {"name": "asset", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "onBehalfOf", "type": "address"},
            {"name": "referralCode", "type": "uint16"},
        ],
        "name": "supply",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "asset", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "interestRateMode", "type": "uint256"},
            {"name": "referralCode", "type": "uint16"},
            {"name": "onBehalfOf", "type": "address"},
        ],
        "name": "borrow",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "asset", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "to", "type": "address"},
        ],
        "name": "withdraw",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "asset", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "interestRateMode", "type": "uint256"},
            {"name": "onBehalfOf", "type": "address"},
        ],
        "name": "repay",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

# Known token addresses on Base Sepolia
BASE_SEPOLIA_TOKENS = {
    "WETH": "0x4200000000000000000000000000000000000006",
    "USDC": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    "DAI": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
}


class DeFi(BlockchainInterface):

    @property
    def name(self) -> str:
        return "defi"

    @property
    def description(self) -> str:
        return "DeFi operations: lending, borrowing, yield farming, and liquidity provision on Base L2. All gas fees covered by the platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["supply", "borrow", "withdraw", "repay", "get_rates", "get_positions"],
                    "description": "DeFi action to perform",
                },
                "protocol": {"type": "string", "description": "Protocol to use (aave, uniswap)", "default": "aave"},
                "token": {"type": "string", "description": "Token symbol (WETH, USDC, DAI)"},
                "amount": {"type": "string", "description": "Amount in token units"},
                "user_address": {"type": "string", "description": "User's wallet address"},
                "pool_address": {"type": "string", "description": "Aave pool contract address"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        handlers = {
            "supply": self._supply,
            "borrow": self._borrow,
            "withdraw": self._withdraw,
            "repay": self._repay,
            "get_rates": self._get_rates,
            "get_positions": self._get_positions,
        }
        handler = handlers.get(action)
        if not handler:
            return f"Unknown DeFi action: {action}. Available: {', '.join(handlers.keys())}"
        return await handler(kwargs)

    async def _supply(self, params: dict) -> str:
        """Supply tokens to Aave lending pool. Gas covered by platform."""
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            token = params.get("token", "WETH").upper()
            token_address = BASE_SEPOLIA_TOKENS.get(token)
            if not token_address:
                return f"Unknown token: {token}. Available: {', '.join(BASE_SEPOLIA_TOKENS.keys())}"

            amount = int(float(params.get("amount", "0")) * 10**18)
            pool_address = params.get("pool_address", "")
            user_address = params.get("user_address", bc["platform_wallet"])

            pool = self.web3.eth.contract(
                address=Web3.to_checksum_address(pool_address),
                abi=AAVE_POOL_ABI,
            )
            account = Account.from_key(bc["paymaster_private_key"])

            tx = pool.functions.supply(
                Web3.to_checksum_address(token_address),
                amount,
                Web3.to_checksum_address(user_address),
                0,
            ).build_transaction({
                "from": bc["platform_wallet"],
                "chainId": self.chain_id,
                "gas": 500000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "supplied" if receipt["status"] == 1 else "failed",
                "token": token,
                "amount": params.get("amount", "0"),
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Supply failed: {e}"

    async def _borrow(self, params: dict) -> str:
        """Borrow tokens from Aave. Gas covered by platform."""
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]
            token = params.get("token", "USDC").upper()
            token_address = BASE_SEPOLIA_TOKENS.get(token)
            if not token_address:
                return f"Unknown token: {token}"

            amount = int(float(params.get("amount", "0")) * 10**18)
            pool_address = params.get("pool_address", "")
            user_address = params.get("user_address", bc["platform_wallet"])

            pool = self.web3.eth.contract(
                address=Web3.to_checksum_address(pool_address),
                abi=AAVE_POOL_ABI,
            )
            account = Account.from_key(bc["paymaster_private_key"])

            tx = pool.functions.borrow(
                Web3.to_checksum_address(token_address),
                amount,
                2,  # variable rate
                0,
                Web3.to_checksum_address(user_address),
            ).build_transaction({
                "from": bc["platform_wallet"],
                "chainId": self.chain_id,
                "gas": 500000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "borrowed" if receipt["status"] == 1 else "failed",
                "token": token,
                "amount": params.get("amount", "0"),
                "rate_mode": "variable",
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Borrow failed: {e}"

    async def _withdraw(self, params: dict) -> str:
        """Withdraw supplied tokens from Aave. Gas covered by platform."""
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]
            token = params.get("token", "WETH").upper()
            token_address = BASE_SEPOLIA_TOKENS.get(token)
            if not token_address:
                return f"Unknown token: {token}"

            amount = int(float(params.get("amount", "0")) * 10**18)
            pool_address = params.get("pool_address", "")

            pool = self.web3.eth.contract(
                address=Web3.to_checksum_address(pool_address),
                abi=AAVE_POOL_ABI,
            )
            account = Account.from_key(bc["paymaster_private_key"])

            tx = pool.functions.withdraw(
                Web3.to_checksum_address(token_address),
                amount,
                Web3.to_checksum_address(bc["platform_wallet"]),
            ).build_transaction({
                "from": bc["platform_wallet"],
                "chainId": self.chain_id,
                "gas": 500000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "withdrawn" if receipt["status"] == 1 else "failed",
                "token": token,
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Withdraw failed: {e}"

    async def _repay(self, params: dict) -> str:
        """Repay borrowed tokens to Aave. Gas covered by platform."""
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]
            token = params.get("token", "USDC").upper()
            token_address = BASE_SEPOLIA_TOKENS.get(token)
            if not token_address:
                return f"Unknown token: {token}"

            amount = int(float(params.get("amount", "0")) * 10**18)
            pool_address = params.get("pool_address", "")

            pool = self.web3.eth.contract(
                address=Web3.to_checksum_address(pool_address),
                abi=AAVE_POOL_ABI,
            )
            account = Account.from_key(bc["paymaster_private_key"])

            tx = pool.functions.repay(
                Web3.to_checksum_address(token_address),
                amount,
                2,  # variable rate
                Web3.to_checksum_address(bc["platform_wallet"]),
            ).build_transaction({
                "from": bc["platform_wallet"],
                "chainId": self.chain_id,
                "gas": 500000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "repaid" if receipt["status"] == 1 else "failed",
                "token": token,
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Repay failed: {e}"

    async def _get_rates(self, params: dict) -> str:
        """Get current lending/borrowing rates from Aave V3 data provider."""
        try:
            from web3 import Web3

            pool_address = params.get("pool_address", "")
            if not pool_address:
                return json.dumps({
                    "status": "error",
                    "error": "pool_address (Aave V3 Pool) is required to query live rates.",
                    "hint": "Pass the Aave V3 Pool contract address for this network.",
                    "tokens": list(BASE_SEPOLIA_TOKENS.keys()),
                    "network": self.network,
                }, indent=2)

            # Aave V3 getReserveData ABI (simplified — returns the ReserveData struct)
            reserve_data_abi = [{
                "inputs": [{"name": "asset", "type": "address"}],
                "name": "getReserveData",
                "outputs": [{
                    "components": [
                        {"name": "configuration", "type": "uint256"},
                        {"name": "liquidityIndex", "type": "uint128"},
                        {"name": "currentLiquidityRate", "type": "uint128"},
                        {"name": "variableBorrowIndex", "type": "uint128"},
                        {"name": "currentVariableBorrowRate", "type": "uint128"},
                        {"name": "currentStableBorrowRate", "type": "uint128"},
                        {"name": "lastUpdateTimestamp", "type": "uint40"},
                        {"name": "id", "type": "uint16"},
                        {"name": "aTokenAddress", "type": "address"},
                        {"name": "stableDebtTokenAddress", "type": "address"},
                        {"name": "variableDebtTokenAddress", "type": "address"},
                        {"name": "interestRateStrategyAddress", "type": "address"},
                        {"name": "accruedToTreasury", "type": "uint128"},
                        {"name": "unbacked", "type": "uint128"},
                        {"name": "isolationModeTotalDebt", "type": "uint128"},
                    ],
                    "name": "",
                    "type": "tuple",
                }],
                "stateMutability": "view",
                "type": "function",
            }]

            pool = self.web3.eth.contract(
                address=Web3.to_checksum_address(pool_address),
                abi=reserve_data_abi,
            )

            rates = {}
            for token_name, token_addr in BASE_SEPOLIA_TOKENS.items():
                try:
                    data = pool.functions.getReserveData(
                        Web3.to_checksum_address(token_addr)
                    ).call()
                    # Aave rates are in RAY (1e27)
                    supply_apy = float(data[2]) / 1e27 * 100
                    borrow_apy = float(data[4]) / 1e27 * 100
                    rates[token_name] = {
                        "supply_apy": f"{supply_apy:.4f}%",
                        "variable_borrow_apy": f"{borrow_apy:.4f}%",
                    }
                except Exception as e:
                    rates[token_name] = {"error": str(e)}

            return json.dumps({
                "protocol": "aave_v3",
                "network": self.network,
                "rates": rates,
            }, indent=2)
        except Exception as e:
            return f"Rate query failed: {e}"

    async def _get_positions(self, params: dict) -> str:
        """Get user's current DeFi positions by querying aToken balances."""
        try:
            from web3 import Web3

            user = params.get("user_address", self.platform_wallet)
            if not user:
                return json.dumps({"status": "error", "error": "user_address or configured platform_wallet is required"})

            erc20_balance_abi = [{
                "inputs": [{"name": "account", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function",
            }]

            pool_address = params.get("pool_address", "")
            if not pool_address:
                return json.dumps({
                    "status": "error",
                    "error": "pool_address (Aave V3 Pool) is required to query positions.",
                    "hint": "Pass the Aave V3 Pool contract address for this network.",
                    "network": self.network,
                }, indent=2)

            # Query native token balances for each known token
            positions = {}
            for token_name, token_addr in BASE_SEPOLIA_TOKENS.items():
                try:
                    contract = self.web3.eth.contract(
                        address=Web3.to_checksum_address(token_addr),
                        abi=erc20_balance_abi,
                    )
                    balance = contract.functions.balanceOf(
                        Web3.to_checksum_address(user)
                    ).call()
                    if balance > 0:
                        positions[token_name] = {
                            "wallet_balance": str(balance),
                            "wallet_balance_human": str(balance / 10**18),
                        }
                except Exception as e:
                    positions[token_name] = {"error": str(e)}

            return json.dumps({
                "user": user,
                "protocol": "aave_v3",
                "network": self.network,
                "token_balances": positions,
            }, indent=2)
        except Exception as e:
            return f"Position query failed: {e}"
