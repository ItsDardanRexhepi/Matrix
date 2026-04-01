"""
Outcome Learning Schema — canonical schema for decision outcome records.
Append-only JSONL storage with linkers and replay validation.
"""

import copy
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# ── Schema definition ────────────────────────────────────────────────

_REQUIRED_FIELDS: list[str] = [
    "decision_id", "subsystem", "timestamp", "selected_action",
    "realized_outcome", "label",
]

_OPTIONAL_FIELDS: list[str] = [
    "validation_horizon", "avoided_loss", "missed_opportunity",
    "confidence", "completeness",
]

_ALL_FIELDS: set[str] = set(_REQUIRED_FIELDS) | set(_OPTIONAL_FIELDS)

_VALID_LABELS: set[str] = {"success", "failure", "neutral"}

# Maximum parameter change per learning cycle (10%)
_MAX_PARAM_CHANGE_RATIO: float = 0.10


class OutcomeSchema:
    """Canonical schema for decision outcome records.

    Each record captures what was decided, what actually happened,
    and metadata for downstream learning.
    """

    def create_record(self, **kwargs: Any) -> dict[str, Any]:
        """Create a validated outcome record.

        Required kwargs:
            decision_id, subsystem, selected_action, realized_outcome, label

        Optional kwargs:
            timestamp, validation_horizon, avoided_loss,
            missed_opportunity, confidence, completeness

        Returns a fully-formed record dict.
        Raises ValueError on missing required fields or invalid label.
        """
        # Defaults
        record: dict[str, Any] = {
            "decision_id": kwargs.get("decision_id"),
            "subsystem": kwargs.get("subsystem"),
            "timestamp": kwargs.get("timestamp", time.time()),
            "selected_action": kwargs.get("selected_action"),
            "realized_outcome": kwargs.get("realized_outcome"),
            "validation_horizon": kwargs.get("validation_horizon"),
            "label": kwargs.get("label"),
            "avoided_loss": kwargs.get("avoided_loss"),
            "missed_opportunity": kwargs.get("missed_opportunity"),
            "confidence": kwargs.get("confidence"),
            "completeness": kwargs.get("completeness"),
        }

        # Validate
        missing = [f for f in _REQUIRED_FIELDS if record.get(f) is None]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

        if record["label"] not in _VALID_LABELS:
            raise ValueError(
                f"Invalid label '{record['label']}'. "
                f"Must be one of: {', '.join(sorted(_VALID_LABELS))}"
            )

        return record

    def validate_record(self, record: dict[str, Any]) -> bool:
        """Check whether *record* conforms to the outcome schema.

        Returns True if valid, False otherwise.
        """
        for field in _REQUIRED_FIELDS:
            if field not in record or record[field] is None:
                return False
        if record.get("label") not in _VALID_LABELS:
            return False
        return True


class OutcomeLinker:
    """Links decisions to their realised outcomes for traceability."""

    def __init__(self) -> None:
        # decision_id -> list of linked outcomes
        self._links: dict[str, list[dict[str, Any]]] = {}
        # subsystem -> list of decision_ids
        self._subsystem_index: dict[str, list[str]] = {}

    async def link_decision_to_outcome(
        self, decision_id: str, outcome: dict[str, Any]
    ) -> dict[str, Any]:
        """Link *decision_id* to a realised *outcome*.

        Returns the link record.
        """
        link = {
            "link_id": str(uuid.uuid4()),
            "decision_id": decision_id,
            "outcome": outcome,
            "linked_at": time.time(),
        }
        self._links.setdefault(decision_id, []).append(link)

        subsystem = outcome.get("subsystem", "unknown")
        self._subsystem_index.setdefault(subsystem, [])
        if decision_id not in self._subsystem_index[subsystem]:
            self._subsystem_index[subsystem].append(decision_id)

        logger.info("Linked decision '%s' to outcome (subsystem=%s)",
                     decision_id, subsystem)
        return link

    async def get_linked_outcomes(
        self, subsystem: str
    ) -> list[dict[str, Any]]:
        """Return all linked outcomes for *subsystem*."""
        decision_ids = self._subsystem_index.get(subsystem, [])
        results: list[dict[str, Any]] = []
        for did in decision_ids:
            for link in self._links.get(did, []):
                results.append(link)
        return results


