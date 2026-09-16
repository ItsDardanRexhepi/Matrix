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
        self._morpheus_security = None
        # Distinguishes "the seam returned no gate" from "constructing the gate
        # RAISED". The second is a fault, and a fault must not read as an absence
        # (§CD sibling axis: the evaluate-time fault fails closed, the init-time
        # one silently skipped the whole block).
        self._morpheus_init_failed = False

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

        # Morpheus — the authoritative server-side security gate (the spine).
        # Consulted first in pre_action, ahead of RexhepiGate. Uses the process-wide
        # singleton so bans/freezes are GLOBAL across agents and requests. The full
        # config is passed so the layer resolves owner/blockchain/db subtrees (the
        # gateway creates the singleton first, at startup, with the DB handle).
        try:
            from runtime.security import get_morpheus_security  # seam → morpheus_security or no-op
            self._morpheus_security = get_morpheus_security(self.config)
        except Exception:
            logger.exception("Failed to initialise MorpheusSecurity")
            self._morpheus_init_failed = True

        logger.info(
            "ProtocolStack initialised for agent=%s (protocols loaded: %d/11)",
            self.agent_name,
            sum(1 for p in [
                self._jarvis, self._ultron, self._friday, self._vision,
                self._trajectory, self._outcome_learning,
                self._morpheus_triggers, self._rexhepi_gate, self._omega,
                self._auditor, self._morpheus_security,
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

                    # THE `unavailable` GUIDES CARRY NO `action_name`, BY
                    # DESIGN — that is what stops the model dispatching a
                    # disabled action. Subscripting it here raised KeyError,
                    # which the `except Exception` below swallowed at DEBUG,
                    # discarding the ENTIRE enrichment. Sixteen honest-
                    # unavailable dispositions across six closed domains
                    # shipped their routing half and silently dropped the half
                    # the user would actually read: measured, all sixteen
                    # delivered ZERO enrichments, indistinguishable from the
                    # request not being recognised at all — which is precisely
                    # what keeping the keywords was supposed to prevent.
                    #
                    # Second occurrence of the inert-fix pattern after
                    # ACTION_LABELS: a fix whose deliverable is text a user
                    # reads, resting on a consumer nobody drove.
                    if top.get("unavailable"):
                        hint_parts = [
                            "[Intent Detection] The user is asking for a "
                            "capability that is NOT AVAILABLE: "
                            f"{top.get('description', '')}",
                        ]
                        if top.get("follow_up"):
                            hint_parts.append(f"Tell them: {top['follow_up']}")
                        hint_parts.append(
                            "Do not attempt this action and do not imply it "
                            "succeeded."
                        )
                    else:
                        hint_parts = [
                            f"[Intent Detection] The user likely wants: "
                            f"{top['action_name']} (confidence: {top['score']:.0%})",
                        ]
                        param_prompt = get_param_prompt(top["action_name"])
                        if param_prompt:
                            hint_parts.append(f"Required info: {param_prompt}")
                        if top.get("follow_up"):
                            hint_parts.append(
                                f"If info is missing, ask: {top['follow_up']}"
                            )
                    enrichments.append("\n".join(hint_parts))

                    # Include runner-up if close in score. `.get` here too: an
                    # unavailable runner-up used to raise and cost the
                    # `[Intent Alt]` line, though the top's line survived
                    # because it was appended first.
                    if len(matches) > 1 and matches[1]["score"] >= top["score"] * 0.7:
                        alt = matches[1]
                        alt_name = alt.get("action_name")
                        if alt_name is None and alt.get("unavailable"):
                            enrichments.append(
                                "[Intent Alt] Also possible, but NOT "
                                f"AVAILABLE: {alt.get('description', '')}"
                            )
                        elif alt_name is not None:
                            enrichments.append(
                                f"[Intent Alt] Also possible: {alt_name} "
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

        # ── Live knowledge injection (non-blocking) ────────────────
        try:
            from runtime.knowledge.retriever import KnowledgeRetriever

            retriever = KnowledgeRetriever(self.config.get("blockchain", {}))
            user_msg = ""
            for msg in reversed(context.conversation):
                if msg.role == "user":
                    user_msg = str(msg.content)
                    break
            if user_msg:
                knowledge = await retriever.get_relevant_context(user_msg, self.agent_name)
                if knowledge:
                    parts = [item["content"] for item in knowledge if item.get("content")]
                    if parts:
                        enrichments.append("[Live Data] " + " | ".join(parts))
        except Exception:
            logger.debug("Knowledge retrieval skipped")

        # ── Blockchain state context ──────────────────────────────
        user_context = context.metadata.get("user_context", {})
        wallet = user_context.get("wallet_address", "")
        if wallet:
            state_parts = [f"Wallet: {wallet[:8]}...{wallet[-4:]}"]
            tier = user_context.get("tier", "free")
            state_parts.append(f"Tier: {tier.title()}")
            balance = user_context.get("eth_balance")
            if balance is not None:
                state_parts.append(f"Balance: {balance} ETH")
            if state_parts:
                enrichments.append("[User Context] " + " | ".join(state_parts))

        # ── Error recovery context ────────────────────────────────
        prev_error = context.metadata.get("previous_error")
        if prev_error:
            enrichments.append(
                f"[Previous Attempt Failed] Last action: {prev_error.get('action', 'unknown')}. "
                f"Reason: {prev_error.get('reason', 'unknown')}. "
                "Do not repeat the same approach. Acknowledge the limitation "
                "clearly and offer alternatives."
            )

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

        # What the call DOES, not what the tool is called (§DL.4): the twin
        # tools take their real verb in arguments.action, and a contract
        # deployment or an ERC-20 approve signed with the platform key must
        # reach the gate as a signing action, not as "smart_contract".
        from runtime.security.action_map import (
            allowance_violation, beneficiary_violation, canonical_action,
        )
        action_type, signs = canonical_action(tool_name, arguments)
        action = {
            "action_type": action_type,
            "type": action_type,
            "tool": tool_name,
            "tool_action": (arguments.get("action") if isinstance(arguments, dict) else None),
            "signs_with_platform_key": bool(signs),
            "parameters": arguments,
        }

        # Seam-level refusals that need no gate: a platform-signed action
        # pointed at somebody else's address, and a platform-key approve
        # without an operator-set cap.
        if signs:
            identity = str(
                (context or {}).get("wallet") or (context or {}).get("wallet_address")
                or (context or {}).get("identity") or ""
            ).strip()
            refusal = (beneficiary_violation(tool_name, arguments, identity)
                       or allowance_violation(tool_name, arguments, self.config))
            if refusal:
                result["approved"] = False
                result["denial_reason"] = refusal
                return result

        # Morpheus — the security spine. Runs FIRST, so every execution path
        # passes him. Authoritative server-side allow/deny (binding only in
        # ENFORCE mode; OBSERVE logs without blocking while the layer is
        # unverified). App-side Morpheus is UX only; THIS is the boundary.
        if self._morpheus_security is None and self._morpheus_init_failed:
            # The gate could not be CONSTRUCTED. That is a fault, not a posture,
            # and it gets the same fail-direction the evaluate-time fault gets:
            # a value-moving or unrecognised action must not proceed ungated.
            from runtime.access_policy import could_move_value
            if could_move_value(action_type):
                logger.error("Morpheus gate unavailable (init failed); FAIL-CLOSED deny "
                             "(action=%s)", action_type)
                result["approved"] = False
                result["denial_reason"] = (
                    "This action couldn't be authorized right now. Please try again."
                )
                return result
            logger.warning("Morpheus gate unavailable (init failed); benign read allowed "
                           "(action=%s)", action_type)

        if self._morpheus_security is not None:
            try:
                decision = await self._morpheus_security.evaluate(action, context)
                result["morpheus_security"] = decision
                if not decision.get("allow", True):
                    result["approved"] = False
                    result["denial_reason"] = decision.get(
                        "reason", "Blocked by Morpheus security."
                    )
                    return result
            except Exception:
                logger.exception("MorpheusSecurity pre-action failed")
                # Fail-direction on a gate fault: a value-moving / owner-gated action
                # must NOT proceed ungated — fail CLOSED (deny). A benign read may
                # continue so a transient fault doesn't break it. Coarse public label
                # only; for the platform_action mega-tool the real action is in the
                # arguments. The authoritative classification lives in the private gate.
                # The canonical action type carries the twins' real verb and
                # platform_action's inner action alike.
                from runtime.access_policy import could_move_value
                if could_move_value(action_type):
                    result["approved"] = False
                    result["denial_reason"] = (
                        "This action couldn't be authorized right now. Please try again."
                    )
                    return result

        # Rexhepi gate evaluation — the URF reasoning loop scores the six
        # gates and resolves one canonical outcome. Only EXECUTE is a green
        # light; PROBE/ASK/DEFER/ABORT hold the action and tell the loop what
        # canonical move to make instead (URF §12).
        if self._rexhepi_gate is not None:
            try:
                gate_result = await self._rexhepi_gate.evaluate(action, context)
                result["urf"] = {
                    "outcome": gate_result.get("outcome"),
                    "scores": gate_result.get("scores"),
                    "decision_line": gate_result.get("decision_line"),
                    "rationale": gate_result.get("rationale"),
                    "requires_approval": gate_result.get("requires_approval"),
                }
                if not gate_result.get("approved", True):
                    result["approved"] = False
                    outcome = gate_result.get("outcome", "ABORT")
                    reason = gate_result.get("reason") or gate_result.get("rationale", "")
                    result["denial_reason"] = f"[URF: {outcome}] {reason}".strip()
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
        from runtime.security.action_map import canonical_action
        action_type, signs = canonical_action(tool_name, arguments)
        action = {
            "action_type": action_type,
            "type": action_type,
            "tool": tool_name,
            "tool_action": (arguments.get("action") if isinstance(arguments, dict) else None),
            "signs_with_platform_key": bool(signs),
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
