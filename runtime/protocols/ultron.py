"""
Ultron Protocol — Strategic reasoning engine.
Multi-step planning, goal decomposition, risk assessment.
"""

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

RISK_LEVELS = ("low", "medium", "high", "critical")

# Actions that are inherently higher risk
_HIGH_RISK_KEYWORDS: set[str] = {
    "deploy", "transfer", "swap", "bridge", "burn", "revoke", "delegate",
    "liquidate", "borrow", "repay", "unstake", "withdraw", "migrate",
}

_CRITICAL_RISK_KEYWORDS: set[str] = {
    "deploy_contract", "transfer_ownership", "burn_nft", "self_destruct",
    "upgrade_proxy", "set_implementation",
}


class UltronProtocol:
    """Strategic reasoning — breaks goals into steps, assesses risk,
    and learns from outcomes to refine future plans."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._outcome_history: list[dict[str, Any]] = []
        logger.info("UltronProtocol initialised")

    # ── Planning ──────────────────────────────────────────────────────

    async def plan(self, goal: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Decompose *goal* into a list of executable step dicts.

        Each step contains:
            id, description, action_type, parameters, dependencies,
            estimated_risk, requires_confirmation
        """
        if not goal:
            logger.warning("plan() called with empty goal")
            return []

        steps = self._decompose_goal(goal, context)

        # Annotate each step with risk info
        for step in steps:
            risk = await self.assess_risk(step)
            step["estimated_risk"] = risk["risk_level"]
            step["requires_confirmation"] = risk["risk_level"] in ("high", "critical")
            step["risk_details"] = risk

        logger.info("Planned %d steps for goal='%s'", len(steps), goal[:80])
        return steps

    # ── Risk assessment ───────────────────────────────────────────────

    async def assess_risk(self, action: dict[str, Any]) -> dict[str, Any]:
        """Evaluate the risk of *action*.

        Returns:
            risk_level: one of low / medium / high / critical
            concerns: list of human-readable concern strings
            mitigations: list of suggested mitigations
            triggers_morpheus: bool — True when Morpheus should intervene
        """
        concerns: list[str] = []
        mitigations: list[str] = []
        risk_level = "low"

        action_type = str(action.get("action_type", action.get("type", ""))).lower()
        value = action.get("parameters", {}).get("value", 0)
        description = str(action.get("description", ""))

        # Keyword-based escalation
        if action_type in _CRITICAL_RISK_KEYWORDS or any(kw in description.lower() for kw in _CRITICAL_RISK_KEYWORDS):
            risk_level = "critical"
            concerns.append(f"Action '{action_type}' is classified as critical and irreversible.")
            mitigations.append("Require explicit user confirmation with a summary of consequences.")
        elif action_type in _HIGH_RISK_KEYWORDS or any(kw in description.lower() for kw in _HIGH_RISK_KEYWORDS):
            risk_level = "high"
            concerns.append(f"Action '{action_type}' involves asset movement or state change.")
            mitigations.append("Display transaction preview before execution.")

        # Value-based escalation
        value_thresholds = self.config.get("risk_value_thresholds", {
            "medium": 100,
            "high": 1000,
            "critical": 10000,
        })
        if isinstance(value, (int, float)):
            if value >= value_thresholds.get("critical", 10000):
                risk_level = "critical"
                concerns.append(f"Transaction value ${value:,.2f} exceeds critical threshold.")
                mitigations.append("Split into smaller transactions if possible.")
            elif value >= value_thresholds.get("high", 1000):
                risk_level = max(risk_level, "high", key=RISK_LEVELS.index)
                concerns.append(f"Transaction value ${value:,.2f} is significant.")
                mitigations.append("Double-check recipient address and amount.")
            elif value >= value_thresholds.get("medium", 100):
                risk_level = max(risk_level, "medium", key=RISK_LEVELS.index)

        # Historical failure patterns
        failure_rate = self._historical_failure_rate(action_type)
        if failure_rate > 0.3:
            risk_level = max(risk_level, "medium", key=RISK_LEVELS.index)
            concerns.append(f"Historical failure rate for '{action_type}' is {failure_rate:.0%}.")
            mitigations.append("Review past failures before proceeding.")

        triggers_morpheus = risk_level in ("high", "critical")

        result = {
            "risk_level": risk_level,
            "concerns": concerns,
            "mitigations": mitigations,
            "triggers_morpheus": triggers_morpheus,
        }
        logger.debug("Risk assessed: %s -> %s", action_type, risk_level)
        return result

    # ── Outcome evaluation ────────────────────────────────────────────

    async def evaluate_outcome(
        self, action: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        """Record the outcome of *action* and return a learning summary.

        Returns:
            success: bool
            lessons: list of strings
            confidence_delta: float (how much to adjust future confidence)
        """
        success = result.get("success", result.get("status") == "success")
        action_type = str(action.get("action_type", action.get("type", "")))
        timestamp = time.time()

        entry = {
            "id": str(uuid.uuid4()),
            "action_type": action_type,
            "action": action,
            "result": result,
            "success": success,
            "timestamp": timestamp,
        }
        self._outcome_history.append(entry)

        # Cap history
        max_history = self.config.get("max_outcome_history", 500)
        if len(self._outcome_history) > max_history:
            self._outcome_history = self._outcome_history[-max_history:]

        lessons: list[str] = []
        confidence_delta = 0.0

        if success:
            confidence_delta = 0.05
            lessons.append(f"Action '{action_type}' succeeded — reinforcing confidence.")
        else:
            confidence_delta = -0.1
            error = result.get("error", "unknown error")
            lessons.append(f"Action '{action_type}' failed: {error}")
            lessons.append("Consider adding pre-flight checks for this action type.")

        evaluation = {
            "success": success,
            "lessons": lessons,
            "confidence_delta": confidence_delta,
            "outcome_id": entry["id"],
        }
        logger.info("Outcome evaluated: %s success=%s", action_type, success)
        return evaluation

    # ── Private helpers ───────────────────────────────────────────────

    def _decompose_goal(
        self, goal: str, context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Heuristic goal decomposition.

        In production, the LLM handles complex decomposition; this
        provides a structured skeleton that the LLM refines.
        """
        goal_lower = goal.lower()
        steps: list[dict[str, Any]] = []

        # Always start with context gathering
        steps.append(self._step("gather_context", "Retrieve relevant user context and history", {}))

        # Intent-specific decomposition
        if any(kw in goal_lower for kw in ("swap", "exchange", "trade")):
            steps.extend(self._swap_steps(goal, context))
        elif any(kw in goal_lower for kw in ("deploy", "create contract", "launch")):
            steps.extend(self._deploy_steps(goal, context))
        elif any(kw in goal_lower for kw in ("transfer", "send")):
            steps.extend(self._transfer_steps(goal, context))
        elif any(kw in goal_lower for kw in ("stake", "delegate")):
            steps.extend(self._staking_steps(goal, context))
        elif any(kw in goal_lower for kw in ("vote", "governance", "proposal")):
            steps.extend(self._governance_steps(goal, context))
        else:
            # Generic two-step: analyse then execute
            steps.append(self._step("analyse", f"Analyse request: {goal}", {"goal": goal}))
            steps.append(self._step("execute", f"Execute: {goal}", {"goal": goal}))

        # Final confirmation step for multi-step plans
        if len(steps) > 2:
            steps.append(self._step("confirm_completion", "Verify all steps completed successfully", {}))

        # Wire up sequential dependencies
        for i in range(1, len(steps)):
            steps[i]["dependencies"] = [steps[i - 1]["id"]]

        return steps

    def _step(
        self,
        action_type: str,
        description: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "action_type": action_type,
            "description": description,
            "parameters": parameters,
            "dependencies": [],
            "estimated_risk": "low",
            "requires_confirmation": False,
        }

    def _swap_steps(self, goal: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._step("check_balance", "Verify source token balance", {}),
            self._step("get_quote", "Fetch swap quote and route", {"goal": goal}),
            self._step("approve_token", "Approve token spend if needed", {}),
            self._step("execute_swap", "Execute the swap transaction", {}),
        ]

    def _deploy_steps(self, goal: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._step("compile_contract", "Compile and verify contract code", {"goal": goal}),
            self._step("security_audit", "Run Glasswing security audit on compiled contract", {}),
            self._step("estimate_gas", "Estimate deployment gas cost", {}),
            self._step("deploy_contract", "Deploy contract to network", {}),
            self._step("verify_contract", "Verify contract on block explorer", {}),
        ]

    def _transfer_steps(self, goal: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._step("validate_address", "Validate recipient address", {}),
            self._step("check_balance", "Verify sufficient balance", {}),
            self._step("transfer", "Execute transfer", {"goal": goal}),
        ]

    def _staking_steps(self, goal: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._step("check_balance", "Verify token balance for staking", {}),
            self._step("select_validator", "Select optimal validator", {}),
            self._step("approve_token", "Approve staking contract", {}),
            self._step("stake", "Stake tokens", {"goal": goal}),
        ]

    def _governance_steps(self, goal: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._step("fetch_proposal", "Retrieve proposal details", {}),
            self._step("analyse_proposal", "Analyse proposal impact", {"goal": goal}),
            self._step("cast_vote", "Submit governance vote", {}),
        ]

    def _historical_failure_rate(self, action_type: str) -> float:
        """Return the failure rate for *action_type* from outcome history."""
        relevant = [e for e in self._outcome_history if e["action_type"] == action_type]
        if not relevant:
            return 0.0
        failures = sum(1 for e in relevant if not e.get("success", True))
        return failures / len(relevant)
