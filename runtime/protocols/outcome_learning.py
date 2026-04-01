"""
Outcome Learning Protocol — Captures outcomes and improves future decisions.
"""

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class OutcomeLearning:
    """Records action outcomes, extracts patterns from successes and
    failures, and adjusts confidence scores for future predictions."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._outcomes: list[dict[str, Any]] = []
        self._learned_patterns: dict[str, list[dict[str, Any]]] = {}
        self._confidence_adjustments: dict[str, float] = {}  # action_type -> cumulative delta
        self._max_outcomes = self.config.get("max_outcomes", 1000)
        logger.info("OutcomeLearning initialised")

    # ── Public API ────────────────────────────────────────────────────

    async def record_outcome(
        self,
        action: dict[str, Any],
        result: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        """Persist an outcome and extract any learnable pattern."""
        action_type = str(action.get("action_type", action.get("type", "unknown")))
        success = result.get("success", result.get("status") == "success")

        entry = {
            "id": str(uuid.uuid4()),
            "action_type": action_type,
            "action": action,
            "result": result,
            "context_snapshot": {
                k: v for k, v in context.items()
                if k in (
                    "network", "gas_price", "balance", "network_congestion",
                    "timestamp", "chain_id",
                )
            },
            "success": success,
            "timestamp": time.time(),
        }
        self._outcomes.append(entry)

        # Bound storage
        if len(self._outcomes) > self._max_outcomes:
            self._outcomes = self._outcomes[-self._max_outcomes:]

        # Extract pattern
        self._extract_pattern(entry)

        logger.info(
            "Recorded outcome: type=%s success=%s (total=%d)",
            action_type, success, len(self._outcomes),
        )

    async def get_learned_patterns(
        self, action_type: str
    ) -> list[dict[str, Any]]:
        """Return all learned patterns for *action_type*.

        Each pattern dict contains:
            pattern_id, action_type, description, confidence,
            sample_size, success_rate, conditions, recommendation
        """
        patterns = self._learned_patterns.get(action_type, [])
        if not patterns:
            # Attempt to generate on the fly from stored outcomes
            patterns = self._generate_patterns_for(action_type)
            if patterns:
                self._learned_patterns[action_type] = patterns

        logger.debug(
            "Returning %d learned patterns for '%s'", len(patterns), action_type
        )
        return list(patterns)

    async def adjust_confidence(
        self,
        prediction: dict[str, Any],
        actual: dict[str, Any],
    ) -> dict[str, Any]:
        """Compare *prediction* against *actual* outcome and return an
        adjusted confidence dict.

        Returns:
            original_confidence: float
            adjusted_confidence: float
            delta: float
            accuracy_assessment: str
        """
        predicted_success = prediction.get("predicted_success_rate", 0.5)
        actual_success = 1.0 if actual.get("success", False) else 0.0
        original_confidence = prediction.get("confidence", 0.5)

        # Error magnitude
        error = abs(predicted_success - actual_success)

        # Learning rate from config
        lr = self.config.get("learning_rate", 0.1)

        if error < 0.1:
            delta = lr * 0.5   # prediction was accurate — small boost
            assessment = "excellent"
        elif error < 0.3:
            delta = 0.0
            assessment = "acceptable"
        elif error < 0.6:
            delta = -lr * 0.5
            assessment = "poor"
        else:
            delta = -lr
            assessment = "very_poor"

        adjusted = max(0.05, min(original_confidence + delta, 1.0))

        # Track cumulative adjustment per action type
        action_type = prediction.get("action_type", "unknown")
        self._confidence_adjustments[action_type] = (
            self._confidence_adjustments.get(action_type, 0.0) + delta
        )

        result = {
            "original_confidence": round(original_confidence, 3),
            "adjusted_confidence": round(adjusted, 3),
            "delta": round(delta, 4),
            "accuracy_assessment": assessment,
            "cumulative_adjustment": round(
                self._confidence_adjustments.get(action_type, 0.0), 4
            ),
        }
        logger.info(
            "Confidence adjusted for '%s': %.3f -> %.3f (%s)",
            action_type, original_confidence, adjusted, assessment,
        )
        return result

    # ── Private helpers ───────────────────────────────────────────────

    def _extract_pattern(self, entry: dict[str, Any]) -> None:
        """Try to derive a pattern from the latest entry by comparing
        it against historical outcomes of the same type."""
        action_type = entry["action_type"]
        same_type = [o for o in self._outcomes if o["action_type"] == action_type]

        # Need minimum sample
        min_sample = self.config.get("min_pattern_sample", 5)
        if len(same_type) < min_sample:
            return

        successes = [o for o in same_type if o.get("success")]
        failures = [o for o in same_type if not o.get("success")]
        success_rate = len(successes) / len(same_type)

        # Check for context-based splits
        patterns: list[dict[str, Any]] = []

        # High-congestion correlation
        congested = [
            o for o in same_type
            if o.get("context_snapshot", {}).get("network_congestion", 0) > 0.7
        ]
        if len(congested) >= 3:
            cong_success = sum(1 for o in congested if o.get("success")) / len(congested)
            if abs(cong_success - success_rate) > 0.15:
                patterns.append({
                    "pattern_id": str(uuid.uuid4()),
                    "action_type": action_type,
                    "description": (
                        f"Under high network congestion, '{action_type}' success rate "
                        f"is {cong_success:.0%} vs overall {success_rate:.0%}"
                    ),
                    "confidence": min(len(congested) / 10.0, 1.0),
                    "sample_size": len(congested),
                    "success_rate": round(cong_success, 3),
                    "conditions": {"network_congestion": ">0.7"},
                    "recommendation": (
                        "Avoid this action during high congestion"
                        if cong_success < success_rate
                        else "This action performs well even under congestion"
                    ),
                })

        # General success-rate pattern
        if len(same_type) >= min_sample:
            patterns.append({
                "pattern_id": str(uuid.uuid4()),
                "action_type": action_type,
                "description": f"Overall success rate for '{action_type}': {success_rate:.0%} over {len(same_type)} attempts",
                "confidence": min(len(same_type) / 20.0, 1.0),
                "sample_size": len(same_type),
                "success_rate": round(success_rate, 3),
                "conditions": {},
                "recommendation": self._recommend(success_rate),
            })

        # Failure-mode clustering
        if failures:
            error_counts: dict[str, int] = {}
            for f in failures:
                err = f.get("result", {}).get("error", "unknown")
                error_counts[err] = error_counts.get(err, 0) + 1
            top_error = max(error_counts, key=error_counts.get)  # type: ignore[arg-type]
            if error_counts[top_error] >= 2:
                patterns.append({
                    "pattern_id": str(uuid.uuid4()),
                    "action_type": action_type,
                    "description": f"Most common failure for '{action_type}': '{top_error}' ({error_counts[top_error]} times)",
                    "confidence": min(error_counts[top_error] / 5.0, 1.0),
                    "sample_size": error_counts[top_error],
                    "success_rate": 0.0,
                    "conditions": {"error": top_error},
                    "recommendation": f"Add pre-check for '{top_error}' before attempting '{action_type}'.",
                })

        if patterns:
            self._learned_patterns[action_type] = patterns

    def _generate_patterns_for(self, action_type: str) -> list[dict[str, Any]]:
        """Fallback pattern generation from raw outcomes."""
        same_type = [o for o in self._outcomes if o["action_type"] == action_type]
        if len(same_type) < 3:
            return []

        success_rate = sum(1 for o in same_type if o.get("success")) / len(same_type)
        return [{
            "pattern_id": str(uuid.uuid4()),
            "action_type": action_type,
            "description": f"Success rate for '{action_type}': {success_rate:.0%} ({len(same_type)} samples)",
            "confidence": min(len(same_type) / 20.0, 1.0),
            "sample_size": len(same_type),
            "success_rate": round(success_rate, 3),
            "conditions": {},
            "recommendation": self._recommend(success_rate),
        }]

    @staticmethod
    def _recommend(success_rate: float) -> str:
        if success_rate >= 0.95:
            return "Highly reliable action. Proceed with confidence."
        if success_rate >= 0.80:
            return "Generally reliable. Standard precautions apply."
        if success_rate >= 0.60:
            return "Moderate reliability. Consider additional checks before executing."
        return "Low reliability. Investigate common failure modes and add safeguards."
