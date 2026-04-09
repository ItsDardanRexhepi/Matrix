"""
DEXService — native decentralized exchange for the 0pnMatrx platform.

Uniswap wrapper with native constant-product AMM fallback.
ZERO FEES to users (platform absorbs gas costs).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.dex.pools import LiquidityPoolManager
from runtime.blockchain.services.dex.router import SwapRouter
from runtime.blockchain.web3_manager import Web3Manager, not_deployed_response

logger = logging.getLogger(__name__)


class DEXService:
    """Native DEX service with zero user fees.

    Gas costs are absorbed by the platform. Users pay nothing for swaps.

    Config keys (under ``config["dex"]``):
        platform_wallet (str): Wallet that absorbs gas costs.
        All keys from LiquidityPoolManager and SwapRouter are also supported.

    Config keys (under ``config["blockchain"]``):
        platform_wallet (str): Fallback platform wallet.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        d_cfg: dict[str, Any] = config.get("dex", {})
        bc_cfg: dict[str, Any] = config.get("blockchain", {})

        self._platform_wallet: str = (
            d_cfg.get("platform_wallet", "")
            or bc_cfg.get("platform_wallet", "")
        )
        self._dex_router_contract: str = d_cfg.get("router_contract", "") or ""
        self._web3 = Web3Manager.get_shared(config)

        self._pools = LiquidityPoolManager(config)
        self._router = SwapRouter(config, self._pools)

        # Trade history
        self._trades: list[dict[str, Any]] = []
        # (provider, pool_id) -> position tracking
        self._user_positions: dict[str, list[dict]] = {}

        logger.info("DEXService initialised (zero-fee mode, gas absorbed by platform).")

    @property
    def pools(self) -> LiquidityPoolManager:
        return self._pools

    @property
    def router(self) -> SwapRouter:
        return self._router

    # ------------------------------------------------------------------
    # Swap operations
    # ------------------------------------------------------------------

    async def swap(
        self,
        trader: str,
        token_in: str,
        token_out: str,
        amount_in: float,
        slippage: float = 0.5,
    ) -> dict:
        """Execute a token swap with zero fees to the user.

        Platform absorbs all gas costs.

        Args:
            trader: Trader wallet address.
            token_in: Token to sell.
            token_out: Token to buy.
            amount_in: Amount of token_in to swap.
            slippage: Maximum slippage tolerance in percent (default 0.5%).

        Returns:
            Trade execution result.
        """
        if not trader:
            raise ValueError("Trader address is required")
        if amount_in <= 0:
            raise ValueError("Swap amount must be positive")
        if not 0 <= slippage <= 50:
            raise ValueError("Slippage must be between 0 and 50 percent")

        if (
            not self._web3.available
            or self._web3.is_placeholder(self._dex_router_contract)
        ):
            logger.warning(
                "Service %s called but contract not deployed",
                self.__class__.__name__,
            )
            return not_deployed_response("dex", {
                "operation": "swap",
                "requested": {
                    "trader": trader,
                    "token_in": token_in,
                    "token_out": token_out,
                    "amount_in": amount_in,
                },
            })

        # Find best route
        route = await self._router.find_best_route(token_in, token_out, amount_in)
        if not route.get("found"):
            raise ValueError(
                f"No swap route found from {token_in} to {token_out}: "
                f"{route.get('reason', 'unknown')}"
            )

        # Slippage check
        expected_output = route["expected_output"]
        min_output = expected_output * (1 - slippage / 100)

        # Execute the swap along the route
        current_amount = amount_in
        executed_pools = []

        for i, pool_id in enumerate(route["pools"]):
            hop_token_in = route["route"][i]
            result = self._pools.execute_swap(pool_id, hop_token_in, current_amount)
            current_amount = result["amount_out"]
            executed_pools.append({
                "pool_id": pool_id,
                "token_in": hop_token_in,
                "token_out": route["route"][i + 1],
                "amount_in": current_amount if i == 0 else result["amount_out"],
                "amount_out": result["amount_out"],
            })

        actual_output = current_amount

        # Verify slippage
        if actual_output < min_output:
            raise ValueError(
                f"Slippage exceeded: expected >= {min_output:.6f}, "
                f"got {actual_output:.6f}"
            )

        trade = {
            "trade_id": str(uuid.uuid4()),
            "trader": trader,
            "token_in": token_in,
            "token_out": token_out,
            "amount_in": amount_in,
            "amount_out": actual_output,
            "effective_price": actual_output / amount_in if amount_in > 0 else 0,
            "price_impact_pct": route.get("price_impact_pct", 0),
            "route": route["route"],
            "hops": route["hops"],
            "slippage_tolerance": slippage,
            "user_fee": 0.0,  # ZERO FEES to users
            "gas_absorbed_by": self._platform_wallet,
            "executed_at": int(time.time()),
            "status": "confirmed",
        }

        self._trades.append(trade)
        logger.info(
            "Swap executed: trader=%s %s %.6f %s -> %.6f %s (0 user fees)",
            trader, token_in, amount_in, token_out, actual_output, token_out,
        )
        return trade

    async def get_quote(
        self, token_in: str, token_out: str, amount: float
    ) -> dict:
        """Get a price quote without executing.

        Returns:
            Quote with expected output, price impact, and route.
        """
        if amount <= 0:
            raise ValueError("Quote amount must be positive")

        route = await self._router.find_best_route(token_in, token_out, amount)
        if not route.get("found"):
            return {
                "token_in": token_in,
                "token_out": token_out,
                "amount_in": amount,
                "available": False,
                "reason": route.get("reason", "No route found"),
            }

        return {
            "token_in": token_in,
            "token_out": token_out,
            "amount_in": amount,
            "expected_output": route["expected_output"],
            "effective_price": route["effective_price"],
            "price_impact_pct": route["price_impact_pct"],
            "route": route["route"],
            "hops": route["hops"],
            "user_fee": 0.0,  # ZERO FEES
            "available": True,
            "warning": route.get("warning"),
        }

    # ------------------------------------------------------------------
    # Liquidity operations
    # ------------------------------------------------------------------

    async def add_liquidity(
        self,
        provider: str,
        token_a: str,
        token_b: str,
        amount_a: float,
        amount_b: float,
    ) -> dict:
        """Add liquidity to a pool (creates pool if it doesn't exist).

        Args:
            provider: Liquidity provider wallet address.
            token_a: First token.
            token_b: Second token.
            amount_a: Amount of token_a.
            amount_b: Amount of token_b.

        Returns:
            LP position details.
        """
        if not provider:
            raise ValueError("Provider address is required")
        if amount_a <= 0 or amount_b <= 0:
            raise ValueError("Both amounts must be positive")

        # Find or create pool
        pool = self._pools.get_pool_by_pair(token_a, token_b)
        if pool is None:
            pool = await self._pools.create_pool(token_a, token_b)

        result = await self._pools.add_liquidity(
            pool["pool_id"], provider, amount_a, amount_b
        )

        # Track user positions
        self._user_positions.setdefault(provider, []).append({
            "type": "add_liquidity",
            "pool_id": pool["pool_id"],
            "amount_a": amount_a,
            "amount_b": amount_b,
            "timestamp": int(time.time()),
        })

        logger.info(
            "Liquidity added: provider=%s pool=%s", provider, pool["pool_id"],
        )
        return result

    async def remove_liquidity(
        self, provider: str, pool_id: str, percentage: float
    ) -> dict:
        """Remove liquidity from a pool.

        Args:
            provider: LP wallet address.
            pool_id: Pool identifier.
            percentage: 0-100, percentage of position to remove.

        Returns:
            Withdrawal details.
        """
        if not provider:
            raise ValueError("Provider address is required")

        result = await self._pools.remove_liquidity(pool_id, provider, percentage)

        self._user_positions.setdefault(provider, []).append({
            "type": "remove_liquidity",
            "pool_id": pool_id,
            "percentage": percentage,
            "timestamp": int(time.time()),
        })

        logger.info(
            "Liquidity removed: provider=%s pool=%s pct=%.1f%%",
            provider, pool_id, percentage,
        )
        return result

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    async def get_positions(self, address: str) -> list:
        """Get all LP positions for an address."""
        return self._user_positions.get(address, [])

    def get_trades(self, trader: str | None = None, limit: int = 50) -> list:
        """Get trade history, optionally filtered by trader."""
        if trader:
            filtered = [t for t in self._trades if t["trader"] == trader]
        else:
            filtered = list(self._trades)
        filtered.sort(key=lambda t: t["executed_at"], reverse=True)
        return filtered[:limit]
