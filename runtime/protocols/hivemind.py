"""
HiveMind Protocol — multi-instance collective intelligence architecture.
Specialized reasoning instances share state and reach consensus.
"""

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

INSTANCE_TYPES: list[str] = [
    "geopolitical", "financial", "technical",
    "governance", "creative", "synthesis",
]


class HiveMindProtocol:
    """Multi-instance collective intelligence.

    Spawns specialised reasoning instances for a task, collects their
    outputs, and drives weighted consensus with explicit dissent
    recording.  Degrades gracefully when instances are unavailable.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

        # ── Internal state ────────────────────────────────────────────
        # task_id -> list[instance_dict]
        self._instances: dict[str, list[dict[str, Any]]] = {}
        # domain -> shared context data
        self._shared_state: dict[str, Any] = {}
        # domain -> accuracy score (0.0 – 1.0)
        self._specialization_scores: dict[str, float] = {
            d: 0.5 for d in INSTANCE_TYPES
        }
        # domain -> {"attempts": int, "successes": int}
        self._accuracy_tracker: dict[str, dict[str, int]] = {
            d: {"attempts": 0, "successes": 0} for d in INSTANCE_TYPES
        }
        self._consensus_history: list[dict[str, Any]] = []
        self._max_history = int(self.config.get("max_history", 500))

        logger.info("HiveMindProtocol initialised with %d instance types",
                     len(INSTANCE_TYPES))

    # ── Public API ────────────────────────────────────────────────────

    async def spawn_instance(
        self, domain: str, task: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a specialised reasoning instance for *domain*.

        Args:
            domain: One of INSTANCE_TYPES (or a custom domain).
            task: Task description dict (must contain at least 'description').

        Returns:
            instance dict with id, domain, task_id, status, created_at.
        """
        task_id = task.get("task_id", str(uuid.uuid4()))

        instance: dict[str, Any] = {
            "instance_id": str(uuid.uuid4()),
            "domain": domain,
            "task_id": task_id,
            "task": task,
            "status": "running",
            "output": None,
            "created_at": time.time(),
            "completed_at": None,
        }

        self._instances.setdefault(task_id, []).append(instance)

        # Simulate instance execution — produce a stub output.
        # In production this dispatches to the real reasoning backend.
        instance["output"] = {
            "domain": domain,
            "analysis": f"[{domain}] analysis of: {task.get('description', 'unknown')}",
            "confidence": self._specialization_scores.get(domain, 0.5),
            "recommendations": [],
            "concerns": [],
        }
        instance["status"] = "completed"
        instance["completed_at"] = time.time()

        logger.info("Spawned %s instance %s for task %s",
                     domain, instance["instance_id"], task_id)
        return instance

    async def collect_outputs(self, task_id: str) -> list[dict[str, Any]]:
        """Gather all instance outputs for *task_id*.

        Returns only completed instances.  If none exist, returns an
        empty list (graceful degradation).
        """
        instances = self._instances.get(task_id, [])
        outputs: list[dict[str, Any]] = []

        for inst in instances:
            if inst["status"] == "completed" and inst["output"] is not None:
                outputs.append({
                    "instance_id": inst["instance_id"],
                    "domain": inst["domain"],
                    "output": inst["output"],
                    "completed_at": inst["completed_at"],
                })
            elif inst["status"] == "running":
                logger.warning("Instance %s still running — skipping",
                               inst["instance_id"])

        logger.debug("Collected %d outputs for task %s", len(outputs), task_id)
        return outputs

    async def reach_consensus(
        self, outputs: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Compute weighted consensus across instance outputs.

        Weighting: relevance * confidence * specialization_score

        Returns:
            consensus_id, agreed_recommendation, confidence,
            contributing_instances, dissents, timestamp
        """
        if not outputs:
            return {
                "consensus_id": str(uuid.uuid4()),
                "agreed_recommendation": None,
                "confidence": 0.0,
                "contributing_instances": [],
                "dissents": [],
                "timestamp": time.time(),
                "status": "no_outputs",
            }

        weighted_entries: list[dict[str, Any]] = []
        for entry in outputs:
            output = entry.get("output", {})
            domain = entry.get("domain", "unknown")

            relevance = output.get("relevance", 1.0)
            confidence = output.get("confidence", 0.5)
            spec_score = self._specialization_scores.get(domain, 0.5)

            weight = relevance * confidence * spec_score
            weighted_entries.append({
                "instance_id": entry.get("instance_id"),
                "domain": domain,
                "weight": round(weight, 4),
                "output": output,
            })

        # Sort by weight descending — top entry is the primary recommendation
        weighted_entries.sort(key=lambda e: e["weight"], reverse=True)

        primary = weighted_entries[0]
        primary_analysis = primary["output"].get("analysis", "")
        primary_recs = primary["output"].get("recommendations", [])

        # Dissent: instances whose analysis or recommendations significantly
        # differ from the primary (simple heuristic: lower-weight entries
        # with concerns that the primary doesn't share).
        dissents: list[dict[str, Any]] = []
        for entry in weighted_entries[1:]:
            concerns = entry["output"].get("concerns", [])
            primary_concerns = primary["output"].get("concerns", [])
            unique_concerns = [c for c in concerns if c not in primary_concerns]
            if unique_concerns:
                dissents.append({
                    "instance_id": entry["instance_id"],
                    "domain": entry["domain"],
                    "weight": entry["weight"],
                    "dissenting_concerns": unique_concerns,
                })

        total_weight = sum(e["weight"] for e in weighted_entries)
        avg_confidence = total_weight / len(weighted_entries) if weighted_entries else 0.0

        consensus = {
            "consensus_id": str(uuid.uuid4()),
            "agreed_recommendation": primary_analysis,
            "recommendations": primary_recs,
            "confidence": round(avg_confidence, 4),
            "contributing_instances": [
                {"instance_id": e["instance_id"], "domain": e["domain"],
                 "weight": e["weight"]}
                for e in weighted_entries
            ],
            "dissents": dissents,
            "timestamp": time.time(),
            "status": "consensus_reached",
        }

        # Record history
        self._consensus_history.append(consensus)
        if len(self._consensus_history) > self._max_history:
            self._consensus_history = self._consensus_history[-self._max_history:]

        logger.info("Consensus reached: confidence=%.4f, dissents=%d",
                     avg_confidence, len(dissents))
        return consensus

    async def get_shared_state(self) -> dict[str, Any]:
        """Return the shared context bus across all instances."""
        return dict(self._shared_state)

    async def update_shared_state(
        self, domain: str, data: dict[str, Any]
    ) -> None:
        """Update the shared context bus for *domain*."""
        self._shared_state[domain] = {
            **(self._shared_state.get(domain, {})),
            **data,
            "_updated_at": time.time(),
        }
        logger.debug("Shared state updated for domain '%s'", domain)

    async def get_specialization_scores(self) -> dict[str, float]:
        """Return per-domain accuracy / specialisation scores.

        Scores are updated as outcomes are recorded via
        ``_record_outcome`` (internal helper).
        """
        return dict(self._specialization_scores)

    # ── Internal helpers ──────────────────────────────────────────────

    def _record_outcome(
        self, domain: str, success: bool
    ) -> None:
        """Update specialisation score for *domain* based on outcome."""
        tracker = self._accuracy_tracker.setdefault(
            domain, {"attempts": 0, "successes": 0}
        )
        tracker["attempts"] += 1
        if success:
            tracker["successes"] += 1

        attempts = tracker["attempts"]
        if attempts > 0:
            self._specialization_scores[domain] = round(
                tracker["successes"] / attempts, 4
            )
