"""
Trajectory Protocol — Outcome prediction and path optimization.
Predicts likely outcomes of actions and suggests optimal paths.
"""

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class TrajectoryEngine:
    """Predicts outcomes, explores alternative execution paths, and
    recommends the optimal route to a user's goal."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._prediction_cache: dict[str, dict[str, Any]] = {}
        logger.info("TrajectoryEngine initialised")

    # ── Public API ────────────────────────────────────────────────────

    async def predict_outcome(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Predict the likely outcome of *action* given *context*.

        Returns:
            prediction_id, action_type, predicted_success_rate,
            expected_outcome, risks, confidence, time_estimate_seconds
        """
        action_type = str(action.get("action_type", action.get("type", "unknown")))
        prediction_id = str(uuid.uuid4())

        # Base success rate from action type heuristics
        success_rate = self._base_success_rate(action_type)

        # Adjust for context signals
        success_rate = self._adjust_for_context(success_rate, action, context)

        # Risk factors
        risks = self._identify_risks(action, context)

        # Confidence based on data available
        confidence = self._calculate_confidence(action, context)

        # Time estimate
        time_est = self._estimate_time(action_type)

        prediction = {
            "prediction_id": prediction_id,
            "action_type": action_type,
            "predicted_success_rate": round(success_rate, 3),
            "expected_outcome": self._describe_expected_outcome(action_type, action),
            "risks": risks,
            "confidence": round(confidence, 3),
            "time_estimate_seconds": time_est,
        }

        self._prediction_cache[prediction_id] = prediction
        logger.info(
            "Predicted outcome for '%s': success=%.1f%% confidence=%.1f%%",
            action_type, success_rate * 100, confidence * 100,
        )
        return prediction

    async def find_optimal_path(
        self, goal: str, constraints: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Find the optimal sequence of steps to achieve *goal* under
        *constraints*.

        Returns an ordered list of step dicts, each with:
            step_id, action, estimated_cost, estimated_time_seconds,
            success_probability, rationale
        """
        goal_lower = goal.lower()
        max_cost = constraints.get("max_cost")
        max_time = constraints.get("max_time_seconds")
        preferred_chains = constraints.get("preferred_chains", [])
        risk_tolerance = constraints.get("risk_tolerance", "medium")

        paths = self._generate_candidate_paths(goal_lower, constraints)

        # Filter by constraints
        valid: list[list[dict[str, Any]]] = []
        for path in paths:
            total_cost = sum(s.get("estimated_cost", 0) for s in path)
            total_time = sum(s.get("estimated_time_seconds", 0) for s in path)
            if max_cost is not None and total_cost > max_cost:
                continue
            if max_time is not None and total_time > max_time:
                continue
            valid.append(path)

        if not valid:
            # Return best single path anyway with a warning
            if paths:
                best = paths[0]
                for step in best:
                    step["warning"] = "No path meets all constraints; this is the best available."
                return best
            return [{
                "step_id": str(uuid.uuid4()),
                "action": "manual_review",
                "estimated_cost": 0,
                "estimated_time_seconds": 0,
                "success_probability": 0.0,
                "rationale": "Unable to determine a path for this goal. Manual review recommended.",
            }]

        # Score and pick best
        scored = [(self._score_path(p, risk_tolerance), p) for p in valid]
        scored.sort(key=lambda x: x[0], reverse=True)
        best_path = scored[0][1]

        logger.info("Optimal path for '%s': %d steps", goal[:60], len(best_path))
        return best_path

    async def compare_paths(
        self, paths: list[list[dict[str, Any]]]
    ) -> dict[str, Any]:
        """Compare multiple execution *paths* and return a ranked analysis.

        Returns:
            ranked: list of path summaries (best first)
            recommendation: index of recommended path
            comparison_matrix: dict of metric comparisons
        """
        if not paths:
            return {"ranked": [], "recommendation": -1, "comparison_matrix": {}}

        summaries: list[dict[str, Any]] = []
        for i, path in enumerate(paths):
            total_cost = sum(s.get("estimated_cost", 0) for s in path)
            total_time = sum(s.get("estimated_time_seconds", 0) for s in path)
            avg_success = (
                sum(s.get("success_probability", 0.5) for s in path) / len(path)
                if path else 0
            )
            summaries.append({
                "path_index": i,
                "step_count": len(path),
                "total_cost": round(total_cost, 4),
                "total_time_seconds": total_time,
                "average_success_probability": round(avg_success, 3),
                "composite_score": round(
                    avg_success * 0.5 + (1.0 / (1 + total_cost)) * 0.3 + (1.0 / (1 + total_time / 60)) * 0.2,
                    3,
                ),
            })

        summaries.sort(key=lambda s: s["composite_score"], reverse=True)
        best_idx = summaries[0]["path_index"]

        comparison_matrix = {
            "cost": {f"path_{s['path_index']}": s["total_cost"] for s in summaries},
            "time": {f"path_{s['path_index']}": s["total_time_seconds"] for s in summaries},
            "success": {f"path_{s['path_index']}": s["average_success_probability"] for s in summaries},
        }

        result = {
            "ranked": summaries,
            "recommendation": best_idx,
            "comparison_matrix": comparison_matrix,
        }
        logger.info("Compared %d paths; recommended path_%d", len(paths), best_idx)
        return result

    # ── Private helpers ───────────────────────────────────────────────

    _BASE_RATES: dict[str, float] = {
        "transfer": 0.95,
        "swap": 0.90,
        "deploy_contract": 0.80,
        "stake": 0.92,
        "unstake": 0.90,
        "vote": 0.97,
        "bridge": 0.85,
        "borrow": 0.88,
        "repay": 0.95,
        "approve_token": 0.98,
        "claim_rewards": 0.95,
        "mint_nft": 0.88,
    }

    def _base_success_rate(self, action_type: str) -> float:
        return self._BASE_RATES.get(action_type, 0.85)

    @staticmethod
    def _adjust_for_context(
        rate: float, action: dict[str, Any], context: dict[str, Any]
    ) -> float:
        adjusted = rate

        # Network congestion penalty
        congestion = context.get("network_congestion", 0)  # 0-1
        adjusted -= congestion * 0.1

        # Low balance warning
        balance = context.get("balance", float("inf"))
        value = action.get("parameters", {}).get("value", 0)
        if isinstance(value, (int, float)) and isinstance(balance, (int, float)):
            if value > balance * 0.9:
                adjusted -= 0.15  # cutting it close

        # Historical success for this user
        user_success = context.get("user_historical_success_rate")
        if isinstance(user_success, (int, float)):
            adjusted = adjusted * 0.7 + user_success * 0.3

        return max(0.01, min(adjusted, 0.99))

    @staticmethod
    def _identify_risks(
        action: dict[str, Any], context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        risks: list[dict[str, Any]] = []
        action_type = str(action.get("action_type", action.get("type", "")))

        if action_type in ("bridge", "swap"):
            risks.append({"risk": "slippage", "severity": "medium", "mitigation": "Set slippage tolerance"})
        if action_type == "deploy_contract":
            risks.append({"risk": "gas_spike", "severity": "high", "mitigation": "Use gas price oracle"})
        if context.get("network_congestion", 0) > 0.7:
            risks.append({"risk": "network_congestion", "severity": "medium", "mitigation": "Wait for lower congestion or increase gas"})

        value = action.get("parameters", {}).get("value", 0)
        if isinstance(value, (int, float)) and value > 1000:
            risks.append({"risk": "high_value", "severity": "high", "mitigation": "Verify recipient and use hardware wallet"})

        return risks

    @staticmethod
    def _calculate_confidence(action: dict[str, Any], context: dict[str, Any]) -> float:
        confidence = 0.5
        if context.get("user_historical_success_rate") is not None:
            confidence += 0.2
        if context.get("network_congestion") is not None:
            confidence += 0.1
        if context.get("balance") is not None:
            confidence += 0.1
        if action.get("parameters"):
            confidence += 0.1
        return min(confidence, 1.0)

    _TIME_ESTIMATES: dict[str, int] = {
        "transfer": 30,
        "swap": 45,
        "deploy_contract": 120,
        "stake": 60,
        "unstake": 60,
        "vote": 20,
        "bridge": 300,
        "borrow": 45,
        "repay": 30,
        "approve_token": 20,
        "claim_rewards": 30,
        "mint_nft": 60,
    }

    def _estimate_time(self, action_type: str) -> int:
        return self._TIME_ESTIMATES.get(action_type, 60)

    @staticmethod
    def _describe_expected_outcome(action_type: str, action: dict[str, Any]) -> str:
        descriptions: dict[str, str] = {
            "transfer": "Tokens transferred to recipient address.",
            "swap": "Source token exchanged for target token at market rate.",
            "deploy_contract": "Smart contract deployed and verified on-chain.",
            "stake": "Tokens staked with selected validator.",
            "unstake": "Tokens unstaked; cooldown period initiated.",
            "vote": "Governance vote recorded on-chain.",
            "bridge": "Tokens bridged to destination chain.",
            "borrow": "Loan originated against deposited collateral.",
            "repay": "Outstanding loan balance reduced.",
            "approve_token": "Token spending approval granted to contract.",
        }
        return descriptions.get(action_type, f"Action '{action_type}' executed successfully.")

    def _generate_candidate_paths(
        self, goal: str, constraints: dict[str, Any]
    ) -> list[list[dict[str, Any]]]:
        """Generate candidate paths (heuristic; LLM refines in production)."""
        paths: list[list[dict[str, Any]]] = []

        if any(kw in goal for kw in ("swap", "exchange", "trade")):
            # Direct swap path
            paths.append([
                self._path_step("approve_token", 0.5, 20, 0.98, "Approve token for DEX"),
                self._path_step("swap", 2.0, 45, 0.90, "Execute swap on primary DEX"),
            ])
            # Aggregator path
            paths.append([
                self._path_step("approve_token", 0.5, 20, 0.98, "Approve token for aggregator"),
                self._path_step("swap", 1.5, 60, 0.92, "Execute swap via aggregator for better rate"),
            ])
        elif any(kw in goal for kw in ("bridge", "cross-chain")):
            paths.append([
                self._path_step("approve_token", 0.5, 20, 0.98, "Approve for bridge"),
                self._path_step("bridge", 5.0, 300, 0.85, "Bridge tokens to destination chain"),
            ])
        elif any(kw in goal for kw in ("stake", "delegate")):
            paths.append([
                self._path_step("approve_token", 0.3, 20, 0.98, "Approve staking contract"),
                self._path_step("stake", 1.0, 60, 0.92, "Stake tokens"),
            ])
        else:
            paths.append([
                self._path_step("execute", 1.0, 60, 0.85, f"Execute: {goal[:50]}"),
            ])

        return paths

    @staticmethod
    def _path_step(
        action: str, cost: float, time_s: int, success: float, rationale: str
    ) -> dict[str, Any]:
        return {
            "step_id": str(uuid.uuid4()),
            "action": action,
            "estimated_cost": cost,
            "estimated_time_seconds": time_s,
            "success_probability": success,
            "rationale": rationale,
        }

    @staticmethod
    def _score_path(path: list[dict[str, Any]], risk_tolerance: str) -> float:
        if not path:
            return 0.0
        total_cost = sum(s.get("estimated_cost", 0) for s in path)
        total_time = sum(s.get("estimated_time_seconds", 0) for s in path)
        avg_success = sum(s.get("success_probability", 0.5) for s in path) / len(path)

        risk_weights = {"low": 0.7, "medium": 0.5, "high": 0.3}
        success_weight = risk_weights.get(risk_tolerance, 0.5)

        score = (
            avg_success * success_weight
            + (1.0 / (1 + total_cost)) * (1 - success_weight) * 0.6
            + (1.0 / (1 + total_time / 60)) * (1 - success_weight) * 0.4
        )
        return score
