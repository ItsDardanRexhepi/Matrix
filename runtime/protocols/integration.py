"""
Protocol Integration Layer — initializes and wires all protocols into the agent runtime.
Single entry point that the ReAct loop uses.
"""

from __future__ import annotations

import logging
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.react_loop import ReActContext

# Contract-related tool names that trigger Glasswing audit
_CONTRACT_TOOLS: set[str] = {
    "smart_contract", "deploy_contract", "platform_action",
    "contract_conversion", "security_audit",
}

logger = logging.getLogger(__name__)


class ProtocolStack:
    """Unified protocol interface for the ReAct loop.

    Lazily initialises all sub-protocols with graceful error handling.
    Any protocol that fails to load or errors at runtime is logged
    and skipped — the agent continues operating.
    """

    def __init__(self, config: dict, agent_name: str) -> None:
        self.config = config
        self.agent_name = agent_name

        # Lazy-init flags
        self._jarvis = None
        self._ultron = None
        self._friday = None
        self._vision = None
        self._trajectory = None
        self._outcome_learning = None
        self._morpheus_triggers = None
        self._rexhepi_gate = None
        self._omega = None
        self._auditor = None

        self._init_protocols()

    # ── Lazy initialisation ──────────────────────────────────────────

    def _init_protocols(self) -> None:
        """Initialise each protocol independently; failures are logged,
        never propagated."""
        try:
            from runtime.protocols.jarvis import JarvisProtocol
            self._jarvis = JarvisProtocol(self.agent_name, self.config)
        except Exception:
            logger.exception("Failed to initialise JarvisProtocol")

        try:
            from runtime.protocols.ultron import UltronProtocol
            self._ultron = UltronProtocol(self.config.get("ultron", {}))
        except Exception:
            logger.exception("Failed to initialise UltronProtocol")

        try:
            from runtime.protocols.friday import FridayProtocol
            self._friday = FridayProtocol(self.config.get("friday", {}))
        except Exception:
            logger.exception("Failed to initialise FridayProtocol")

        try:
            from runtime.protocols.vision import VisionProtocol
            self._vision = VisionProtocol(self.config.get("vision", {}))
        except Exception:
            logger.exception("Failed to initialise VisionProtocol")

        try:
            from runtime.protocols.trajectory import TrajectoryEngine
            self._trajectory = TrajectoryEngine(self.config.get("trajectory", {}))
        except Exception:
            logger.exception("Failed to initialise TrajectoryEngine")

        try:
            from runtime.protocols.outcome_learning import OutcomeLearning
            self._outcome_learning = OutcomeLearning(self.config.get("outcome_learning", {}))
        except Exception:
            logger.exception("Failed to initialise OutcomeLearning")

        try:
            from runtime.protocols.morpheus_triggers import MorpheusTriggerSystem
            self._morpheus_triggers = MorpheusTriggerSystem(self.config.get("morpheus", {}))
        except Exception:
            logger.exception("Failed to initialise MorpheusTriggerSystem")

        try:
            from runtime.protocols.rexhepi_gate import RexhepiGate
            self._rexhepi_gate = RexhepiGate(self.config.get("rexhepi", {}))
        except Exception:
            logger.exception("Failed to initialise RexhepiGate")

        try:
            from runtime.protocols.omega import OmegaMind
            self._omega = OmegaMind(self.agent_name, self.config)
        except Exception:
            logger.exception("Failed to initialise OmegaMind")

        try:
            from runtime.security.audit import ContractAuditor
            self._auditor = ContractAuditor(self.config)
        except Exception:
            logger.exception("Failed to initialise ContractAuditor")

        logger.info(
            "ProtocolStack initialised for agent=%s (protocols loaded: %d/10)",
            self.agent_name,
            sum(1 for p in [
                self._jarvis, self._ultron, self._friday, self._vision,
                self._trajectory, self._outcome_learning,
                self._morpheus_triggers, self._rexhepi_gate, self._omega,
                self._auditor,
            ] if p is not None),
        )

    # ── Pre-process: runs BEFORE the model call ──────────────────────

    async def pre_process(self, context: ReActContext) -> ReActContext:
        """Enrich context before the model sees it.

        - Jarvis identity context
        - Friday proactive checks
        - Vision pattern detection
        - Memory / conversational enrichment via Jarvis
        """
        enrichments: list[str] = []

        # Intent classification — score the user's message against known actions
        try:
            from runtime.chat.intent_actions import match_intent, get_param_prompt
            user_msg = ""
            for msg in reversed(context.conversation):
                if msg.role == "user":
                    user_msg = str(msg.content)
                    break
            if user_msg:
                matches = match_intent(user_msg)
                if matches:
                    top = matches[0]
                    context.metadata["matched_intent"] = top
                    hint_parts = [
                        f"[Intent Detection] The user likely wants: {top['action_name']} "
                        f"(confidence: {top['score']:.0%})",
                    ]
                    param_prompt = get_param_prompt(top["action_name"])
                    if param_prompt:
                        hint_parts.append(f"Required info: {param_prompt}")
                    if top.get("follow_up"):
                        hint_parts.append(f"If info is missing, ask: {top['follow_up']}")
                    enrichments.append("\n".join(hint_parts))

                    # Include runner-up if close in score
                    if len(matches) > 1 and matches[1]["score"] >= top["score"] * 0.7:
                        alt = matches[1]
                        enrichments.append(
                            f"[Intent Alt] Also possible: {alt['action_name']} "
                            f"(confidence: {alt['score']:.0%})"
                        )
        except Exception:
            logger.debug("Intent classification unavailable")

        # Jarvis — build identity context + structured plan
        if self._jarvis is not None:
            try:
                # Feed conversation patterns into Jarvis
                for msg in context.conversation[-5:]:
                    if msg.role == "user":
                        self._jarvis.record_conversation_pattern({
                            "description": f"User said: {str(msg.content)[:80]}",
                        })
                identity_ctx = await self._jarvis.build_identity_context()
                if identity_ctx:
                    enrichments.append(identity_ctx)

                # Build a structured plan from the latest user message
                user_msg = ""
                for msg in reversed(context.conversation):
                    if msg.role == "user":
                        user_msg = str(msg.content)
                        break
                if user_msg:
                    plan = self._jarvis.build_plan(user_msg, context.metadata)
                    context.metadata["active_plan"] = plan
                    plan_enrichment = self._jarvis.get_plan_enrichment()
                    if plan_enrichment:
                        enrichments.append(plan_enrichment)
            except Exception:
                logger.exception("Jarvis pre-process failed")

        # Friday — proactive checks with time-decay and actionable suggestions
        if self._friday is not None:
            try:
                user_context = context.metadata.get("user_context", {})
                friday_enrichments = await self._friday.build_enrichments(user_context)
                enrichments.extend(friday_enrichments)
                # Store active opportunities in metadata for other protocols
                context.metadata["active_opportunities"] = (
                    self._friday.get_active_opportunities()
                )
            except Exception:
                logger.exception("Friday pre-process failed")

        # Vision — pattern detection with summaries and proactive suggestions
        if self._vision is not None:
            try:
                activity = context.metadata.get("activity_history", [])
                # Determine current action from latest user message
                current_action = None
                for msg in reversed(context.conversation):
                    if msg.role == "user":
                        current_action = str(msg.content)[:50]
                        break
                vision_enrichments = await self._vision.build_pattern_enrichments(
                    activity, current_action,
                )
                enrichments.extend(vision_enrichments)
            except Exception:
                logger.exception("Vision pre-process failed")

        # OutcomeLearning — inject learned patterns for the detected action
        if self._outcome_learning is not None:
            try:
                # Determine action type from intent match or conversation
                action_type = ""
                matched = context.metadata.get("matched_intent")
                if matched:
                    action_type = matched.get("action_name", "")
                if action_type:
                    patterns = await self._outcome_learning.get_learned_patterns(action_type)
                    if patterns:
                        pattern_lines = [f"[Learned Patterns for '{action_type}']"]
                        for p in patterns[:3]:
                            pattern_lines.append(
                                f"  - {p['description']} "
                                f"(confidence: {p.get('confidence', 0):.0%}) "
                                f"→ {p.get('recommendation', '')}"
                            )
                        enrichments.append("\n".join(pattern_lines))
            except Exception:
                logger.debug("OutcomeLearning pattern injection failed")

        # Append enrichments to metadata for system prompt construction
        if enrichments:
            context.metadata["protocol_enrichments"] = enrichments

        return context

    # ── Pre-action: runs BEFORE each tool call ───────────────────────

    async def pre_action(
        self,
        tool_name: str,
        arguments: dict,
        context: dict,
    ) -> dict[str, Any]:
        """Gate-check a tool call before execution.

        Returns:
            approved: bool
            denial_reason: str | None
            morpheus_message: str | None
            risk: dict | None
        """
        result: dict[str, Any] = {
            "approved": True,
            "denial_reason": None,
            "morpheus_message": None,
            "risk": None,
        }

        action = {
            "action_type": tool_name,
            "type": tool_name,
            "parameters": arguments,
        }

        # Rexhepi gate evaluation
        if self._rexhepi_gate is not None:
            try:
                gate_result = await self._rexhepi_gate.evaluate(action, context)
                if not gate_result.get("approved", True):
                    result["approved"] = False
                    result["denial_reason"] = gate_result.get("reason", "Denied by security gate.")
                    return result
            except Exception:
                logger.exception("RexhepiGate pre-action failed")

        # Trajectory — outcome prediction (feeds into Ultron and Morpheus)
        if self._trajectory is not None:
            try:
                trajectory_prediction = await self._trajectory.build_pre_action_prediction(
                    tool_name, arguments, context,
                )
                result["trajectory"] = trajectory_prediction
                # If trajectory warns, surface it to Morpheus
                if trajectory_prediction.get("should_warn"):
                    risk_summary = trajectory_prediction.get("risk_summary", "")
                    existing_morpheus = result.get("morpheus_message") or ""
                    trajectory_warning = (
                        f"[Trajectory] Prediction for '{tool_name}': {risk_summary}"
                    )
                    result["morpheus_message"] = (
                        f"{existing_morpheus}\n{trajectory_warning}".strip()
                        if existing_morpheus
                        else trajectory_warning
                    )
            except Exception:
                logger.exception("Trajectory pre-action prediction failed")

        # Ultron risk assessment (enriched with trajectory data)
        if self._ultron is not None:
            try:
                # Inject trajectory prediction into action for Ultron to consider
                if result.get("trajectory"):
                    action["trajectory_prediction"] = result["trajectory"].get("prediction")
                risk = await self._ultron.assess_risk(action)
                result["risk"] = risk
            except Exception:
                logger.exception("Ultron risk assessment failed")

        # Glasswing security audit — runs on contract-related tool calls
        if self._auditor is not None and tool_name in _CONTRACT_TOOLS:
            try:
                source_code = arguments.get("source_code", "")
                if source_code:
                    audit_report = self._auditor.audit(
                        source_code, arguments.get("contract_name", "")
                    )
                    result["audit"] = audit_report.to_dict()
                    if self._auditor.should_block(audit_report):
                        result["approved"] = False
                        result["denial_reason"] = (
                            f"Glasswing audit blocked deployment: {audit_report.summary}"
                        )
                        result["morpheus_message"] = (
                            f"[Morpheus] Security audit failed. {audit_report.summary} "
                            "Review the findings and fix the vulnerabilities before deploying."
                        )
                        return result
                    elif audit_report.findings:
                        # Findings exist but not blocking — feed to Morpheus as context
                        if result.get("risk"):
                            result["risk"]["concerns"].append(
                                f"Glasswing audit: {audit_report.summary}"
                            )
            except Exception:
                logger.exception("Glasswing audit pre-action failed")

        # Morpheus intervention check
        if self._morpheus_triggers is not None:
            try:
                intervention = await self._morpheus_triggers.should_intervene(
                    action, context,
                )
                if intervention.get("should_intervene"):
                    result["morpheus_message"] = intervention.get("message", "")
            except Exception:
                logger.exception("Morpheus intervention check failed")

        return result

    # ── Post-action: runs AFTER each tool call ───────────────────────

    async def post_action(
        self,
        tool_name: str,
        arguments: dict,
        tool_result: str,
        context: dict,
    ) -> None:
        """Record outcomes and update state after a tool call completes."""
        action = {
            "action_type": tool_name,
            "type": tool_name,
            "parameters": arguments,
        }
        outcome = {
            "result": tool_result,
            "success": True,  # assume success if no exception
            "status": "success",
        }

        # Outcome recording + confidence feedback loop
        if self._outcome_learning is not None:
            try:
                await self._outcome_learning.record_outcome(action, outcome, context)

                # Feed outcome back to Trajectory to update base rates
                if self._trajectory is not None:
                    action_type = str(action.get("action_type", action.get("type", "unknown")))
                    patterns = await self._outcome_learning.get_learned_patterns(action_type)
                    for p in patterns:
                        if p.get("success_rate") is not None and p.get("sample_size", 0) >= 10:
                            # Blend learned rate into Trajectory base rates
                            current_base = self._trajectory._BASE_RATES.get(action_type, 0.85)
                            learned_rate = p["success_rate"]
                            # Weighted blend: 60% base, 40% learned (grows with sample size)
                            weight = min(p["sample_size"] / 50.0, 0.6)
                            blended = current_base * (1 - weight) + learned_rate * weight
                            self._trajectory._BASE_RATES[action_type] = round(blended, 3)
                            logger.info(
                                "Updated Trajectory base rate for '%s': %.3f -> %.3f (learned from %d outcomes)",
                                action_type, current_base, blended, p["sample_size"],
                            )
                            break
            except Exception:
                logger.exception("OutcomeLearning post-action failed")

        # Confidence calibration — compare Trajectory prediction vs actual outcome
        if self._outcome_learning is not None and self._trajectory is not None:
            try:
                # Retrieve the cached prediction for this action type
                action_type = str(action.get("action_type", action.get("type", "unknown")))
                cached_pred = None
                for pid, pred in self._trajectory._prediction_cache.items():
                    if pred.get("action_type") == action_type:
                        cached_pred = pred
                        break
                if cached_pred:
                    await self._outcome_learning.adjust_confidence(cached_pred, outcome)
            except Exception:
                logger.debug("Confidence calibration skipped")

        # Jarvis — mark plan step as complete if it matches the tool call
        if self._jarvis is not None and self._jarvis._active_plan is not None:
            try:
                next_step = self._jarvis.suggest_next_action()
                if next_step and next_step.get("action") == tool_name:
                    self._jarvis.mark_step_complete(next_step["step_id"])
                    logger.debug("Marked plan step '%s' complete", next_step["step_id"])
            except Exception:
                logger.exception("Jarvis plan step tracking failed")

    # ── Post-process: runs on the FINAL response ─────────────────────

    async def post_process(self, response: str, context: ReActContext) -> str:
        """Apply protocol transformations to the final agent response.

        - Jarvis voice consistency
        - Trajectory prediction logging
        """
        adjusted = response

        # Jarvis voice consistency
        if self._jarvis is not None:
            try:
                adjusted = await self._jarvis.maintain_voice_consistency(adjusted)
            except Exception:
                logger.exception("Jarvis post-process voice consistency failed")

        return adjusted