class ReplayEngine:
    """Replays historical decisions with candidate parameters to
    validate whether proposed parameter changes improve outcomes."""

    def __init__(self) -> None:
        self._replay_cache: dict[str, dict[str, Any]] = {}

    async def replay_with_params(
        self, decisions: list[dict[str, Any]], candidate_params: dict[str, Any]
    ) -> dict[str, Any]:
        """Replay *decisions* using *candidate_params* and return
        simulated outcomes.

        Returns:
            replay_id, total_decisions, simulated_successes,
            simulated_failures, simulated_neutrals,
            success_rate, params_used
        """
        replay_id = str(uuid.uuid4())
        successes = 0
        failures = 0
        neutrals = 0

        for decision in decisions:
            simulated_label = self._simulate_decision(decision, candidate_params)
            if simulated_label == "success":
                successes += 1
            elif simulated_label == "failure":
                failures += 1
            else:
                neutrals += 1

        total = len(decisions)
        result = {
            "replay_id": replay_id,
            "total_decisions": total,
            "simulated_successes": successes,
            "simulated_failures": failures,
            "simulated_neutrals": neutrals,
            "success_rate": round(successes / total, 4) if total > 0 else 0.0,
            "params_used": candidate_params,
            "timestamp": time.time(),
        }
        self._replay_cache[replay_id] = result
        logger.info("Replay %s complete: %d decisions, %.2f%% success",
                     replay_id, total, result["success_rate"] * 100)
        return result

    async def compare_to_baseline(
        self, replay_results: dict[str, Any], baseline: dict[str, Any]
    ) -> dict[str, Any]:
        """Compare *replay_results* against *baseline* performance.

        Returns:
            improvement: float (positive = better)
            replay_success_rate: float
            baseline_success_rate: float
            is_superior: bool
        """
        replay_rate = replay_results.get("success_rate", 0.0)
        baseline_rate = baseline.get("success_rate", 0.0)
        improvement = replay_rate - baseline_rate

        return {
            "improvement": round(improvement, 4),
            "replay_success_rate": replay_rate,
            "baseline_success_rate": baseline_rate,
            "is_superior": improvement > 0,
        }

    async def validate_update(
        self, candidate: dict[str, Any]
    ) -> bool:
        """Check whether *candidate* param changes stay within the
        allowed per-cycle limit (<=10% change per parameter).

        Args:
            candidate: dict with 'baseline_params' and 'proposed_params'.

        Returns True if all changes are within limits.
        """
        baseline = candidate.get("baseline_params", {})
        proposed = candidate.get("proposed_params", {})

        for key, proposed_value in proposed.items():
            baseline_value = baseline.get(key)
            if baseline_value is None:
                continue  # new param, no constraint
            if isinstance(baseline_value, (int, float)) and baseline_value != 0:
                change_ratio = abs(proposed_value - baseline_value) / abs(baseline_value)
                if change_ratio > _MAX_PARAM_CHANGE_RATIO:
                    logger.warning(
                        "Param '%s' change %.2f%% exceeds limit %.2f%%",
                        key, change_ratio * 100, _MAX_PARAM_CHANGE_RATIO * 100,
                    )
                    return False
        return True

    # ── Private ───────────────────────────────────────────────────────

    @staticmethod
    def _simulate_decision(
        decision: dict[str, Any], params: dict[str, Any]
    ) -> str:
        """Simulate a single decision replay.

        In production this runs the decision through the actual model
        with *params*.  Here we use a deterministic heuristic: if the
        original label was 'failure' and the candidate params include a
        higher confidence threshold, we flip to 'neutral'; otherwise
        keep the original label.
        """
        original_label = decision.get("label", "neutral")

        # Simple heuristic: higher confidence threshold can rescue failures
        orig_threshold = decision.get("confidence", 0.5)
        candidate_threshold = params.get("confidence_threshold", orig_threshold)

        if original_label == "failure" and candidate_threshold > orig_threshold:
            return "neutral"
        return original_label


