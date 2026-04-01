"""
Jarvis Protocol — Identity foundation for all agents.
Handles agent personality persistence, voice consistency,
memory integration, and context window management.
"""

import logging
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
