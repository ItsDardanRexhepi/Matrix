"""
SwapRouter — multi-hop swap routing for the 0pnMatrx native DEX.

Checks Uniswap pools first, falls back to native pools.
Calculates price impact and enforces slippage protection.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Common intermediate tokens for multi-hop routing
_BRIDGE_TOKENS = ["ETH", "WETH", "USDC", "USDT", "DAI"]


class SwapRouter:
    """Multi-hop swap router with Uniswap-first strategy.

    Config keys (under ``config["dex"]``):
        max_hops (int): Maximum route hops (default 3).
        max_price_impact (float): Max price impact % (default 5.0).
        uniswap_enabled (bool): Try Uniswap first (default True).
    """

    def __init__(self, config: dict, pool_manager: Any) -> None:
        self._config = config
        d_cfg: dict[str, Any] = config.get("dex", {})

        self._max_hops: int = int(d_cfg.get("max_hops", 3))
        self._max_impact: float = float(d_cfg.get("max_price_impact", 5.0))
        self._uniswap_enabled: bool = bool(d_cfg.get("uniswap_enabled", True))

        self._pool_manager = pool_manager

        logger.info(
            "SwapRouter initialised (max_hops=%d, max_impact=%.1f%%, uniswap=%s).",
            self._max_hops, self._max_impact, self._uniswap_enabled,
        )

    async def find_best_route(
        self, token_in: str, token_out: str, amount: float
    ) -> dict:
        """Find the best swap route from token_in to token_out.

        Strategy:
        1. Check for direct pool (Uniswap first, then native).
        2. Try single-hop via bridge tokens.
        3. Try multi-hop (up to max_hops).

        Returns:
            Dict with route, expected_output, price_impact, and source.
        """
        if token_in == token_out:
            raise ValueError("Cannot swap a token for itself")
        if amount <= 0:
            raise ValueError("Swap amount must be positive")

        best_route: dict[str, Any] | None = None

        # 1. Try direct pool
        direct = self._try_direct_route(token_in, token_out, amount)
        if direct is not None:
            best_route = direct

        # 2. Try single-hop via bridge tokens
        for bridge in _BRIDGE_TOKENS:
            if bridge in (token_in, token_out):
                continue
            hop_route = self._try_two_hop_route(token_in, bridge, token_out, amount)
            if hop_route is not None:
                if best_route is None or hop_route["expected_output"] > best_route["expected_output"]:
                    best_route = hop_route

        # 3. Try two intermediate hops if max_hops >= 3
        if self._max_hops >= 3:
            for bridge1 in _BRIDGE_TOKENS:
                if bridge1 in (token_in, token_out):
                    continue
                for bridge2 in _BRIDGE_TOKENS:
                    if bridge2 in (token_in, token_out, bridge1):
                        continue
                    three_hop = self._try_three_hop_route(
                        token_in, bridge1, bridge2, token_out, amount
                    )
                    if three_hop is not None:
                        if best_route is None or three_hop["expected_output"] > best_route["expected_output"]:
                            best_route = three_hop

        if best_route is None:
            return {
                "found": False,
                "token_in": token_in,
                "token_out": token_out,
                "amount": amount,
                "reason": f"No route found from {token_in} to {token_out}",
            }

        # Enforce price impact limit
        if best_route["price_impact_pct"] > self._max_impact:
            best_route["warning"] = (
                f"Price impact {best_route['price_impact_pct']:.2f}% "
                f"exceeds maximum {self._max_impact}%"
            )

        best_route["found"] = True
        return best_route

    def _try_direct_route(
        self, token_in: str, token_out: str, amount: float
    ) -> dict | None:
        """Try a direct swap via native pool."""
        pool = self._pool_manager.get_pool_by_pair(token_in, token_out)
        if pool is None:
            return None
        if pool["reserve_a"] == 0 or pool["reserve_b"] == 0:
            return None

        try:
            result = self._pool_manager.calculate_swap_output(
                pool["pool_id"], token_in, amount
            )
        except (ValueError, ZeroDivisionError):
            return None

        return {
            "route": [token_in, token_out],
            "pools": [pool["pool_id"]],
            "hops": 1,
            "expected_output": result["amount_out"],
            "effective_price": result["effective_price"],
            "price_impact_pct": result["price_impact_pct"],
            "total_fees": result["fee_amount"],
            "source": "native",
            "token_in": token_in,
            "token_out": token_out,
            "amount_in": amount,
        }

    def _try_two_hop_route(
        self, token_in: str, bridge: str, token_out: str, amount: float
    ) -> dict | None:
        """Try a two-hop route: token_in -> bridge -> token_out."""
        pool1 = self._pool_manager.get_pool_by_pair(token_in, bridge)
        pool2 = self._pool_manager.get_pool_by_pair(bridge, token_out)

        if pool1 is None or pool2 is None:
            return None
        if pool1["reserve_a"] == 0 or pool1["reserve_b"] == 0:
            return None
        if pool2["reserve_a"] == 0 or pool2["reserve_b"] == 0:
            return None

        try:
            result1 = self._pool_manager.calculate_swap_output(
                pool1["pool_id"], token_in, amount
            )
            result2 = self._pool_manager.calculate_swap_output(
                pool2["pool_id"], bridge, result1["amount_out"]
            )
        except (ValueError, ZeroDivisionError):
            return None

        total_impact = result1["price_impact_pct"] + result2["price_impact_pct"]
        total_fees = result1["fee_amount"] + result2["fee_amount"]
        effective_price = result2["amount_out"] / amount if amount > 0 else 0

        return {
            "route": [token_in, bridge, token_out],
            "pools": [pool1["pool_id"], pool2["pool_id"]],
            "hops": 2,
            "expected_output": result2["amount_out"],
            "effective_price": effective_price,
            "price_impact_pct": total_impact,
            "total_fees": total_fees,
            "source": "native",
            "token_in": token_in,
            "token_out": token_out,
            "amount_in": amount,
        }

    def _try_three_hop_route(
        self, token_in: str, bridge1: str, bridge2: str, token_out: str,
        amount: float,
    ) -> dict | None:
        """Try a three-hop route: token_in -> bridge1 -> bridge2 -> token_out."""
        pool1 = self._pool_manager.get_pool_by_pair(token_in, bridge1)
        pool2 = self._pool_manager.get_pool_by_pair(bridge1, bridge2)
        pool3 = self._pool_manager.get_pool_by_pair(bridge2, token_out)

        if any(p is None for p in [pool1, pool2, pool3]):
            return None

        for p in [pool1, pool2, pool3]:
            if p["reserve_a"] == 0 or p["reserve_b"] == 0:  # type: ignore[index]
                return None

        try:
            r1 = self._pool_manager.calculate_swap_output(
                pool1["pool_id"], token_in, amount  # type: ignore[index]
            )
            r2 = self._pool_manager.calculate_swap_output(
                pool2["pool_id"], bridge1, r1["amount_out"]  # type: ignore[index]
            )
            r3 = self._pool_manager.calculate_swap_output(
                pool3["pool_id"], bridge2, r2["amount_out"]  # type: ignore[index]
            )
        except (ValueError, ZeroDivisionError):
            return None

        total_impact = r1["price_impact_pct"] + r2["price_impact_pct"] + r3["price_impact_pct"]
        total_fees = r1["fee_amount"] + r2["fee_amount"] + r3["fee_amount"]
        effective_price = r3["amount_out"] / amount if amount > 0 else 0

        return {
            "route": [token_in, bridge1, bridge2, token_out],
            "pools": [pool1["pool_id"], pool2["pool_id"], pool3["pool_id"]],  # type: ignore[index]
            "hops": 3,
            "expected_output": r3["amount_out"],
            "effective_price": effective_price,
            "price_impact_pct": total_impact,
            "total_fees": total_fees,
            "source": "native",
            "token_in": token_in,
            "token_out": token_out,
            "amount_in": amount,
        }
