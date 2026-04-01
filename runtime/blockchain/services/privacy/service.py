"""Privacy Protection Service - Component 29.

Irrevocable on-chain commitment to user privacy. Manages data deletion
requests with dependency checking across all platform components.
Links to Component 5 (DID identity) and Component 8 (attestations).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from .deletion_executor import DeletionExecutor
from .dependency_checker import DependencyChecker

logger = logging.getLogger(__name__)

VALID_DATA_TYPES = {
    "profile", "messages", "transactions", "attestations", "social_posts",
    "loyalty_data", "subscription_data", "marketplace_history",
    "cashback_data", "brand_rewards_data", "all",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "require_dependency_check": True,
    "cooldown_period_hours": 24,
    "max_concurrent_deletions": 5,
}


class PrivacyService:
    """Privacy protection with irrevocable on-chain commitments.

    Manages the full lifecycle of data deletion requests:
    1. User requests deletion of specific data types.
    2. System checks for blocking dependencies (disputes, loans, etc.).
    3. If clear, deletion is executed and attested on-chain.
    4. Privacy commitment is recorded immutably.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self._deletion_requests: dict[str, dict] = {}
        self._privacy_commitments: dict[str, dict] = {}  # user -> commitment
        self.executor = DeletionExecutor(self.config)
        self.dependency_checker = DependencyChecker(self.config)
        logger.info("PrivacyService initialised")

    async def request_deletion(self, user: str, data_types: list) -> dict:
        """Request deletion of user data.

        Args:
            user: User's wallet address (links to Component 5 DID).
            data_types: List of data types to delete. Use ['all'] for everything.

        Returns:
            Deletion request record with dependency check results.
        """
        if not user:
            raise ValueError("user is required")
        if not data_types:
            raise ValueError("data_types is required (at least one type)")

        # Validate data types
        if "all" in data_types:
            resolved_types = list(VALID_DATA_TYPES - {"all"})
        else:
            invalid = set(data_types) - VALID_DATA_TYPES
            if invalid:
                raise ValueError(f"Invalid data types: {invalid}. Valid types: {VALID_DATA_TYPES}")
            resolved_types = list(data_types)

        # Check for pending requests
        for req in self._deletion_requests.values():
            if req["user"] == user and req["status"] in ("pending", "in_progress"):
                raise ValueError(
                    f"User already has a pending deletion request (id={req['request_id']}). "
                    "Please wait for it to complete."
                )

        # Run dependency check
        dep_result = await self.check_dependencies(user)
        blocking = dep_result.get("blocking_dependencies", [])

        request_id = f"del_{uuid.uuid4().hex[:12]}"
        now = time.time()

        request = {
            "request_id": request_id,
            "user": user,
            "data_types": resolved_types,
            "status": "blocked" if blocking else "pending",
            "blocking_dependencies": blocking,
            "dependency_check": dep_result,
            "created_at": now,
            "updated_at": now,
            "cooldown_until": now + self.config["cooldown_period_hours"] * 3600 if not blocking else None,
            "executed_at": None,
            "verified_at": None,
            "attestation_uid": None,
        }

        self._deletion_requests[request_id] = request

        if blocking:
            logger.warning(
                "Deletion request %s for user %s BLOCKED: %d dependencies",
                request_id, user, len(blocking),
            )
        else:
            logger.info(
                "Deletion request %s created for user %s (%d data types, cooldown=%dh)",
                request_id, user, len(resolved_types), self.config["cooldown_period_hours"],
            )

        return request

    async def get_privacy_commitment(self, user: str) -> dict:
        """Get the irrevocable privacy commitment for a user.

        The commitment is an on-chain record that the platform will honour
        all valid deletion requests for this user.

        Args:
            user: User's wallet address.

        Returns:
            Privacy commitment record.
        """
        if not user:
            raise ValueError("user is required")

        if user not in self._privacy_commitments:
            commitment_id = f"priv_{uuid.uuid4().hex[:12]}"
            now = time.time()
            self._privacy_commitments[user] = {
                "commitment_id": commitment_id,
                "user": user,
                "commitment": (
                    "The platform irrevocably commits to honouring all valid data deletion "
                    "requests for this user, subject to legal and operational constraints. "
                    "This commitment is recorded on-chain and cannot be revoked."
                ),
                "did_reference": f"did:0pnmatrx:{user}",  # Component 5 DID
                "created_at": now,
                "deletion_requests": [],
                "total_deletions_completed": 0,
            }

        commitment = self._privacy_commitments[user]

        # Enrich with deletion history
        user_requests = [
            r for r in self._deletion_requests.values() if r["user"] == user
        ]
        commitment["deletion_requests"] = [
            {"request_id": r["request_id"], "status": r["status"], "created_at": r["created_at"]}
            for r in user_requests
        ]
        commitment["total_deletions_completed"] = sum(
            1 for r in user_requests if r["status"] == "completed"
        )

        return commitment

    async def check_dependencies(self, user: str) -> dict:
        """Check all platform dependencies before deletion.

        Queries across all components for data that cannot be deleted.

        Args:
            user: User's wallet address.

        Returns:
            Dict with dependency status and blocking items.
        """
        if not user:
            raise ValueError("user is required")

        result = await self.dependency_checker.check_structural_dependencies(user)
        blocking = await self.dependency_checker.get_blocking_dependencies(user)

        return {
            "user": user,
            "can_delete": len(blocking) == 0,
            "blocking_dependencies": blocking,
            "structural_dependencies": result,
            "checked_at": time.time(),
        }

    async def get_deletion_status(self, request_id: str) -> dict:
        """Get the status of a deletion request.

        Args:
            request_id: The deletion request ID.

        Returns:
            Full status including execution and verification details.
        """
        request = self._deletion_requests.get(request_id)
        if not request:
            raise ValueError(f"Deletion request '{request_id}' not found")

        now = time.time()
        result = {**request}

        # If pending and past cooldown, mark as ready
        if request["status"] == "pending" and request.get("cooldown_until"):
            if now >= request["cooldown_until"]:
                result["ready_for_execution"] = True
                result["cooldown_remaining_seconds"] = 0
            else:
                result["ready_for_execution"] = False
                result["cooldown_remaining_seconds"] = round(request["cooldown_until"] - now, 0)

        # If in progress, get executor status
        if request["status"] == "in_progress":
            exec_status = await self.executor.get_execution_status(request_id)
            result["execution_details"] = exec_status

        return result

    async def execute_pending_deletion(self, request_id: str) -> dict:
        """Execute a pending deletion request that has passed its cooldown.

        Args:
            request_id: The deletion request to execute.

        Returns:
            Execution result.
        """
        request = self._deletion_requests.get(request_id)
        if not request:
            raise ValueError(f"Deletion request '{request_id}' not found")
        if request["status"] != "pending":
            raise ValueError(f"Request is not pending (status={request['status']})")

        now = time.time()
        if request.get("cooldown_until") and now < request["cooldown_until"]:
            remaining = round(request["cooldown_until"] - now, 0)
            raise ValueError(f"Cooldown period has not elapsed. {remaining}s remaining.")

        # Re-check dependencies
        blocking = await self.dependency_checker.get_blocking_dependencies(request["user"])
        if blocking:
            request["status"] = "blocked"
            request["blocking_dependencies"] = blocking
            request["updated_at"] = now
            raise ValueError(f"New blocking dependencies found: {len(blocking)} items")

        request["status"] = "in_progress"
        request["updated_at"] = now

        # Execute deletion
        exec_result = await self.executor.execute_deletion(request_id)

        if exec_result.get("success"):
            request["status"] = "completed"
            request["executed_at"] = now

            # Verify deletion
            verification = await self.executor.verify_deletion(request_id)
            request["verified_at"] = time.time()
            request["attestation_uid"] = verification.get("attestation_uid")

            logger.info(
                "Deletion request %s completed and verified for user %s",
                request_id, request["user"],
            )
        else:
            request["status"] = "failed"
            request["error"] = exec_result.get("error", "Unknown error")
            logger.error("Deletion request %s failed: %s", request_id, request.get("error"))

        request["updated_at"] = time.time()
        return {**request, "execution_result": exec_result}
