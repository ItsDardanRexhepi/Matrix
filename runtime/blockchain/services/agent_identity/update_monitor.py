"""
UpdateMonitor -- monitors and validates agent identity updates.

Includes a SafetyValidator that ensures updates do not expand agent
permissions beyond their authorised scope. Supports rollback capability.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Maximum allowed capability expansion per update (percentage of current)
MAX_CAPABILITY_EXPANSION_PCT = 0.50  # 50%

# Restricted capabilities that require explicit authorisation
RESTRICTED_CAPABILITIES: set[str] = {
    "financial_transfer",
    "contract_deployment",
    "governance_vote",
    "identity_management",
    "admin_override",
    "cross_chain_bridge",
    "key_management",
}

# Valid proposal statuses
PROPOSAL_STATUSES = {"pending", "validated", "rejected", "applied", "rolled_back"}


class SafetyValidator:
    """
    Validates agent updates for safety before they are applied.

    Checks:
    - Capability scope validation (no unauthorised escalation)
    - Behavior change limits (bounded deviation from current config)
    - Rollback capability verification
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        ai = config.get("agent_identity", {})
        self.max_expansion_pct: float = ai.get(
            "max_capability_expansion_pct", MAX_CAPABILITY_EXPANSION_PCT
        )
        self.restricted_capabilities: set[str] = set(
            ai.get("restricted_capabilities", RESTRICTED_CAPABILITIES)
        )

    def validate_capability_scope(
        self,
        old_capabilities: list[str],
        new_capabilities: list[str],
    ) -> dict[str, Any]:
        """
        Check that new capabilities do not exceed authorised scope.

        Returns a validation result with pass/fail and details.
        """
        old_set = set(old_capabilities)
        new_set = set(new_capabilities)

        added = new_set - old_set
        removed = old_set - new_set

        issues: list[str] = []

        # Check for restricted capability additions
        restricted_added = added & self.restricted_capabilities
        if restricted_added:
            issues.append(
                f"Adding restricted capabilities requires explicit authorisation: "
                f"{sorted(restricted_added)}"
            )

        # Check expansion rate
        if old_set and added:
            expansion_rate = len(added) / len(old_set)
            if expansion_rate > self.max_expansion_pct:
                issues.append(
                    f"Capability expansion rate {expansion_rate:.0%} exceeds "
                    f"maximum allowed {self.max_expansion_pct:.0%}"
                )

        return {
            "safe": len(issues) == 0,
            "added": sorted(added),
            "removed": sorted(removed),
            "unchanged": sorted(old_set & new_set),
            "restricted_additions": sorted(restricted_added) if restricted_added else [],
            "issues": issues,
        }

    def validate_behavior_change(
        self, update: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Validate that behavioral changes are within acceptable bounds.

        Checks metadata changes for configuration drift.
        """
        issues: list[str] = []

        # Check for model changes (if metadata includes model info)
        if "model" in update and "old_model" in update:
            if update["model"] != update.get("old_model"):
                # Model change is significant but allowed with warning
                issues.append(
                    f"Model change detected: {update.get('old_model')} -> {update['model']}"
                )

        # Check for temperature/parameter changes
        if "parameters" in update:
            params = update["parameters"]
            if "temperature" in params and params["temperature"] > 1.5:
                issues.append(
                    f"Temperature {params['temperature']} exceeds safe threshold (1.5)"
                )
            if "max_tokens" in params and params["max_tokens"] > 100_000:
                issues.append(
                    f"Max tokens {params['max_tokens']} exceeds safe threshold (100,000)"
                )

        return {
            "safe": len(issues) == 0,
            "issues": issues,
            "warnings": [i for i in issues if "detected" in i.lower()],
        }

    def verify_rollback_capability(
        self, proposal: dict[str, Any]
    ) -> dict[str, Any]:
        """Verify that a rollback is possible for the proposed update."""
        has_snapshot = "snapshot" in proposal and proposal["snapshot"] is not None
        has_previous = "previous_state" in proposal and proposal["previous_state"] is not None

        rollback_possible = has_snapshot or has_previous

        return {
            "rollback_possible": rollback_possible,
            "has_snapshot": has_snapshot,
            "has_previous_state": has_previous,
            "reason": "Rollback data available" if rollback_possible else "No rollback data stored",
        }


class UpdateMonitor:
    """
    Monitors and manages agent identity update proposals.

    Each update goes through a propose -> validate -> apply pipeline
    with full safety checks and rollback support.

    Config keys (under config["agent_identity"]):
        require_validation  -- whether validation is mandatory (default True)
        auto_apply          -- auto-apply safe updates (default False)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        ai = config.get("agent_identity", {})

        self.require_validation: bool = ai.get("require_validation", True)
        self.auto_apply: bool = ai.get("auto_apply", False)

        self._validator = SafetyValidator(config)

        # proposal_id -> proposal record
        self._proposals: dict[str, dict[str, Any]] = {}
        # agent_id -> list of proposal_ids
        self._agent_proposals: dict[str, list[str]] = {}

        logger.info(
            "UpdateMonitor initialised: require_validation=%s auto_apply=%s",
            self.require_validation, self.auto_apply,
        )

    async def propose_update(
        self, agent_id: str, update: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Create an update proposal for an agent.

        The proposal captures the intended changes and a snapshot
        of the current state for rollback purposes.

        Args:
            agent_id: The agent to update.
            update: Dict describing the proposed changes.

        Returns:
            Dict with proposal_id and proposal details.
        """
        proposal_id = self._generate_proposal_id(agent_id)
        timestamp = int(time.time())

        # Build snapshot for rollback
        snapshot: dict[str, Any] | None = None
        if update.get("type") == "capability_change":
            snapshot = {
                "capabilities": update.get("old_capabilities", []),
                "timestamp": timestamp,
            }

        proposal: dict[str, Any] = {
            "proposal_id": proposal_id,
            "agent_id": agent_id,
            "update": update,
            "status": "pending",
            "snapshot": snapshot,
            "previous_state": update.get("old_capabilities") or update.get("previous"),
            "created_at": timestamp,
            "validated_at": None,
            "applied_at": None,
            "validation_result": None,
        }

        self._proposals[proposal_id] = proposal
        self._agent_proposals.setdefault(agent_id, []).append(proposal_id)

        logger.info(
            "Update proposal created: proposal=%s agent=%s type=%s",
            proposal_id, agent_id, update.get("type", "unknown"),
        )

        return {
            "status": "proposed",
            "proposal_id": proposal_id,
            "agent_id": agent_id,
            "update_type": update.get("type", "unknown"),
            "created_at": timestamp,
        }

    async def validate_update(self, proposal_id: str) -> dict[str, Any]:
        """
        Validate a proposed update through safety checks.

        Runs capability scope, behavior change, and rollback validations.

        Args:
            proposal_id: The proposal to validate.

        Returns:
            Dict with validation result (safe/unsafe) and details.
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return {"status": "error", "error": f"Proposal not found: {proposal_id}"}

        if proposal["status"] not in ("pending",):
            return {
                "status": "error",
                "error": f"Proposal cannot be validated in status: {proposal['status']}",
            }

        update = proposal["update"]
        results: dict[str, Any] = {}
        all_safe = True

        # 1. Capability scope validation
        if update.get("type") == "capability_change":
            scope_result = self._validator.validate_capability_scope(
                update.get("old_capabilities", []),
                update.get("new_capabilities", []),
            )
            results["capability_scope"] = scope_result
            if not scope_result["safe"]:
                all_safe = False

        # 2. Behavior change validation
        behavior_result = self._validator.validate_behavior_change(update)
        results["behavior_change"] = behavior_result
        if not behavior_result["safe"]:
            all_safe = False

        # 3. Rollback capability
        rollback_result = self._validator.verify_rollback_capability(proposal)
        results["rollback"] = rollback_result

        # Update proposal status
        timestamp = int(time.time())
        proposal["status"] = "validated" if all_safe else "rejected"
        proposal["validated_at"] = timestamp
        proposal["validation_result"] = results

        logger.info(
            "Proposal validated: proposal=%s safe=%s",
            proposal_id, all_safe,
        )

        return {
            "proposal_id": proposal_id,
            "safe": all_safe,
            "status": proposal["status"],
            "results": results,
            "validated_at": timestamp,
        }

    async def apply_update(self, proposal_id: str) -> dict[str, Any]:
        """
        Apply a validated update proposal.

        Only proposals in "validated" status can be applied.

        Args:
            proposal_id: The proposal to apply.

        Returns:
            Dict with application result.
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return {"status": "error", "error": f"Proposal not found: {proposal_id}"}

        if proposal["status"] != "validated":
            return {
                "status": "error",
                "error": (
                    f"Proposal must be validated before applying. "
                    f"Current status: {proposal['status']}"
                ),
            }

        timestamp = int(time.time())
        proposal["status"] = "applied"
        proposal["applied_at"] = timestamp

        logger.info(
            "Proposal applied: proposal=%s agent=%s",
            proposal_id, proposal["agent_id"],
        )

        return {
            "status": "applied",
            "proposal_id": proposal_id,
            "agent_id": proposal["agent_id"],
            "applied_at": timestamp,
            "rollback_available": proposal.get("snapshot") is not None,
        }

    async def rollback_update(self, proposal_id: str) -> dict[str, Any]:
        """
        Rollback a previously applied update.

        Args:
            proposal_id: The applied proposal to roll back.

        Returns:
            Dict with rollback result including restored state.
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return {"status": "error", "error": f"Proposal not found: {proposal_id}"}

        if proposal["status"] != "applied":
            return {
                "status": "error",
                "error": f"Can only rollback applied proposals. Current status: {proposal['status']}",
            }

        snapshot = proposal.get("snapshot")
        previous_state = proposal.get("previous_state")

        if snapshot is None and previous_state is None:
            return {
                "status": "error",
                "error": "No rollback data available for this proposal",
            }

        proposal["status"] = "rolled_back"
        proposal["rolled_back_at"] = int(time.time())

        restored = snapshot if snapshot else {"state": previous_state}

        logger.info("Proposal rolled back: proposal=%s", proposal_id)

        return {
            "status": "rolled_back",
            "proposal_id": proposal_id,
            "agent_id": proposal["agent_id"],
            "restored_state": restored,
            "rolled_back_at": proposal["rolled_back_at"],
        }

    async def get_proposals(
        self, agent_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all proposals for an agent, optionally filtered by status."""
        ids = self._agent_proposals.get(agent_id, [])
        proposals = [self._proposals[pid] for pid in ids if pid in self._proposals]

        if status is not None:
            proposals = [p for p in proposals if p["status"] == status]

        return proposals

    @staticmethod
    def _generate_proposal_id(agent_id: str) -> str:
        raw = f"{agent_id}:{uuid.uuid4().hex}:{time.time()}"
        return "prop_" + hashlib.sha256(raw.encode()).hexdigest()[:20]
