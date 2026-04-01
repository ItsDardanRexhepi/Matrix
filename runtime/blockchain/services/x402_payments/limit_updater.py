"""
LimitUpdater -- manages spend limit changes for x402 agents.

Ensures only authorised owners can update limits. All limit changes
are attested via the attestation service (Component 8) for on-chain
audit trail.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

VALID_LIMIT_KEYS = {"per_transaction", "daily", "weekly", "monthly"}


class LimitUpdater:
    """
    Manages spend limit updates for agents in the x402 payment system.

    Only the agent's owner can update its spend limits. Each change
    is recorded with an attestation for on-chain audit.

    Config keys (under config["x402"]):
        require_attestation -- whether to attest limit changes (default True)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        x402 = config.get("x402", {})

        self.require_attestation: bool = x402.get("require_attestation", True)

        # agent_id -> owner address
        self._agent_owners: dict[str, str] = {}
        # agent_id -> current limits
        self._agent_limits: dict[str, dict[str, float]] = {}
        # agent_id -> list of change records
        self._limit_history: dict[str, list[dict[str, Any]]] = {}

        # Reference to spend enforcer (set externally after init)
        self._spend_enforcer: Any = None

        logger.info(
            "LimitUpdater initialised: require_attestation=%s",
            self.require_attestation,
        )

    def set_spend_enforcer(self, enforcer: Any) -> None:
        """Link the spend enforcer so limit updates propagate."""
        self._spend_enforcer = enforcer

    def register_agent_owner(self, agent_id: str, owner: str) -> None:
        """Register the owner for an agent (for authorisation checks)."""
        self._agent_owners[agent_id] = owner
        logger.debug("Agent owner registered: agent=%s owner=%s", agent_id, owner)

    async def update_limits(
        self,
        agent_id: str,
        new_limits: dict[str, float],
        authorized_by: str,
    ) -> dict[str, Any]:
        """
        Update spend limits for an agent.

        Only the registered owner can update limits. Changes are
        attested via Component 8 for audit trail.

        Args:
            agent_id: The agent whose limits to update.
            new_limits: Dict with limit keys (per_transaction, daily, weekly, monthly).
            authorized_by: Address of the person authorising the change.

        Returns:
            Dict with update result and attestation info.
        """
        # Authorisation check
        registered_owner = self._agent_owners.get(agent_id)
        if registered_owner is None:
            return {
                "status": "error",
                "error": f"No owner registered for agent: {agent_id}. "
                         f"Register the agent owner first.",
            }

        if authorized_by != registered_owner:
            logger.warning(
                "Unauthorised limit update attempt: agent=%s by=%s (owner=%s)",
                agent_id, authorized_by, registered_owner,
            )
            return {
                "status": "error",
                "error": "Only the agent owner can update spend limits",
                "authorized_by": authorized_by,
                "owner": registered_owner,
            }

        # Validate limit keys
        invalid_keys = set(new_limits.keys()) - VALID_LIMIT_KEYS
        if invalid_keys:
            return {
                "status": "error",
                "error": f"Invalid limit keys: {sorted(invalid_keys)}. "
                         f"Valid keys: {sorted(VALID_LIMIT_KEYS)}",
            }

        # Validate limit values
        for key, value in new_limits.items():
            if not isinstance(value, (int, float)) or value < 0:
                return {
                    "status": "error",
                    "error": f"Limit '{key}' must be a non-negative number, got: {value}",
                }

        # Capture previous limits
        previous_limits = self._agent_limits.get(agent_id, {}).copy()

        # Merge new limits with existing
        current = self._agent_limits.get(agent_id, {}).copy()
        current.update(new_limits)
        self._agent_limits[agent_id] = current

        # Propagate to spend enforcer
        if self._spend_enforcer is not None:
            self._spend_enforcer.set_limits(agent_id, current)

        timestamp = int(time.time())

        # Create change record
        change_record: dict[str, Any] = {
            "agent_id": agent_id,
            "previous_limits": previous_limits,
            "new_limits": current.copy(),
            "changed_fields": {k: {"old": previous_limits.get(k), "new": v} for k, v in new_limits.items()},
            "authorized_by": authorized_by,
            "timestamp": timestamp,
            "change_hash": self._compute_change_hash(agent_id, new_limits, timestamp),
        }

        self._limit_history.setdefault(agent_id, []).append(change_record)

        # Attest the change via Component 8
        attestation_result: dict[str, Any] | None = None
        if self.require_attestation:
            attestation_result = await self._attest_limit_change(
                agent_id, change_record
            )

        logger.info(
            "Limits updated: agent=%s by=%s changes=%s",
            agent_id, authorized_by, new_limits,
        )

        return {
            "status": "updated",
            "agent_id": agent_id,
            "limits": current,
            "previous_limits": previous_limits,
            "authorized_by": authorized_by,
            "timestamp": timestamp,
            "attestation": attestation_result,
        }

    async def get_limits(self, agent_id: str) -> dict[str, Any]:
        """
        Get the current spend limits for an agent.

        Args:
            agent_id: The agent identifier.

        Returns:
            Dict with current limits, owner, and source.
        """
        limits = self._agent_limits.get(agent_id)
        owner = self._agent_owners.get(agent_id)

        if limits is None:
            return {
                "agent_id": agent_id,
                "limits": None,
                "source": "none",
                "owner": owner,
                "note": "No custom limits set. Using system defaults.",
            }

        return {
            "agent_id": agent_id,
            "limits": limits,
            "owner": owner,
            "source": "custom",
        }

    async def get_limit_history(self, agent_id: str) -> list[dict[str, Any]]:
        """
        Get the history of limit changes for an agent.

        Args:
            agent_id: The agent identifier.

        Returns:
            List of change records, newest first.
        """
        history = self._limit_history.get(agent_id, [])
        return list(reversed(history))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _attest_limit_change(
        self, agent_id: str, change_record: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Attest a limit change via Component 8 (AttestationService).

        If the attestation service is not available, logs a warning
        and returns a placeholder.
        """
        try:
            from runtime.blockchain.services.attestation.service import AttestationService

            attestation_svc = AttestationService(self.config)
            result = await attestation_svc.attest(
                schema_uid="payments",
                data={
                    "action": "limit_update",
                    "agent_id": agent_id,
                    "changes": change_record["changed_fields"],
                    "authorized_by": change_record["authorized_by"],
                    "change_hash": change_record["change_hash"],
                },
                recipient=change_record["authorized_by"],
            )
            return result

        except ImportError:
            logger.warning(
                "AttestationService not available for limit change attestation. "
                "Change recorded locally only."
            )
            return {
                "status": "skipped",
                "reason": "AttestationService not available",
                "change_hash": change_record["change_hash"],
            }
        except Exception as exc:
            logger.error("Failed to attest limit change: %s", exc)
            return {
                "status": "failed",
                "error": str(exc),
                "change_hash": change_record["change_hash"],
            }

    @staticmethod
    def _compute_change_hash(
        agent_id: str, limits: dict[str, float], timestamp: int
    ) -> str:
        payload = f"{agent_id}|{sorted(limits.items())}|{timestamp}"
        return "0x" + hashlib.sha256(payload.encode()).hexdigest()
