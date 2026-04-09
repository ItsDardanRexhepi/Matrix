from __future__ import annotations

"""
Jarvis Protocol — Identity foundation for all agents.
Handles agent personality persistence, voice consistency,
memory integration, context window management, and
structured planning that feeds back into the ReAct loop.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# ── Personality profiles ─────────────────────────────────────────────
PERSONALITY_PROFILES: dict[str, dict[str, float]] = {
    "trinity": {
        "warmth": 0.9,
        "formality": 0.3,
        "verbosity": 0.5,
        "technical": 0.2,
    },
    "morpheus": {
        "warmth": 0.4,
        "formality": 0.8,
        "verbosity": 0.3,
        "technical": 0.5,
    },
    "neo": {
        "warmth": 0.1,
        "formality": 0.9,
        "verbosity": 0.1,
        "technical": 1.0,
    },
}

# Voice style guides keyed by trait thresholds
_VOICE_RULES: dict[str, list[tuple[str, float, str, str]]] = {
    # (trait, threshold, direction, instruction)
    "warmth": [
        ("warmth", 0.7, "above", "Use friendly, empathetic language. Address the user personally."),
        ("warmth", 0.3, "below", "Maintain a neutral, objective tone. Avoid emotional language."),
    ],
    "formality": [
        ("formality", 0.7, "above", "Use precise terminology. Avoid slang or contractions."),
        ("formality", 0.4, "below", "Keep it conversational. Contractions and casual phrasing are fine."),
    ],
    "verbosity": [
        ("verbosity", 0.6, "above", "Provide thorough explanations with context."),
        ("verbosity", 0.3, "below", "Be concise. One sentence where one sentence suffices."),
    ],
    "technical": [
        ("technical", 0.8, "above", "Include exact figures, addresses, and technical parameters."),
        ("technical", 0.3, "below", "Translate technical details into plain language."),
    ],
}


class JarvisProtocol:
    """Identity foundation that ensures every agent response is on-brand,
    personality-consistent, and enriched with relevant memory."""

    def __init__(self, agent_name: str, config: dict[str, Any]) -> None:
        self.agent_name = agent_name.lower()
        self.config = config
        self.traits = self.get_personality_traits(self.agent_name)
        self._conversation_patterns: list[dict[str, Any]] = []
        self._memory_entries: list[dict[str, Any]] = []
        self._active_plan: dict[str, Any] | None = None
        logger.info("JarvisProtocol initialised for agent=%s", self.agent_name)

    # ── Public API ────────────────────────────────────────────────────

    async def build_identity_context(self) -> str:
        """Return the agent's identity prompt enriched with memory,
        personality traits, and conversation-history patterns."""
        sections: list[str] = []

        # Core identity
        sections.append(self._build_identity_header())

        # Personality encoding
        sections.append(self._build_personality_section())

        # Voice guide
        sections.append(self._build_voice_guide())

        # Memory context (most-recent first, capped to budget)
        memory_ctx = self._build_memory_context()
        if memory_ctx:
            sections.append(memory_ctx)

        # Conversation pattern hints
        pattern_ctx = self._build_pattern_context()
        if pattern_ctx:
            sections.append(pattern_ctx)

        identity_prompt = "\n\n".join(sections)
        logger.debug(
            "Identity context built for %s — %d chars",
            self.agent_name,
            len(identity_prompt),
        )
        return identity_prompt

    async def maintain_voice_consistency(self, draft_response: str) -> str:
        """Ensure *draft_response* matches the agent's voice profile.

        Returns the (potentially adjusted) response text.  Current
        implementation applies heuristic post-processing; a future
        revision will call the LLM for deeper rewriting when drift
        is detected.
        """
        if not draft_response:
            return draft_response

        adjusted = draft_response

        # Verbosity enforcement
        if self.traits.get("verbosity", 0.5) <= 0.3:
            adjusted = self._trim_verbose(adjusted)

        # Formality enforcement
        if self.traits.get("formality", 0.5) >= 0.7:
            adjusted = self._enforce_formal(adjusted)
        elif self.traits.get("formality", 0.5) <= 0.4:
            adjusted = self._relax_formality(adjusted)

        if adjusted != draft_response:
            logger.debug("Voice consistency adjusted response for %s", self.agent_name)

        return adjusted

    def get_personality_traits(self, agent_name: str) -> dict[str, float]:
        """Return the personality-trait dict for *agent_name*.

        Falls back to a balanced default if the agent is unknown.
        """
        name = agent_name.lower()

        # Check config overrides first
        overrides = self.config.get("personality_overrides", {}).get(name)
        if overrides and isinstance(overrides, dict):
            return {**PERSONALITY_PROFILES.get(name, {}), **overrides}

        profile = PERSONALITY_PROFILES.get(name)
        if profile is not None:
            return dict(profile)  # return a copy

        logger.warning("No personality profile for '%s'; using balanced defaults", name)
        return {"warmth": 0.5, "formality": 0.5, "verbosity": 0.5, "technical": 0.5}

    # ── Memory helpers (fed externally) ───────────────────────────────

    def ingest_memory(self, entries: list[dict[str, Any]]) -> None:
        """Accept memory entries retrieved from the memory subsystem."""
        self._memory_entries = list(entries)

    def record_conversation_pattern(self, pattern: dict[str, Any]) -> None:
        """Record an observed conversation pattern for future context."""
        self._conversation_patterns.append(pattern)
        # Keep a sliding window
        max_patterns = self.config.get("max_conversation_patterns", 50)
        if len(self._conversation_patterns) > max_patterns:
            self._conversation_patterns = self._conversation_patterns[-max_patterns:]

    # ── Planning ─────────────────────────────────────────────────────

    def build_plan(self, user_message: str, context_metadata: dict[str, Any]) -> dict[str, Any]:
        """Build a structured plan from the user's message and inject it
        into context metadata so the ReAct loop can reference it.

        The plan contains prioritized steps derived from intent keywords,
        conversation history, and known patterns.
        """
        intent_keywords = self._extract_intent_keywords(user_message)
        steps = self._derive_steps(intent_keywords, user_message, context_metadata)

        plan: dict[str, Any] = {
            "goal": user_message[:200],
            "created_at": time.time(),
            "steps": steps,
            "completed_steps": [],
            "current_step_index": 0,
        }
        self._active_plan = plan
        logger.info(
            "Built plan with %d steps for: %s",
            len(steps), user_message[:60],
        )
        return plan

    def suggest_next_action(self) -> dict[str, Any] | None:
        """Return the highest-priority unfinished step from the active
        plan, or None if no plan is active or all steps are done."""
        if self._active_plan is None:
            return None

        steps = self._active_plan.get("steps", [])
        completed = set(self._active_plan.get("completed_steps", []))
        for step in steps:
            if step["step_id"] not in completed:
                return step
        return None

    def mark_step_complete(self, step_id: str) -> None:
        """Mark a plan step as completed."""
        if self._active_plan is not None:
            completed = self._active_plan.setdefault("completed_steps", [])
            if step_id not in completed:
                completed.append(step_id)
                idx = self._active_plan.get("current_step_index", 0)
                self._active_plan["current_step_index"] = idx + 1

    def get_plan_enrichment(self) -> str:
        """Return a formatted string describing the active plan for
        injection into the system prompt."""
        if self._active_plan is None:
            return ""

        steps = self._active_plan.get("steps", [])
        completed = set(self._active_plan.get("completed_steps", []))
        if not steps:
            return ""

        lines = [f"[Active Plan] Goal: {self._active_plan['goal'][:120]}"]
        for step in steps:
            status = "DONE" if step["step_id"] in completed else "TODO"
            marker = "x" if status == "DONE" else " "
            lines.append(
                f"  [{marker}] (P{step['priority']}) {step['description']}"
            )

        next_action = self.suggest_next_action()
        if next_action:
            lines.append(f"  >> Next: {next_action['description']}")

        return "\n".join(lines)

    # ── Planning internals ───────────────────────────────────────────

    _INTENT_STEP_MAP: dict[str, list[dict[str, Any]]] = {
        "swap": [
            {"action": "check_balance", "description": "Check token balances", "priority": 1},
            {"action": "approve_token", "description": "Approve token for DEX", "priority": 2},
            {"action": "swap", "description": "Execute token swap", "priority": 3},
            {"action": "verify", "description": "Verify swap completed", "priority": 4},
        ],
        "transfer": [
            {"action": "check_balance", "description": "Check available balance", "priority": 1},
            {"action": "validate_address", "description": "Validate recipient address", "priority": 2},
            {"action": "transfer", "description": "Execute transfer", "priority": 3},
        ],
        "stake": [
            {"action": "check_balance", "description": "Check available balance", "priority": 1},
            {"action": "approve_token", "description": "Approve staking contract", "priority": 2},
            {"action": "stake", "description": "Stake tokens", "priority": 3},
        ],
        "bridge": [
            {"action": "check_balance", "description": "Check source chain balance", "priority": 1},
            {"action": "approve_token", "description": "Approve bridge contract", "priority": 2},
            {"action": "bridge", "description": "Bridge tokens to destination", "priority": 3},
            {"action": "verify", "description": "Verify bridge completed on destination", "priority": 4},
        ],
        "deploy": [
            {"action": "audit", "description": "Audit contract source", "priority": 1},
            {"action": "estimate_gas", "description": "Estimate deployment gas", "priority": 2},
            {"action": "deploy_contract", "description": "Deploy contract", "priority": 3},
            {"action": "verify", "description": "Verify deployment on explorer", "priority": 4},
        ],
        "claim": [
            {"action": "check_rewards", "description": "Check claimable rewards", "priority": 1},
            {"action": "claim_rewards", "description": "Claim rewards", "priority": 2},
        ],
        "vote": [
            {"action": "review_proposal", "description": "Review governance proposal", "priority": 1},
            {"action": "vote", "description": "Cast governance vote", "priority": 2},
        ],
    }

    def _extract_intent_keywords(self, message: str) -> list[str]:
        """Extract intent keywords from the user's message."""
        msg_lower = message.lower()
        found: list[str] = []
        for keyword in self._INTENT_STEP_MAP:
            if keyword in msg_lower:
                found.append(keyword)
        # Also check common synonyms
        synonyms = {
            "exchange": "swap", "trade": "swap", "send": "transfer",
            "delegate": "stake", "cross-chain": "bridge",
            "governance": "vote", "proposal": "vote",
        }
        for synonym, canonical in synonyms.items():
            if synonym in msg_lower and canonical not in found:
                found.append(canonical)
        return found

    def _derive_steps(
        self, intents: list[str], message: str, context_metadata: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Build prioritized steps from intent keywords."""
        steps: list[dict[str, Any]] = []
        step_counter = 0

        for intent in intents:
            template_steps = self._INTENT_STEP_MAP.get(intent, [])
            for tmpl in template_steps:
                step_counter += 1
                steps.append({
                    "step_id": f"step_{step_counter}",
                    "action": tmpl["action"],
                    "description": tmpl["description"],
                    "priority": tmpl["priority"],
                    "intent": intent,
                })

        if not steps:
            # Generic single-step plan for unknown intents
            steps.append({
                "step_id": "step_1",
                "action": "execute",
                "description": f"Process request: {message[:80]}",
                "priority": 1,
                "intent": "general",
            })

        # Sort by priority
        steps.sort(key=lambda s: s["priority"])
        return steps

    # ── Private helpers ───────────────────────────────────────────────

    def _build_identity_header(self) -> str:
        display = self.agent_name.capitalize()
        role_map = {
            "trinity": "the user's primary assistant — approachable, supportive, and clear.",
            "morpheus": "the guardian of irreversible actions — authoritative and measured.",
            "neo": "the technical execution engine — precise, minimal, and data-driven.",
        }
        role = role_map.get(self.agent_name, f"an agent named {display}.")
        return f"You are {display}, {role}"

    def _build_personality_section(self) -> str:
        lines = ["Personality traits:"]
        for trait, value in self.traits.items():
            bar = int(value * 10)
            lines.append(f"  {trait}: {'#' * bar}{'.' * (10 - bar)} ({value})")
        return "\n".join(lines)

    def _build_voice_guide(self) -> str:
        instructions: list[str] = []
        for _category, rules in _VOICE_RULES.items():
            for trait, threshold, direction, instruction in rules:
                val = self.traits.get(trait, 0.5)
                if direction == "above" and val >= threshold:
                    instructions.append(instruction)
                elif direction == "below" and val <= threshold:
                    instructions.append(instruction)
        if not instructions:
            return "Voice guide: maintain a balanced, professional tone."
        return "Voice guide:\n" + "\n".join(f"- {i}" for i in instructions)

    def _build_memory_context(self) -> str:
        if not self._memory_entries:
            return ""
        budget = self.config.get("memory_context_budget", 2000)
        lines = ["Relevant memories:"]
        chars = 0
        for entry in reversed(self._memory_entries):
            summary = entry.get("summary", str(entry))
            if chars + len(summary) > budget:
                break
            lines.append(f"- {summary}")
            chars += len(summary)
        return "\n".join(lines)

    def _build_pattern_context(self) -> str:
        if not self._conversation_patterns:
            return ""
        recent = self._conversation_patterns[-5:]
        lines = ["Observed conversation patterns:"]
        for p in recent:
            lines.append(f"- {p.get('description', str(p))}")
        return "\n".join(lines)

    # ── Voice post-processing ─────────────────────────────────────────

    @staticmethod
    def _trim_verbose(text: str) -> str:
        """Reduce paragraph count for low-verbosity agents."""
        paragraphs = text.split("\n\n")
        if len(paragraphs) > 3:
            return "\n\n".join(paragraphs[:3])
        return text

    @staticmethod
    def _enforce_formal(text: str) -> str:
        """Light pass to remove obvious informal contractions."""
        replacements = {
            "can't": "cannot",
            "won't": "will not",
            "don't": "do not",
            "isn't": "is not",
            "aren't": "are not",
            "it's": "it is",
            "that's": "that is",
            "there's": "there is",
            "we're": "we are",
            "they're": "they are",
            "you're": "you are",
            "I'm": "I am",
        }
        result = text
        for contraction, expansion in replacements.items():
            result = result.replace(contraction, expansion)
        return result

    @staticmethod
    def _relax_formality(text: str) -> str:
        """No-op for now; casual voice is the default LLM output."""
        return text
