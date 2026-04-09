from __future__ import annotations

"""
Rexhepi Conversational Layer — transforms agent interactions from command-response
into genuine fluid dialogue. Memory, personality, proactive initiative, transparency.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# ── User state detection constants ────────────────────────────────────

_USER_STATES: list[str] = [
    "stressed", "curious", "uncertain", "focused", "strategic",
]

_URGENCY_MARKERS: list[str] = [
    "asap", "urgent", "immediately", "right now", "hurry",
    "critical", "emergency", "quick", "fast",
]

# Adaptation strategies keyed by detected state
_ADAPTATION_RULES: dict[str, dict[str, Any]] = {
    "stressed": {
        "tone": "concise",
        "instruction": "Keep responses short and actionable. No filler.",
        "max_length_ratio": 0.5,
    },
    "curious": {
        "tone": "expansive",
        "instruction": "Provide deeper context, analogies, and related insights.",
        "max_length_ratio": 1.5,
    },
    "uncertain": {
        "tone": "transparent",
        "instruction": ("Explain reasoning step-by-step. Surface trade-offs "
                        "and confidence levels explicitly."),
        "max_length_ratio": 1.2,
    },
    "focused": {
        "tone": "minimal",
        "instruction": "Answer directly. Omit pleasantries and preamble.",
        "max_length_ratio": 0.4,
    },
    "strategic": {
        "tone": "full_synthesis",
        "instruction": ("Provide comprehensive analysis with options, risks, "
                        "and recommended path forward."),
        "max_length_ratio": 2.0,
    },
}

# Per-agent dialogue principles
_AGENT_PRINCIPLES: dict[str, list[str]] = {
    "neo": [
        "Speak with calm authority; never panic.",
        "Prefer strategic framing over tactical detail.",
        "Reference prior conversations when relevant.",
        "Ask clarifying questions rather than assume.",
    ],
    "trinity": [
        "Lead with data and evidence.",
        "Be direct — brevity is valued.",
        "Highlight risks proactively.",
        "Confirm understanding before executing.",
    ],
    "morpheus": [
        "Guide with questions more than answers.",
        "Use metaphor and narrative where it aids clarity.",
        "Challenge assumptions respectfully.",
        "Surface second-order consequences.",
    ],
}

_DEFAULT_PRINCIPLES: list[str] = [
    "Maintain conversational continuity across sessions.",
    "Adapt tone to user state without being asked.",
    "Be transparent about confidence and limitations.",
    "Offer proactive insights when context warrants it.",
]


class ConversationalLayer:
    """Transforms flat command-response exchanges into fluid dialogue
    with memory, personality adaptation, proactive initiative, and
    transparency."""

    def __init__(
        self, agent_name: str, config: dict[str, Any] | None = None
    ) -> None:
        self.agent_name = agent_name.lower()
        self.config = config or {}

        # ── Internal state ────────────────────────────────────────────
        # user_id -> list of preference records
        self._user_preferences: dict[str, list[dict[str, Any]]] = {}
        # user_id -> relationship context (tone preferences, history summary)
        self._relationship_context: dict[str, dict[str, Any]] = {}
        # user_id -> recent detected states
        self._user_state_history: dict[str, list[dict[str, Any]]] = {}
        self._max_preference_entries = int(
            self.config.get("max_preference_entries", 200)
        )

        logger.info("ConversationalLayer initialised for agent '%s'",
                     self.agent_name)

    # ── Public API ────────────────────────────────────────────────────

    async def enrich_context(
        self,
        conversation: list[dict[str, Any]],
        user_id: str,
    ) -> dict[str, Any]:
        """Add conversational memory, user preferences, and relationship
        context to the current exchange.

        Returns:
            user_preferences: list[dict]
            relationship: dict
            detected_state: dict
            dialogue_principles: list[str]
            conversation_length: int
        """
        prefs = self._user_preferences.get(user_id, [])
        relationship = self._relationship_context.get(user_id, {
            "interaction_count": 0,
            "first_seen": time.time(),
            "preferred_tone": None,
        })

        # Bump interaction count
        relationship["interaction_count"] = relationship.get(
            "interaction_count", 0) + 1
        relationship["last_seen"] = time.time()
        self._relationship_context[user_id] = relationship

        # Detect user state from recent messages
        user_messages = [
            m for m in conversation if m.get("role") == "user"
        ]
        detected_state = await self.detect_user_state(user_messages)

        principles = await self.get_dialogue_principles(self.agent_name)

        return {
            "user_preferences": prefs[-20:],  # last 20
            "relationship": relationship,
            "detected_state": detected_state,
            "dialogue_principles": principles,
            "conversation_length": len(conversation),
        }

    async def adapt_response(
        self, response: str, user_state: dict[str, Any]
    ) -> str:
        """Adapt tone and depth of *response* based on *user_state*.

        For stressed users: truncate to essentials.
        For curious users: expand.
        For uncertain users: add reasoning transparency.
        For focused users: strip to minimum.
        For strategic users: full synthesis.
        """
        state_label = user_state.get("state", "focused")
        rules = _ADAPTATION_RULES.get(state_label, _ADAPTATION_RULES["focused"])
        max_ratio = rules["max_length_ratio"]

        # Apply length constraint as a rough adaptation
        target_len = int(len(response) * max_ratio)

        if max_ratio < 1.0 and len(response) > target_len:
            # Truncate — keep first target_len chars, ensure we end at a
            # sentence boundary if possible.
            truncated = response[:target_len]
            last_period = truncated.rfind(".")
            if last_period > target_len * 0.5:
                truncated = truncated[: last_period + 1]
            adapted = truncated
        elif max_ratio > 1.0:
            # In production the LLM would expand; here we annotate.
            instruction = rules["instruction"]
            adapted = f"{response}\n\n[Adaptation note: {instruction}]"
        else:
            adapted = response

        logger.debug("Adapted response for state '%s' (ratio=%.1f)",
                     state_label, max_ratio)
        return adapted

    async def detect_user_state(
        self, messages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Classify the user's current state from recent messages.

        Heuristics:
            - Message length: very short = focused, very long = strategic
            - Question frequency: many questions = curious
            - Topic switching: frequent switches = stressed
            - Urgency markers: urgent language = stressed
            - Hedging language: "maybe", "not sure" = uncertain

        Returns:
            state: str (one of _USER_STATES)
            confidence: float
            signals: list[str]
        """
        if not messages:
            return {"state": "focused", "confidence": 0.3, "signals": []}

        recent = messages[-5:]
        signals: list[str] = []
        scores: dict[str, float] = {s: 0.0 for s in _USER_STATES}

        contents = [str(m.get("content", "")) for m in recent]
        avg_length = sum(len(c) for c in contents) / len(contents) if contents else 0

        # ── Length signal ─────────────────────────────────────────────
        if avg_length < 30:
            scores["focused"] += 1.0
            signals.append("short_messages")
        elif avg_length > 300:
            scores["strategic"] += 1.0
            signals.append("long_messages")

        # ── Question frequency ────────────────────────────────────────
        question_count = sum(c.count("?") for c in contents)
        if question_count >= 3:
            scores["curious"] += 1.5
            signals.append("many_questions")
        elif question_count >= 1:
            scores["curious"] += 0.5

        # ── Urgency markers ───────────────────────────────────────────
        combined_lower = " ".join(contents).lower()
        urgency_hits = sum(1 for m in _URGENCY_MARKERS if m in combined_lower)
        if urgency_hits >= 2:
            scores["stressed"] += 2.0
            signals.append("urgency_language")
        elif urgency_hits == 1:
            scores["stressed"] += 0.8
            signals.append("mild_urgency")

        # ── Hedging / uncertainty ─────────────────────────────────────
        hedging_words = ["maybe", "not sure", "i think", "possibly",
                         "might", "uncertain", "don't know"]
        hedge_hits = sum(1 for h in hedging_words if h in combined_lower)
        if hedge_hits >= 2:
            scores["uncertain"] += 1.5
            signals.append("hedging_language")
        elif hedge_hits == 1:
            scores["uncertain"] += 0.5

        # ── Topic switching ───────────────────────────────────────────
        if len(contents) >= 3:
            # Rough heuristic: if consecutive messages share few words, topics are switching
            switches = 0
            for i in range(1, len(contents)):
                words_prev = set(contents[i - 1].lower().split())
                words_curr = set(contents[i].lower().split())
                overlap = len(words_prev & words_curr)
                if overlap < 2:
                    switches += 1
            if switches >= 2:
                scores["stressed"] += 1.0
                signals.append("topic_switching")

        # ── Determine winner ──────────────────────────────────────────
        best_state = max(scores, key=scores.get)  # type: ignore[arg-type]
        best_score = scores[best_state]
        total_score = sum(scores.values())
        confidence = round(best_score / total_score, 3) if total_score > 0 else 0.3

        result = {
            "state": best_state,
            "confidence": confidence,
            "signals": signals,
        }

        logger.debug("Detected user state: %s (confidence=%.3f)",
                      best_state, confidence)
        return result

    async def generate_initiative(
        self, context: dict[str, Any]
    ) -> str | None:
        """Generate a proactive conversation opener if warranted.

        Returns *None* if no initiative is appropriate.
        """
        relationship = context.get("relationship", {})
        detected_state = context.get("detected_state", {})
        interaction_count = relationship.get("interaction_count", 0)

        # Don't be proactive on the very first interaction
        if interaction_count < 2:
            return None

        state = detected_state.get("state", "focused")

        # Only generate initiative for stressed or uncertain states
        if state == "stressed":
            return ("I notice things seem time-sensitive. "
                    "Want me to prioritise the most critical items first?")
        if state == "uncertain":
            return ("It sounds like there's some ambiguity here. "
                    "Would it help if I walked through the options with "
                    "trade-offs and confidence levels?")

        # For strategic users after several interactions
        if state == "strategic" and interaction_count > 5:
            return ("Based on our recent discussions, I've noticed some "
                    "recurring themes. Want me to synthesise a strategic "
                    "overview?")

        return None

    async def learn_preference(
        self, user_id: str, interaction: dict[str, Any]
    ) -> None:
        """Track what communication styles work for *user_id*.

        Interaction dict should include:
            style: str — the style used (concise, expansive, etc.)
            effective: bool — whether the user responded positively
            context: dict — optional additional context
        """
        entry = {
            "style": interaction.get("style", "unknown"),
            "effective": interaction.get("effective", True),
            "context": interaction.get("context", {}),
            "timestamp": time.time(),
        }

        prefs = self._user_preferences.setdefault(user_id, [])
        prefs.append(entry)

        # Bound storage
        if len(prefs) > self._max_preference_entries:
            self._user_preferences[user_id] = prefs[-self._max_preference_entries:]

        # Update relationship preferred tone if we have enough data
        effective_styles = [p["style"] for p in prefs if p.get("effective")]
        if len(effective_styles) >= 3:
            # Most frequent effective style
            style_counts: dict[str, int] = {}
            for s in effective_styles:
                style_counts[s] = style_counts.get(s, 0) + 1
            preferred = max(style_counts, key=style_counts.get)  # type: ignore[arg-type]
            rel = self._relationship_context.setdefault(user_id, {})
            rel["preferred_tone"] = preferred

        logger.debug("Learned preference for user '%s': style=%s effective=%s",
                      user_id, entry["style"], entry["effective"])

    async def get_dialogue_principles(
        self, agent_name: str
    ) -> list[str]:
        """Return agent-specific dialogue rules.

        Falls back to default principles if the agent name is not
        recognised.
        """
        name = agent_name.lower()
        return list(
            _AGENT_PRINCIPLES.get(name, _DEFAULT_PRINCIPLES)
        )
