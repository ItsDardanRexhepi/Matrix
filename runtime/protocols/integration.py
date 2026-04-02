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

        logger.info(
            "ProtocolStack initialised for agent=%s (protocols loaded: %d/9)",
            self.agent_name,
            sum(1 for p in [
                self._jarvis, self._ultron, self._friday, self._vision,
                self._trajectory, self._outcome_learning,
                self._morpheus_triggers, self._rexhepi_gate, self._omega,
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

        # Jarvis — build identity context
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
            except Exception:
                logger.exception("Jarvis pre-process failed")

        # Friday — proactive checks
        if self._friday is not None:
            try:
                user_context = context.metadata.get("user_context", {})
                opportunities = await self._friday.check_opportunities(user_context)
                for opp in opportunities[:3]:
                    should_notify = await self._friday.should_notify(opp)
                    if should_notify:
                        suggestion = await self._friday.generate_suggestion(opp)
                        enrichments.append(f"[Friday Alert] {suggestion}")
            except Exception:
                logger.exception("Friday pre-process failed")

        # Vision — pattern detection on conversation history
        if self._vision is not None:
            try:
                activity = context.metadata.get("activity_history", [])
                if activity:
                    patterns = await self._vision.detect_patterns(activity)
                    for p in patterns[:3]:
                        enrichments.append(
                            f"[Pattern] {p.get('description', '')} "
                            f"(confidence: {p.get('confidence', 0):.0%})"
                        )
            except Exception:
                logger.exception("Vision pre-process failed")

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

        # Ultron risk assessment
        if self._ultron is not None:
            try:
                risk = await self._ultron.assess_risk(action)
                result["risk"] = risk
            except Exception:
                logger.exception("Ultron risk assessment failed")

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

        # Outcome recording
        if self._outcome_learning is not None:
            try:
                await self._outcome_learning.record_outcome(action, outcome, context)
            except Exception:
                logger.exception("OutcomeLearning post-action failed")

        # Trajectory prediction logging
        if self._trajectory is not None:
            try:
                await self._trajectory.predict_outcome(action, context)
            except Exception:
                logger.exception("Trajectory post-action logging failed")

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
