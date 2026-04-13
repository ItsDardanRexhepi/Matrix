"""Intent resolver — converts plain-English intents into executable plans with full cost and risk analysis."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from runtime.blockchain.protocol_abstraction.cross_chain_router import CrossChainRouter
from runtime.blockchain.protocol_abstraction.data_aggregator import DataAggregator
from runtime.blockchain.protocol_abstraction.defi_router import DeFiRouter

logger = logging.getLogger(__name__)

# Mapping of user intents to internal action categories.
_INTENT_MAP: dict[str, str] = {
    "swap": "swap",
    "trade": "swap",
    "exchange": "swap",
    "lend": "yield_deposit",
    "deposit": "yield_deposit",
    "earn yield": "yield_deposit",
    "earn": "yield_deposit",
    "borrow": "borrow",
    "loan": "borrow",
    "bridge": "bridge",
    "move": "bridge",
    "transfer cross-chain": "bridge",
    "store": "storage",
    "upload": "storage",
    "save": "storage",
}

# Risk assessments by action category.
_RISK_PROFILES: dict[str, dict[str, str]] = {
    "swap": {"level": "low", "description": "Standard token swap on a battle-tested DEX. Slippage risk is minimal for liquid pairs."},
    "yield_deposit": {"level": "medium", "description": "Depositing into a lending protocol. Smart-contract risk exists but protocols are audited."},
    "borrow": {"level": "medium", "description": "Borrowing against collateral. Liquidation risk exists if collateral value drops."},
    "bridge": {"level": "medium", "description": "Cross-chain bridge. Assets are locked until the destination chain confirms."},
    "storage": {"level": "low", "description": "Decentralized storage upload. Data is replicated across nodes."},
}

# Baseline time estimates in seconds per action.
_TIME_ESTIMATES: dict[str, int] = {
    "swap": 15,
    "yield_deposit": 20,
    "borrow": 25,
    "bridge": 300,
    "storage": 10,
}

# Threshold (USD) above which user confirmation is required.
_CONFIRMATION_THRESHOLD_USD = 100.0


class IntentResolver:
    """Convert plain-English intents into executable on-chain plans."""

    def __init__(self, config: dict) -> None:
        self._config = config
        self._defi_router = DeFiRouter(config)
        self._cross_chain_router = CrossChainRouter(config)
        self._data_aggregator = DataAggregator(config)
        self._logger = logging.getLogger(__name__)

    # ── Intent resolution ────────────────────────────────────────────

    async def resolve(
        self,
        intent: str,
        entities: dict,
        wallet: str,
        tier: str = "free",
    ) -> dict:
        """Resolve *intent* into a structured execution plan."""
        try:
            intent_lower = intent.lower().strip()

            # Match intent to action category.
            action: str | None = None
            for keyword, mapped_action in _INTENT_MAP.items():
                if keyword in intent_lower:
                    action = mapped_action
                    break

            if action is None:
                return {
                    "status": "unresolved",
                    "message": (
                        f"Could not resolve intent '{intent}'. "
                        "Try: swap, deposit, borrow, bridge, or store."
                    ),
                    "supported_intents": list(_INTENT_MAP.keys()),
                }

            plan_id = str(uuid.uuid4())
            asset = entities.get("asset", "ETH")
            amount = float(entities.get("amount", 0))
            from_chain = entities.get("from_chain", "base")
            to_chain = entities.get("to_chain", "base")
            token_out = entities.get("token_out", "USDC")
            collateral = entities.get("collateral", "ETH")

            # Determine optimal chain.
            chain = self._cross_chain_router.get_optimal_chain(action, asset)
            if action == "bridge":
                chain = from_chain  # Source chain for bridges.

            # Build steps and cost estimate.
            steps: list[dict[str, Any]] = []
            estimated_cost_usd = 0.0
            protocols_used: list[str] = []

            if action == "swap":
                route_result = await self._defi_router.get_best_swap_route(asset, token_out, amount)
                best = route_result.get("best_route", {})
                gas_usd = best.get("gas_estimate_usd", 3.0)
                steps.append({
                    "action": "swap",
                    "params": {"token_in": asset, "token_out": token_out, "amount": amount},
                    "estimated_gas_usd": gas_usd,
                })
                estimated_cost_usd = gas_usd
                protocols_used.append(best.get("dex", "uniswap"))

            elif action == "yield_deposit":
                yield_result = await self._defi_router.get_best_yield(asset, amount)
                recommended = yield_result.get("recommended", {})
                protocol_name = recommended.get("protocol", "aave")
                gas_usd = 2.50
                steps.append({
                    "action": "approve",
                    "params": {"asset": asset, "spender": protocol_name},
                    "estimated_gas_usd": 1.00,
                })
                steps.append({
                    "action": "deposit",
                    "params": {"protocol": protocol_name, "asset": asset, "amount": amount},
                    "estimated_gas_usd": gas_usd,
                })
                estimated_cost_usd = 1.00 + gas_usd
                protocols_used.append(protocol_name)

            elif action == "borrow":
                borrow_result = await self._defi_router.get_best_borrow_rate(asset, collateral)
                recommended = borrow_result.get("recommended", {})
                protocol_name = recommended.get("protocol", "aave")
                gas_usd = 3.00
                steps.append({
                    "action": "supply_collateral",
                    "params": {"asset": collateral, "protocol": protocol_name},
                    "estimated_gas_usd": 2.00,
                })
                steps.append({
                    "action": "borrow",
                    "params": {"asset": asset, "protocol": protocol_name, "amount": amount},
                    "estimated_gas_usd": gas_usd,
                })
                estimated_cost_usd = 2.00 + gas_usd
                protocols_used.append(protocol_name)

            elif action == "bridge":
                bridge_result = await self._cross_chain_router.get_best_bridge(
                    asset, from_chain, to_chain, amount,
                )
                recommended = bridge_result.get("recommended", {})
                total_cost = recommended.get("total_cost_usd", 1.0)
                steps.append({
                    "action": "bridge",
                    "params": {
                        "asset": asset,
                        "amount": amount,
                        "from_chain": from_chain,
                        "to_chain": to_chain,
                        "bridge": recommended.get("bridge", "hop"),
                    },
                    "estimated_gas_usd": total_cost,
                })
                estimated_cost_usd = total_cost
                protocols_used.append(recommended.get("bridge_key", "hop"))

            elif action == "storage":
                gas_usd = 0.50
                steps.append({
                    "action": "upload",
                    "params": {"data_ref": entities.get("data_ref", ""), "storage": "ipfs"},
                    "estimated_gas_usd": gas_usd,
                })
                estimated_cost_usd = gas_usd
                protocols_used.append("ipfs")

            # Risk profile.
            risk = _RISK_PROFILES.get(action, {"level": "medium", "description": "Unknown action risk"})
            time_estimate = _TIME_ESTIMATES.get(action, 30)

            # High-value transactions require confirmation.
            price_data = await self._data_aggregator.get_asset_price(asset)
            value_usd = amount * price_data.get("price_usd", 0.0)
            requires_confirmation = value_usd > _CONFIRMATION_THRESHOLD_USD

            estimated_cost_usd = round(estimated_cost_usd, 4)

            summary = (
                f"Plan to {action.replace('_', ' ')} {amount} {asset} on {chain}. "
                f"Estimated cost: ${estimated_cost_usd:.2f}. "
                f"Risk: {risk['level']}. "
                f"Estimated time: ~{time_estimate}s."
            )

            return {
                "status": "ok",
                "plan_id": plan_id,
                "intent": intent,
                "action": action,
                "chain": chain,
                "protocols": protocols_used,
                "estimated_cost_usd": estimated_cost_usd,
                "estimated_time_seconds": time_estimate,
                "risk_level": risk["level"],
                "risk_description": risk["description"],
                "steps": steps,
                "requires_confirmation": requires_confirmation,
                "summary": summary,
            }
        except Exception as exc:
            self._logger.error("resolve failed: %s", exc, exc_info=True)
            return {"status": "error", "message": str(exc)}

    # ── Plan execution ───────────────────────────────────────────────

    async def execute_plan(self, plan: dict, wallet: str) -> dict:
        """Execute a resolved plan step by step."""
        try:
            plan_id = plan.get("plan_id", str(uuid.uuid4()))
            steps = plan.get("steps", [])
            results: list[dict] = []
            total_cost = 0.0
            completed = 0

            for step in steps:
                action = step.get("action", "")
                params = step.get("params", {})
                gas_usd = step.get("estimated_gas_usd", 0.0)

                if action == "swap":
                    route = {
                        "dex": "Uniswap V3",
                        "route_path": [params.get("token_in", ""), params.get("token_out", "")],
                        "estimated_output": params.get("amount", 0),
                    }
                    result = await self._defi_router.execute_swap(route, wallet)
                elif action in ("deposit", "yield_deposit"):
                    result = await self._defi_router.execute_yield_deposit(
                        params.get("protocol", "aave"),
                        params.get("asset", "ETH"),
                        float(params.get("amount", 0)),
                        wallet,
                    )
                elif action == "bridge":
                    bridge_route = {
                        "bridge": params.get("bridge", "hop"),
                        "bridge_key": params.get("bridge", "hop"),
                    }
                    result = await self._cross_chain_router.execute_bridge(bridge_route, wallet)
                elif action in ("approve", "supply_collateral", "borrow", "upload"):
                    # Actions that resolve to pending status when blockchain is conceptual.
                    result = {
                        "status": "pending",
                        "action": action,
                        "params": params,
                        "message": f"{action} queued for execution",
                    }
                else:
                    result = {
                        "status": "skipped",
                        "action": action,
                        "message": f"Unknown action '{action}'",
                    }

                results.append(result)
                total_cost += gas_usd
                if result.get("status") in ("pending", "ok"):
                    completed += 1

            return {
                "status": "ok",
                "plan_id": plan_id,
                "results": results,
                "total_cost_usd": round(total_cost, 4),
                "completed_steps": completed,
                "total_steps": len(steps),
            }
        except Exception as exc:
            self._logger.error("execute_plan failed: %s", exc, exc_info=True)
            return {"status": "error", "message": str(exc)}

    # ── Human-readable summary ───────────────────────────────────────

    async def get_plan_summary(self, plan: dict) -> str:
        """Return a plain-English paragraph suitable for Trinity to read aloud."""
        try:
            action = plan.get("action", plan.get("intent", "unknown action"))
            chain = plan.get("chain", "base")
            protocols = plan.get("protocols", [])
            cost = plan.get("estimated_cost_usd", 0.0)
            time_s = plan.get("estimated_time_seconds", 0)
            risk = plan.get("risk_level", "medium")
            risk_desc = plan.get("risk_description", "")
            steps = plan.get("steps", [])
            requires_conf = plan.get("requires_confirmation", False)

            protocol_str = ", ".join(protocols) if protocols else "available protocols"
            step_descriptions = []
            for i, step in enumerate(steps, 1):
                step_action = step.get("action", "unknown")
                step_gas = step.get("estimated_gas_usd", 0.0)
                step_descriptions.append(f"Step {i}: {step_action} (est. ${step_gas:.2f})")

            steps_text = ". ".join(step_descriptions) if step_descriptions else "No steps defined"

            summary_parts = [
                f"Here is your plan to {action.replace('_', ' ')} on {chain} using {protocol_str}.",
                f"This involves {len(steps)} step(s): {steps_text}.",
                f"Total estimated cost is ${cost:.2f}, and it should take about {time_s} seconds.",
                f"Risk level: {risk}. {risk_desc}",
            ]

            if requires_conf:
                summary_parts.append(
                    "Because the transaction value exceeds $100, your confirmation is required before execution."
                )

            return " ".join(summary_parts)
        except Exception as exc:
            self._logger.error("get_plan_summary failed: %s", exc, exc_info=True)
            return f"Unable to generate plan summary: {exc}"
