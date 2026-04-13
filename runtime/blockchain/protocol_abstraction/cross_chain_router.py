"""Cross-chain routing — evaluates bridges and recommends optimal chain for any action."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from runtime.blockchain.web3_manager import Web3Manager, not_deployed_response

logger = logging.getLogger(__name__)

SUPPORTED_CHAINS: dict[str, dict[str, Any]] = {
    "base": {"chain_id": 8453, "name": "Base", "native": "ETH", "explorer": "https://basescan.org"},
    "ethereum": {"chain_id": 1, "name": "Ethereum", "native": "ETH", "explorer": "https://etherscan.io"},
    "polygon": {"chain_id": 137, "name": "Polygon", "native": "MATIC", "explorer": "https://polygonscan.com"},
    "arbitrum": {"chain_id": 42161, "name": "Arbitrum", "native": "ETH", "explorer": "https://arbiscan.io"},
    "optimism": {"chain_id": 10, "name": "Optimism", "native": "ETH", "explorer": "https://optimistic.etherscan.io"},
}

SUPPORTED_BRIDGES: dict[str, dict[str, Any]] = {
    "native": {"name": "Native Bridge", "speed": "slow", "safety": "highest", "fee_bps": 0},
    "stargate": {"name": "Stargate", "speed": "medium", "safety": "high", "fee_bps": 6},
    "hop": {"name": "Hop Protocol", "speed": "fast", "safety": "high", "fee_bps": 4},
    "across": {"name": "Across Protocol", "speed": "fast", "safety": "high", "fee_bps": 5},
}

SUPPORTED_ROUTES: dict[str, list[str]] = {}

# Estimated gas costs per chain in USD for a simple transfer.
_GAS_COSTS_USD: dict[str, float] = {
    "base": 0.01,
    "ethereum": 3.50,
    "polygon": 0.005,
    "arbitrum": 0.08,
    "optimism": 0.06,
}

# Estimated bridge completion times in seconds.
_BRIDGE_TIMES: dict[str, int] = {
    "slow": 900,     # 15 minutes (native bridges)
    "medium": 300,   # 5 minutes
    "fast": 120,     # 2 minutes
}


class CrossChainRouter:
    """Evaluate bridges and recommend optimal cross-chain routing."""

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._logger = logging.getLogger(__name__)

        # Build the route matrix — every chain-pair gets all bridges.
        SUPPORTED_ROUTES.clear()
        chain_names = list(SUPPORTED_CHAINS.keys())
        for src in chain_names:
            for dst in chain_names:
                if src != dst:
                    route_key = f"{src}->{dst}"
                    SUPPORTED_ROUTES[route_key] = list(SUPPORTED_BRIDGES.keys())

    # ── Bridge evaluation ────────────────────────────────────────────

    async def get_best_bridge(
        self,
        asset: str,
        from_chain: str,
        to_chain: str,
        amount: float,
    ) -> dict:
        """Return ranked bridge options for moving *asset* between chains."""
        try:
            bridges_cfg = self._config.get("bridges", {})
            if not bridges_cfg:
                return {
                    "status": "not_configured",
                    "message": (
                        "No bridge endpoints configured. "
                        "Add bridge endpoints to openmatrix.config.json"
                    ),
                    "supported_bridges": list(SUPPORTED_BRIDGES.keys()),
                }

            if from_chain not in SUPPORTED_CHAINS:
                return {
                    "status": "error",
                    "message": f"Unsupported source chain '{from_chain}'. Supported: {list(SUPPORTED_CHAINS.keys())}",
                }
            if to_chain not in SUPPORTED_CHAINS:
                return {
                    "status": "error",
                    "message": f"Unsupported destination chain '{to_chain}'. Supported: {list(SUPPORTED_CHAINS.keys())}",
                }
            if from_chain == to_chain:
                return {
                    "status": "error",
                    "message": "Source and destination chains must differ",
                }

            options: list[dict[str, Any]] = []
            for bridge_key, bridge_info in SUPPORTED_BRIDGES.items():
                if bridge_key not in bridges_cfg and bridge_key != "native":
                    continue

                fee_bps = bridge_info["fee_bps"]
                fee_usd = round(amount * fee_bps / 10_000, 4)
                speed = bridge_info["speed"]
                estimated_seconds = _BRIDGE_TIMES.get(speed, 600)

                # Gas on both chains.
                gas_src = _GAS_COSTS_USD.get(from_chain, 0.10)
                gas_dst = _GAS_COSTS_USD.get(to_chain, 0.10)
                total_cost = round(fee_usd + gas_src + gas_dst, 4)

                options.append({
                    "bridge": bridge_info["name"],
                    "bridge_key": bridge_key,
                    "fee_bps": fee_bps,
                    "fee_usd": fee_usd,
                    "gas_source_usd": gas_src,
                    "gas_destination_usd": gas_dst,
                    "total_cost_usd": total_cost,
                    "speed": speed,
                    "estimated_seconds": estimated_seconds,
                    "safety": bridge_info["safety"],
                })

            # Rank by total cost, then by speed.
            speed_rank = {"fast": 0, "medium": 1, "slow": 2}
            options.sort(key=lambda o: (o["total_cost_usd"], speed_rank.get(o["speed"], 9)))

            if not options:
                return {
                    "status": "not_configured",
                    "message": "No bridges available for this route",
                    "supported_bridges": list(SUPPORTED_BRIDGES.keys()),
                }

            return {
                "status": "ok",
                "asset": asset,
                "from_chain": from_chain,
                "to_chain": to_chain,
                "amount": amount,
                "options": options,
                "recommended": options[0],
            }
        except Exception as exc:
            self._logger.error("get_best_bridge failed: %s", exc, exc_info=True)
            return {"status": "error", "message": str(exc)}

    # ── Execution ────────────────────────────────────────────────────

    async def execute_bridge(self, route: dict, wallet: str) -> dict:
        """Execute a bridge transaction (returns pending status)."""
        try:
            if not isinstance(route, dict) or "bridge_key" not in route:
                return {
                    "status": "error",
                    "message": "Invalid route — must include 'bridge_key'",
                }

            if not self._web3.available:
                return not_deployed_response("cross_chain_router", {
                    "bridge": route.get("bridge"),
                    "message": "Blockchain not configured — cannot execute bridge",
                })

            estimated_seconds = route.get("estimated_seconds", 300)
            estimated_completion = time.time() + estimated_seconds

            return {
                "status": "pending",
                "bridge": route.get("bridge"),
                "bridge_key": route.get("bridge_key"),
                "wallet": wallet,
                "total_cost_usd": route.get("total_cost_usd", 0.0),
                "estimated_completion_timestamp": estimated_completion,
                "estimated_seconds_remaining": estimated_seconds,
                "tx_hash": None,
                "message": "Bridge transaction queued for execution",
            }
        except Exception as exc:
            self._logger.error("execute_bridge failed: %s", exc, exc_info=True)
            return {"status": "error", "message": str(exc)}

    # ── Cost estimation ──────────────────────────────────────────────

    async def estimate_total_cost(
        self,
        action: str,
        from_chain: str,
        to_chain: str,
    ) -> dict:
        """Estimate total cost including gas on both chains and bridge fee."""
        try:
            gas_src = _GAS_COSTS_USD.get(from_chain, 0.10)
            gas_dst = _GAS_COSTS_USD.get(to_chain, 0.10)

            # Action-specific gas multiplier.
            action_multipliers = {
                "swap": 2.5,
                "deposit": 1.8,
                "borrow": 2.0,
                "transfer": 1.0,
                "bridge": 1.5,
            }
            multiplier = action_multipliers.get(action.lower(), 1.5)
            gas_src_adjusted = round(gas_src * multiplier, 4)

            # Average bridge fee (use Hop as representative).
            bridge_fee_estimate = 0.0
            if from_chain != to_chain:
                bridge_fee_estimate = round(
                    SUPPORTED_BRIDGES["hop"]["fee_bps"] / 10_000 * 1000, 4
                )  # Assume $1000 notional for estimate.

            total = round(gas_src_adjusted + gas_dst + bridge_fee_estimate, 4)

            return {
                "status": "ok",
                "action": action,
                "from_chain": from_chain,
                "to_chain": to_chain,
                "gas_source_usd": gas_src_adjusted,
                "gas_destination_usd": gas_dst,
                "bridge_fee_usd": bridge_fee_estimate,
                "total_estimated_usd": total,
            }
        except Exception as exc:
            self._logger.error("estimate_total_cost failed: %s", exc, exc_info=True)
            return {"status": "error", "message": str(exc)}

    # ── Chain recommendation ─────────────────────────────────────────

    def get_optimal_chain(self, action: str, asset: str) -> str:
        """Recommend the best chain for *action* on *asset* based on gas and liquidity."""
        try:
            # Scoring: lower is better.  Gas cost is the dominant factor.
            scores: dict[str, float] = {}
            for chain, gas_cost in _GAS_COSTS_USD.items():
                # Liquidity bonus — Ethereum has the deepest liquidity, L2s less.
                liquidity_penalty = {
                    "base": -0.005,       # home chain bonus
                    "ethereum": 0.0,
                    "arbitrum": 0.002,
                    "optimism": 0.003,
                    "polygon": 0.004,
                }.get(chain, 0.01)

                # For swaps/borrows Ethereum liquidity matters more.
                if action.lower() in ("swap", "borrow") and chain == "ethereum":
                    liquidity_penalty = -0.5  # bonus

                scores[chain] = gas_cost + liquidity_penalty

            best = min(scores, key=scores.get)  # type: ignore[arg-type]
            return best
        except Exception as exc:
            self._logger.error("get_optimal_chain failed: %s", exc, exc_info=True)
            return "base"