class LearningStore:
    """Manages baseline parameters, update proposals, acceptance,
    rejection, and rollback.  Feature-flagged (disabled by default)."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._enabled: bool = bool(self.config.get("enabled", False))

        # Current baseline params
        self._baseline_params: dict[str, Any] = dict(
            self.config.get("initial_params", {
                "confidence_threshold": 0.5,
                "risk_tolerance": 0.3,
                "learning_rate": 0.1,
                "min_sample_size": 10,
            })
        )
        # Params history for rollback (stack)
        self._params_history: list[dict[str, Any]] = [
            copy.deepcopy(self._baseline_params)
        ]
        # Pending and resolved proposals
        self._proposals: dict[str, dict[str, Any]] = {}

        logger.info("LearningStore initialised (enabled=%s)", self._enabled)

    async def get_baseline_params(self) -> dict[str, Any]:
        """Return the current baseline parameters."""
        return dict(self._baseline_params)

    async def propose_update(
        self, candidate: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a parameter update proposal.

        Args:
            candidate: dict with 'proposed_params' and optionally
                       'justification', 'replay_id'.

        Returns the proposal record.
        Raises RuntimeError if the store is disabled.
        """
        if not self._enabled:
            raise RuntimeError(
                "LearningStore is disabled. Enable via config "
                "'enabled: true' to propose parameter updates."
            )

        proposal_id = str(uuid.uuid4())
        proposal = {
            "proposal_id": proposal_id,
            "baseline_params": copy.deepcopy(self._baseline_params),
            "proposed_params": candidate.get("proposed_params", {}),
            "justification": candidate.get("justification", ""),
            "replay_id": candidate.get("replay_id"),
            "status": "pending",
            "created_at": time.time(),
            "resolved_at": None,
        }
        self._proposals[proposal_id] = proposal
        logger.info("Parameter update proposed: %s", proposal_id)
        return proposal

    async def accept_update(self, update_id: str) -> dict[str, Any]:
        """Accept a pending proposal and apply the parameter changes.

        Raises KeyError if the proposal doesn't exist.
        Raises ValueError if the proposal is not pending.
        """
        proposal = self._proposals.get(update_id)
        if proposal is None:
            raise KeyError(f"Proposal '{update_id}' not found")
        if proposal["status"] != "pending":
            raise ValueError(
                f"Proposal '{update_id}' is '{proposal['status']}', not pending"
            )

        # Save current baseline for rollback
        self._params_history.append(copy.deepcopy(self._baseline_params))

        # Apply
        self._baseline_params.update(proposal["proposed_params"])
        proposal["status"] = "accepted"
        proposal["resolved_at"] = time.time()

        logger.info("Proposal %s accepted — params updated", update_id)
        return proposal

    async def reject_update(
        self, update_id: str, reason: str
    ) -> dict[str, Any]:
        """Reject a pending proposal.

        Raises KeyError if the proposal doesn't exist.
        Raises ValueError if the proposal is not pending.
        """
        proposal = self._proposals.get(update_id)
        if proposal is None:
            raise KeyError(f"Proposal '{update_id}' not found")
        if proposal["status"] != "pending":
            raise ValueError(
                f"Proposal '{update_id}' is '{proposal['status']}', not pending"
            )

        proposal["status"] = "rejected"
        proposal["rejection_reason"] = reason
        proposal["resolved_at"] = time.time()

        logger.info("Proposal %s rejected: %s", update_id, reason)
        return proposal

    async def rollback(self) -> dict[str, Any]:
        """Roll back to the previous baseline parameters.

        Returns the restored params.
        Raises RuntimeError if there is no history to roll back to.
        """
        if len(self._params_history) < 2:
            raise RuntimeError("No previous parameter state to roll back to")

        # Pop current, restore previous
        self._params_history.pop()
        self._baseline_params = copy.deepcopy(self._params_history[-1])

        logger.info("Rolled back to previous parameter state")
        return dict(self._baseline_params)
