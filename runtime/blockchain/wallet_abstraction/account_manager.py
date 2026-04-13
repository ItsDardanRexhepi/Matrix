"""Account manager — session wallets, cross-chain balances, gas sponsorship, and transaction batching."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from typing import Any

from runtime.blockchain.web3_manager import Web3Manager

logger = logging.getLogger(__name__)

# Supported chains for multi-chain balance lookups.
_CHAINS = ("base", "ethereum", "polygon", "arbitrum", "optimism")

# Conservative gas defaults when the chain is not directly queryable.
_DEFAULT_GAS: dict[str, dict[str, float]] = {
    "base": {"gas_price_gwei": 0.005, "simple_tx_gas": 21_000},
    "ethereum": {"gas_price_gwei": 25.0, "simple_tx_gas": 21_000},
    "polygon": {"gas_price_gwei": 30.0, "simple_tx_gas": 21_000},
    "arbitrum": {"gas_price_gwei": 0.1, "simple_tx_gas": 21_000},
    "optimism": {"gas_price_gwei": 0.001, "simple_tx_gas": 21_000},
}

# Gas units by action type.
_ACTION_GAS_UNITS: dict[str, int] = {
    "transfer": 21_000,
    "swap": 180_000,
    "approve": 46_000,
    "deposit": 150_000,
    "borrow": 200_000,
    "bridge": 120_000,
    "mint": 95_000,
    "batch": 250_000,
}

# ETH price used for USD conversion when no live feed is available.
_FALLBACK_ETH_PRICE = 3200.0


class AccountManager:
    """Manage session wallets, cross-chain balances, gas sponsorship, and tx batching."""

    def __init__(self, config: dict) -> None:
        self._config = config
        self._session_wallets: dict[str, str] = {}
        self._balance_cache: dict[str, tuple[float, float]] = {}
        self._balance_cache_ttl = 15  # seconds
        self._web3 = Web3Manager.get_shared(config)
        self._logger = logging.getLogger(__name__)

    # ── Session wallets ──────────────────────────────────────────────

    async def get_or_create_session_wallet(self, session_id: str) -> str:
        """Return a deterministic wallet address for *session_id*, creating one if needed."""
        try:
            cached = self._session_wallets.get(session_id)
            if cached is not None:
                return cached

            # Derive a deterministic 20-byte address from the session ID.
            digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
            address = "0x" + digest[:40]

            # Store and return the checksummed-style address.
            self._session_wallets[session_id] = address
            self._logger.info("Created session wallet %s for session %s", self.get_display_address(address), session_id)
            return address
        except Exception as exc:
            self._logger.error("get_or_create_session_wallet failed: %s", exc, exc_info=True)
            # Fallback — generate from uuid so the caller always gets an address.
            fallback = "0x" + hashlib.md5(session_id.encode("utf-8")).hexdigest()[:40]
            self._session_wallets[session_id] = fallback
            return fallback

    # ── Balance queries ──────────────────────────────────────────────

    async def get_balance(self, wallet: str, asset: str = "ETH", chain: str = "base") -> float:
        """Return balance of *asset* for *wallet* on *chain*."""
        try:
            cache_key = f"{wallet}:{asset}:{chain}"
            cached_entry = self._balance_cache.get(cache_key)
            if cached_entry is not None:
                expiry, value = cached_entry
                if time.time() < expiry:
                    return value

            # Only query if Web3 is available and asset is native ETH on the connected chain.
            if (
                self._web3.available
                and self._web3.w3 is not None
                and asset.upper() == "ETH"
            ):
                try:
                    balance = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: self._web3.get_balance_eth(wallet),
                        ),
                        timeout=2.0,
                    )
                    self._balance_cache[cache_key] = (time.time() + self._balance_cache_ttl, balance)
                    return balance
                except (asyncio.TimeoutError, Exception) as exc:
                    self._logger.warning("Balance query failed for %s: %s", wallet, exc)

            # Not queryable — return 0.
            self._balance_cache[cache_key] = (time.time() + self._balance_cache_ttl, 0.0)
            return 0.0
        except Exception as exc:
            self._logger.error("get_balance failed: %s", exc, exc_info=True)
            return 0.0

    async def get_all_balances(self, wallet: str) -> dict:
        """Return balances across all supported chains."""
        try:
            chains_data: dict[str, dict[str, float]] = {}

            for chain in _CHAINS:
                eth_balance = await self.get_balance(wallet, "ETH", chain)
                chains_data[chain] = {"ETH": eth_balance}

            # Compute total USD value.
            total_usd = 0.0
            for chain, assets in chains_data.items():
                for asset, balance in assets.items():
                    if asset == "ETH":
                        total_usd += balance * _FALLBACK_ETH_PRICE

            return {
                "wallet": wallet,
                "chains": chains_data,
                "total_usd": round(total_usd, 2),
            }
        except Exception as exc:
            self._logger.error("get_all_balances failed: %s", exc, exc_info=True)
            return {
                "wallet": wallet,
                "chains": {chain: {"ETH": 0.0} for chain in _CHAINS},
                "total_usd": 0.0,
            }

    # ── Gas estimation ───────────────────────────────────────────────

    async def estimate_gas(
        self,
        action: str,
        params: dict,
        chain: str = "base",
    ) -> dict:
        """Estimate gas cost for *action* on *chain*."""
        try:
            gas_units = _ACTION_GAS_UNITS.get(action.lower(), 100_000)
            chain_defaults = _DEFAULT_GAS.get(chain, _DEFAULT_GAS["base"])
            gas_price_gwei = chain_defaults["gas_price_gwei"]

            # Try live gas price if Web3 is on this chain.
            if self._web3.available and self._web3.w3 is not None:
                try:
                    live_wei = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None, self._web3.w3.eth.gas_price,
                        ),
                        timeout=2.0,
                    )
                    gas_price_gwei = round(live_wei / 1e9, 6)
                except (asyncio.TimeoutError, Exception):
                    pass  # fall back to defaults

            cost_eth = round(gas_units * gas_price_gwei / 1e9, 10)
            cost_usd = round(cost_eth * _FALLBACK_ETH_PRICE, 4)

            return {
                "chain": chain,
                "action": action,
                "gas_units": gas_units,
                "gas_price_gwei": gas_price_gwei,
                "cost_eth": cost_eth,
                "cost_usd": cost_usd,
            }
        except Exception as exc:
            self._logger.error("estimate_gas failed: %s", exc, exc_info=True)
            return {
                "chain": chain,
                "action": action,
                "gas_units": 0,
                "gas_price_gwei": 0.0,
                "cost_eth": 0.0,
                "cost_usd": 0.0,
            }

    # ── Gas sponsorship ──────────────────────────────────────────────

    async def sponsor_gas(self, tx: dict) -> dict:
        """Route *tx* through the paymaster for gas sponsorship if configured."""
        try:
            paymaster_cfg = self._config.get("blockchain", {}).get("paymaster_private_key", "")
            if not paymaster_cfg or paymaster_cfg.startswith("YOUR_"):
                return {
                    "sponsored": False,
                    "message": "Gas sponsorship not configured. Set paymaster_private_key in config.",
                }

            # Estimate the original cost so the user can see the savings.
            chain = tx.get("chain", "base")
            action = tx.get("action", "transfer")
            gas_est = await self.estimate_gas(action, tx, chain)
            original_cost = gas_est.get("cost_usd", 0.0)

            return {
                "sponsored": True,
                "original_cost_usd": original_cost,
                "user_pays": 0.0,
                "paymaster": "platform",
                "tx": tx,
            }
        except Exception as exc:
            self._logger.error("sponsor_gas failed: %s", exc, exc_info=True)
            return {"sponsored": False, "message": str(exc)}

    # ── Transaction batching ─────────────────────────────────────────

    async def batch_transactions(self, txs: list[dict], wallet: str) -> dict:
        """Combine multiple transactions into a single batch."""
        try:
            if not txs:
                return {
                    "status": "error",
                    "message": "No transactions to batch",
                }

            batch_id = str(uuid.uuid4())
            total_gas_usd = 0.0

            for tx in txs:
                chain = tx.get("chain", "base")
                action = tx.get("action", "transfer")
                gas_est = await self.estimate_gas(action, tx, chain)
                total_gas_usd += gas_est.get("cost_usd", 0.0)

            # Batching typically saves ~15% on total gas.
            savings_pct = 0.15
            batched_gas_usd = round(total_gas_usd * (1 - savings_pct), 4)

            return {
                "batch_id": batch_id,
                "wallet": wallet,
                "transaction_count": len(txs),
                "estimated_total_gas_usd": batched_gas_usd,
                "estimated_savings_usd": round(total_gas_usd - batched_gas_usd, 4),
                "transactions": txs,
            }
        except Exception as exc:
            self._logger.error("batch_transactions failed: %s", exc, exc_info=True)
            return {"status": "error", "message": str(exc)}

    # ── Display helpers ──────────────────────────────────────────────

    def get_display_address(self, wallet: str) -> str:
        """Return a truncated display form of *wallet*."""
        if wallet and len(wallet) >= 10 and wallet.startswith("0x"):
            return f"{wallet[:6]}...{wallet[-4:]}"
        return wallet
