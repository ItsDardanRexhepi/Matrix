from __future__ import annotations

"""
Omega Protocol — The synthesis layer that combines all protocol outputs
into a unified agent response. This is the orchestration brain.
"""

import logging
import time
from typing import Any

from runtime.protocols.jarvis import JarvisProtocol
from runtime.protocols.ultron import UltronProtocol
from runtime.protocols.friday import FridayProtocol
from runtime.protocols.vision import VisionProtocol
from runtime.protocols.trajectory import TrajectoryEngine
from runtime.protocols.outcome_learning import OutcomeLearning
from runtime.protocols.morpheus_triggers import MorpheusTriggerSystem
from runtime.protocols.rexhepi_gate import RexhepiGate

logger = logging.getLogger(__name__)


class OmegaMind:
    """The synthesis layer — orchestrates all sub-protocols and merges
    their outputs into a single, coherent agent response.

    Pipeline: Jarvis (identity) -> Ultron (planning) -> Vision (patterns)
              -> Friday (proactive) -> synthesis
    """

    def __init__(self, agent_name: str, config: dict[str, Any]) -> None:
        self.agent_name = agent_name
        self.config = config

        # Initialise sub-protocols
        self.jarvis = JarvisProtocol(agent_name, config)
        self.ultron = UltronProtocol(config.get("ultron", {}))
        self.friday = FridayProtocol(config.get("friday", {}))
        self.vision = VisionProtocol(config.get("vision", {}))
        self.trajectory = TrajectoryEngine(config.get("trajectory", {}))
        self.outcome_learning = OutcomeLearning(config.get("outcome_learning", {}))
        self.morpheus_triggers = MorpheusTriggerSystem(config.get("morpheus", {}))
        self.rexhepi_gate = RexhepiGate(config.get("rexhepi", {}))

        self._processing_count = 0
        logger.info("OmegaMind initialised for agent=%s", agent_name)

    # ── Main processing pipeline ──────────────────────────────────────

    async def process(
        self,
        user_message: str,
        conversation: list[dict[str, Any]],
        user_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the full protocol pipeline and return a unified response.

        Returns:
            response: str           — the agent's final text response
            suggested_actions: list  — actions the user can take
            risk_assessment: dict    — aggregated risk information
            proactive_alerts: list   — notifications from Friday
            identity_context: str    — the identity prompt used
            patterns: list           — detected patterns from Vision
            morpheus_intervention: dict | None — Morpheus message if triggered
            processing_time_ms: int
        """
        start = time.time()
        self._processing_count += 1

        # ── Phase 1: Identity (Jarvis) ────────────────────────────────
        identity_context = await self._phase_identity(conversation, user_context)

        # ── Phase 2: Intent & Planning (Ultron) ───────────────────────
        intent = self._extract_intent(user_message, conversation)
        plan_steps, risk_assessment = await self._phase_planning(intent, user_context)

        # ── Phase 3: Pattern Recognition (Vision) ─────────────────────
        patterns = await self._phase_patterns(user_context)

        # ── Phase 4: Proactive Intelligence (Friday) ──────────────────
        proactive_alerts = await self._phase_proactive(user_context)

        # ── Phase 5: Morpheus check ───────────────────────────────────
        morpheus_intervention = None
        if plan_steps:
            morpheus_intervention = await self._phase_morpheus(
                plan_steps, user_context
            )

        # ── Phase 6: Gate check (Rexhepi) ─────────────────────────────
        gate_results = await self._phase_gate(plan_steps, user_context)

        # ── Phase 7: Synthesis ────────────────────────────────────────
        response_text = self._synthesise(
            user_message=user_message,
            identity_context=identity_context,
            plan_steps=plan_steps,
            risk_assessment=risk_assessment,
            patterns=patterns,
            proactive_alerts=proactive_alerts,
            morpheus_intervention=morpheus_intervention,
            gate_results=gate_results,
        )

        # Voice consistency pass
        response_text = await self.jarvis.maintain_voice_consistency(response_text)

        # Build suggested actions from plan steps
        suggested_actions = self._build_suggested_actions(plan_steps, gate_results)

        elapsed_ms = int((time.time() - start) * 1000)

        result = {
            "response": response_text,
            "suggested_actions": suggested_actions,
            "risk_assessment": risk_assessment,
            "proactive_alerts": proactive_alerts,
            "identity_context": identity_context,
            "patterns": patterns,
            "morpheus_intervention": morpheus_intervention,
            "gate_results": gate_results,
            "processing_time_ms": elapsed_ms,
        }

        logger.info(
            "OmegaMind processed message #%d in %dms (actions=%d, alerts=%d)",
            self._processing_count, elapsed_ms,
            len(suggested_actions), len(proactive_alerts),
        )
        return result

    # ── Pipeline phases ───────────────────────────────────────────────

    async def _phase_identity(
        self,
        conversation: list[dict[str, Any]],
        user_context: dict[str, Any],
    ) -> str:
        """Build identity context via Jarvis."""
        # Feed memory if available
        memories = user_context.get("relevant_memories", [])
        if memories:
            self.jarvis.ingest_memory(memories)

        # Feed conversation patterns
        for entry in conversation[-5:]:
            if entry.get("role") == "user":
                self.jarvis.record_conversation_pattern({
                    "description": f"User said: {str(entry.get('content', ''))[:80]}",
                })

        return await self.jarvis.build_identity_context()

    async def _phase_planning(
        self, intent: str, user_context: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Decompose intent into plan steps and assess aggregate risk."""
        if not intent:
            return [], {"risk_level": "low", "concerns": [], "mitigations": []}

        plan_steps = await self.ultron.plan(intent, user_context)

        # Aggregate risk
        aggregate_risk = self._aggregate_risk(plan_steps)
        return plan_steps, aggregate_risk

    async def _phase_patterns(
        self, user_context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Run pattern detection on user activity."""
        activity = user_context.get("activity_history", [])
        if not activity:
            return []
        try:
            return await self.vision.detect_patterns(activity)
        except Exception:
            logger.exception("Pattern detection failed")
            return []

    async def _phase_proactive(
        self, user_context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Check for proactive opportunities."""
        try:
            opportunities = await self.friday.check_opportunities(user_context)
            alerts: list[dict[str, Any]] = []
            for opp in opportunities:
                should_notify = await self.friday.should_notify(opp)
                if should_notify:
                    suggestion = await self.friday.generate_suggestion(opp)
                    alerts.append({
                        "category": opp.get("category"),
                        "urgency": opp.get("urgency"),
                        "suggestion": suggestion,
                        "details": opp.get("details"),
                    })
            return alerts
        except Exception:
            logger.exception("Proactive check failed")
            return []

    async def _phase_morpheus(
        self,
        plan_steps: list[dict[str, Any]],
        user_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Check if Morpheus should intervene for any plan step."""
        for step in plan_steps:
            try:
                result = await self.morpheus_triggers.should_intervene(
                    step, user_context
                )
                if result.get("should_intervene"):
                    return result
            except Exception:
                logger.exception("Morpheus trigger check failed for step %s", step.get("id"))
        return None

    async def _phase_gate(
        self,
        plan_steps: list[dict[str, Any]],
        user_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Pass each plan step through the Rexhepi execution gate."""
        results: list[dict[str, Any]] = []
        for step in plan_steps:
            try:
                gate_result = await self.rexhepi_gate.evaluate(step, user_context)
                results.append({
                    "step_id": step.get("id"),
                    "action_type": step.get("action_type"),
                    **gate_result,
                })
            except Exception:
                logger.exception("Gate evaluation failed for step %s", step.get("id"))
                results.append({
                    "step_id": step.get("id"),
                    "action_type": step.get("action_type"),
                    "approved": False,
                    "reason": "Gate evaluation encountered an internal error.",
                })
        return results

    # ── Synthesis ─────────────────────────────────────────────────────

    def _synthesise(
        self,
        user_message: str,
        identity_context: str,
        plan_steps: list[dict[str, Any]],
        risk_assessment: dict[str, Any],
        patterns: list[dict[str, Any]],
        proactive_alerts: list[dict[str, Any]],
        morpheus_intervention: dict[str, Any] | None,
        gate_results: list[dict[str, Any]],
    ) -> str:
        """Merge all protocol outputs into a coherent response draft.

        In production, this feeds into the LLM with structured context.
        Here we build the prompt scaffold that the LLM will flesh out.
        """
        sections: list[str] = []

        # Morpheus intervention takes precedence
        if morpheus_intervention and morpheus_intervention.get("should_intervene"):
            sections.append(morpheus_intervention.get("message", ""))

        # Gate denials
        denied = [g for g in gate_results if not g.get("approved")]
        if denied:
            reasons = "; ".join(g.get("reason", "unknown") for g in denied)
            sections.append(
                f"Some actions cannot proceed at this time: {reasons}"
            )

        # Risk warnings for high/critical
        risk_level = risk_assessment.get("risk_level", "low")
        if risk_level in ("high", "critical"):
            concerns = risk_assessment.get("concerns", [])
            if concerns:
                sections.append("Risk concerns: " + " ".join(concerns))

        # Proactive alerts
        for alert in proactive_alerts[:3]:
            sections.append(f"[Alert] {alert.get('suggestion', '')}")

        # Plan summary
        if plan_steps:
            approved_steps = [
                s for s in plan_steps
                if not any(
                    g.get("step_id") == s.get("id") and not g.get("approved")
                    for g in gate_results
                )
            ]
            if approved_steps:
                step_descs = [s.get("description", "step") for s in approved_steps[:5]]
                sections.append("Plan: " + " -> ".join(step_descs))

        # If nothing special, just acknowledge
        if not sections:
            sections.append(f"Understood: {user_message[:200]}")

        return "\n\n".join(sections)

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_intent(
        message: str, conversation: list[dict[str, Any]]
    ) -> str:
        """Extract the primary intent from the user message.

        In production, the LLM classifies the intent; here we use
        the raw message as a passthrough.
        """
        return message.strip()

    @staticmethod
    def _aggregate_risk(steps: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute the aggregate risk across all plan steps."""
        risk_order = ["low", "medium", "high", "critical"]
        max_risk = "low"
        all_concerns: list[str] = []
        all_mitigations: list[str] = []

        for step in steps:
            details = step.get("risk_details", {})
            level = details.get("risk_level", step.get("estimated_risk", "low"))
            if risk_order.index(level) > risk_order.index(max_risk):
                max_risk = level
            all_concerns.extend(details.get("concerns", []))
            all_mitigations.extend(details.get("mitigations", []))

        return {
            "risk_level": max_risk,
            "concerns": list(dict.fromkeys(all_concerns)),  # dedupe, preserve order
            "mitigations": list(dict.fromkeys(all_mitigations)),
        }

    @staticmethod
    def _build_suggested_actions(
        plan_steps: list[dict[str, Any]],
        gate_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build a list of suggested actions the user can confirm."""
        denied_ids = {
            g.get("step_id") for g in gate_results if not g.get("approved")
        }
        actions: list[dict[str, Any]] = []
        for step in plan_steps:
            if step.get("id") in denied_ids:
                continue
            actions.append({
                "action_type": step.get("action_type"),
                "description": step.get("description"),
                "requires_confirmation": step.get("requires_confirmation", False),
                "estimated_risk": step.get("estimated_risk", "low"),
            })
        return actions
