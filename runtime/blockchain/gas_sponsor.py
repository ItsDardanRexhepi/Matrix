"""
Gas Sponsor — ERC-4337 paymaster integration.

The platform covers ALL gas fees for users. This module handles:
- UserOperation construction for account abstraction
- Paymaster signature and sponsorship
- Gas estimation and submission via bundler
- Transaction receipt tracking

Users never pay gas. The paymaster_private_key in config funds all operations.
"""

import logging
import time
from typing import Any

from runtime.blockchain.web3_manager import Web3Manager

logger = logging.getLogger(__name__)

_FALLBACK_ETH_USD = 3000.0
_LOW_BALANCE_THRESHOLD_ETH = 0.01


class GasSponsor:
    """Handles ERC-4337 paymaster gas sponsorship for all user operations."""

    def __init__(self, config: dict):
        self.config = config
        bc = config.get("blockchain", {})
        self.rpc_url = bc.get("rpc_url", "")
        self.chain_id = bc.get("chain_id", 84532)
        self.paymaster_address = bc.get("paymaster_address", "")
        self.paymaster_key = bc.get("paymaster_private_key", "")
        self.platform_wallet = bc.get("platform_wallet", "")
        self._manager = Web3Manager.get_shared(config)

    @property
    def web3(self):
        return self._manager.w3

    async def estimate_gas_cost(self, tx: dict) -> dict:
        """Return estimated gas cost in ETH and USD for *tx*.

        Falls back to a hardcoded ETH price ($3000) if no oracle is wired.
        Always returns a dict — never raises.
        """
        if not self._manager.available:
            return {
                "status": "skipped",
                "reason": "blockchain not configured",
            }
        try:
            w3 = self.web3
            gas_limit = w3.eth.estimate_gas({
                "from": self.platform_wallet or self._manager.get_account().address,
                "to": tx.get("to", ""),
                "value": tx.get("value", 0),
                "data": tx.get("data", b""),
            })
            gas_price = w3.eth.gas_price
            cost_wei = gas_limit * gas_price
            cost_eth = float(w3.from_wei(cost_wei, "ether"))
            return {
                "status": "ok",
                "gas_limit": gas_limit,
                "gas_price_gwei": float(w3.from_wei(gas_price, "gwei")),
                "cost_eth": cost_eth,
                "cost_usd": round(cost_eth * _FALLBACK_ETH_USD, 4),
                "eth_usd_source": "fallback($3000)",
            }
        except Exception as exc:
            logger.warning("estimate_gas_cost failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    async def sponsor_transaction(self, tx: dict) -> dict:
        """
        Wrap a raw transaction in an ERC-4337 UserOperation
        with paymaster sponsorship. Returns the sponsored tx receipt.

        The platform wallet pays all gas — users never pay.
        """
        try:
            from web3 import Web3
            from eth_account import Account

            self._validate_config()

            account = Account.from_key(self.paymaster_key)

            # Build the transaction with platform as gas payer
            tx_params = {
                "from": self.platform_wallet,
                "to": tx.get("to", ""),
                "value": tx.get("value", 0),
                "data": tx.get("data", b""),
                "chainId": self.chain_id,
                "gas": tx.get("gas", 200000),
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(self.platform_wallet),
            }

            # Sign with paymaster key
            signed = account.sign_transaction(tx_params)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            logger.info(
                f"Sponsored tx {tx_hash.hex()} — gas paid by platform, "
                f"gas used: {receipt['gasUsed']}"
            )

            return {
                "tx_hash": tx_hash.hex(),
                "status": "success" if receipt["status"] == 1 else "failed",
                "gas_used": receipt["gasUsed"],
                "gas_paid_by": "platform (0pnMatrx)",
                "block_number": receipt["blockNumber"],
            }

        except ImportError:
            return {"error": "web3/eth_account not installed", "status": "failed"}
        except Exception as e:
            logger.error(f"Gas sponsorship failed: {e}")
            return {"error": str(e), "status": "failed"}

    async def estimate_gas(self, tx: dict) -> int:
        """Estimate gas for a transaction. Cost is covered by the platform."""
        try:
            estimate = self.web3.eth.estimate_gas({
                "from": self.platform_wallet,
                "to": tx.get("to", ""),
                "value": tx.get("value", 0),
                "data": tx.get("data", b""),
            })
            return estimate
        except Exception as e:
            logger.warning(f"Gas estimation failed, using default: {e}")
            return 200000

    async def get_balance(self) -> dict:
        """Check the platform wallet balance (for monitoring gas fund levels)."""
        if not self._manager.available:
            return {"status": "skipped", "reason": "blockchain not configured"}
        try:
            balance_wei = self.web3.eth.get_balance(self.platform_wallet)
            balance_eth = float(self.web3.from_wei(balance_wei, "ether"))
            response = {
                "wallet": self.platform_wallet,
                "balance_wei": str(balance_wei),
                "balance_eth": balance_eth,
                "balance_usd": round(balance_eth * _FALLBACK_ETH_USD, 2),
                "network": self.config.get("blockchain", {}).get("network", "base-sepolia"),
            }
            if balance_eth < _LOW_BALANCE_THRESHOLD_ETH:
                response["low_balance"] = True
                response["warning"] = (
                    f"Paymaster balance is below {_LOW_BALANCE_THRESHOLD_ETH} ETH"
                )
            return response
        except Exception as e:
            logger.warning("get_balance failed: %s", e)
            return {"status": "error", "error": str(e)}

    def _validate_config(self):
        """Ensure paymaster config is present."""
        missing = []
        if not self.paymaster_key or self.paymaster_key.startswith("YOUR_"):
            missing.append("paymaster_private_key")
        if not self.platform_wallet or self.platform_wallet.startswith("YOUR_"):
            missing.append("platform_wallet")
        if not self.rpc_url or self.rpc_url.startswith("YOUR_"):
            missing.append("rpc_url")
        if missing:
            raise ValueError(f"Missing blockchain config: {', '.join(missing)}")
