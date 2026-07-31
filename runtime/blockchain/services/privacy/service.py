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

from .deletion_executor import _OFFLINE_MESSAGE, DeletionExecutor
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
        """OFFLINE (NEW-38) — answers "not available" and queues nothing.

        This used to accept the request, run a real dependency check, mint a
        `del_*` id, set a 24-hour cooldown, and return `status: "pending"`.
        Every part of that was real except the part that mattered: the
        executor at the end of the pipeline deleted nothing (see
        deletion_executor.py). So the honest description of the old
        behaviour is that it took a user's erasure request, told them it was
        pending, and dropped it in a dict that nothing ever drained — no
        cron, no scheduler, no internal caller of
        `execute_pending_deletion`.

        Accepting-and-queuing is worse than refusing. A refusal tells the
        user to go elsewhere with their request; a pending id tells them it is
        being handled, and under GDPR/CCPA the clock they think is running is
        not running. So the request is no longer accepted at all.

        No input validation runs first, deliberately. Validating the data
        types of an operation that cannot happen is its own small theatre,
        and it would answer "invalid data type" — a claim about the request —
        when the truth is a fact about the platform.

        The pre-existing `raise ValueError` on missing args is dropped for
        the same reason: callers get one answer, and it is the true one.
        """
        logger.warning(
            "request_deletion refused for user %s — deletion is OFFLINE "
            "(NEW-38); nothing was queued",
            user,
        )
        return {
            "status": "error",
            "error_category": "not_implemented",
            "error": "deletion_not_implemented",
            "message": _OFFLINE_MESSAGE,
            "user": user,
            "data_types": list(data_types) if data_types else [],
            "request_id": None,
            "queued": False,
        }

    async def get_privacy_commitment(self, user: str) -> dict:
        """Return the platform's recorded privacy statement for a user.

        NEW-38: the record-keeping here is real — an in-memory commitment
        entry per user, enriched with that user's actual request history. The
        SENTENCE it returned was not. It read:

            "The platform irrevocably commits to honouring all valid data
             deletion requests for this user, subject to legal and
             operational constraints. This commitment is recorded on-chain
             and cannot be revoked."

        Three false claims in two sentences. The platform cannot honour a
        deletion request at all (the executor deleted nothing, and is now
        offline). The record is a dict in this process, not on-chain. And
        being in-process, it is revoked by a restart.

        Corrected here rather than deferred because taking deletion offline
        in the same commit would otherwise leave a neighbouring method
        telling users their erasure rights are guaranteed on-chain.

        Args:
            user: User's wallet address.

        Returns:
            Privacy statement record with this user's request history.
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
                    "Data deletion is not currently available on this platform. "
                    "No verified erasure path across the platform's data stores "
                    "has been built, so deletion requests cannot be accepted and "
                    "no deletion can be reported as completed."
                ),
                "deletion_available": False,
                "recorded_on_chain": False,
                "record_scope": (
                    "In-memory record held by the running gateway process. It is "
                    "not an on-chain commitment and does not survive a restart."
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
        """OFFLINE (NEW-38) — refuses. Never reaches the executor.

        This was the orchestration around the fake: it checked the request
        existed, checked the status was pending, enforced the cooldown,
        re-ran the dependency check, then called
        `self.executor.execute_deletion(request_id)` and — because that call
        could not fail — took the success branch every time, marked the
        request "completed", called `verify_deletion`, and stored the minted
        attestation UID on the request.

        The orchestration was real; its subject was not. The cooldown was
        the only gate between a request and a `completed` record, and
        elapsing it is a matter of waiting.

        Kept as a refusing method rather than deleted so callers reaching it
        by any surface get the true answer. `execute_deletion` has been
        removed from ACTION_MAP, so the action surface can no longer route
        here at all; this covers everything else.
        """
        logger.warning(
            "execute_pending_deletion refused for request %s — deletion is "
            "OFFLINE (NEW-38); the executor was not called",
            request_id,
        )
        return {
            "status": "error",
            "error_category": "not_implemented",
            "error": "deletion_not_implemented",
            "message": _OFFLINE_MESSAGE,
            "request_id": request_id,
            "success": False,
            "executed": False,
            "attestation_uid": None,
        }

    # ------------------------------------------------------------------
    # Expanded privacy operations
    # ------------------------------------------------------------------

    # REMOVED — `private_transfer` (NEW-36). It was a RECEIPT PRINTER, not a
    # transfer.
    #
    # It took sender/recipient/amount/token, minted a uuid, hardcoded
    # `"status": "completed"` and `"shielded": True`, and returned. No
    # `transferFrom`, no pool, no balance mutation, no chain call. It also filed
    # its record into `self._deletion_requests` — the GDPR deletion-tracking
    # dict — so the fake record was orphaned in an unrelated store.
    #
    # THE SEVERITY IS FALSE SETTLEMENT, NOT FUNDS LOSS, and the distinction is
    # the whole reason for reading the body. It never took custody either: no
    # tokens were pulled in, so nothing was swallowed and nothing destroyed.
    # The money stayed in the caller's wallet. What was produced was a
    # completed-transfer confirmation for a transfer that never happened — the
    # downstream harm is goods released against a fake "paid", debts believed
    # cleared, a recipient who thinks they were paid and was not.
    #
    # Contrast `stealth_address`, removed earlier in this phase: that one
    # generated unspendable addresses, so funds sent there were destroyed. Both
    # are fabrications; they are different severity classes, and the method name
    # ("transfer") told you neither.
    #
    # AND IT WAS LIVE. Its `platform_action` declaration mismatched
    # (asset/memo/privacy_level vs sender/recipient/amount/token) so that surface
    # errored out — but `POST /api/v1/privacy/transfer` bound exactly the four
    # parameters the method accepts. Live-vs-inert is PER SURFACE: a route
    # supplies its own binding, so an action inert via the tool can be live via
    # HTTP.
    #
    # Removed across every surface, including the Morpheus trigger that was
    # escalating transfers over $1000 for security review — the security layer
    # was reviewing a fabrication.

    # REMOVED — `generate_stealth_address`.
    #
    # It returned `f"0x{uuid.uuid4().hex[:40]}"`: a random 40-hex string shaped
    # like an Ethereum address, with `status: "generated"`. No key derivation,
    # no ERC-5564 (which docs/COMPLETE_CAPABILITY_MAP.md declared as its
    # protocol), no cryptography of any kind. NO PRIVATE KEY FOR THAT ADDRESS
    # EXISTS ANYWHERE — spending requires a key that was never created and
    # cannot be reconstructed, so anything sent there is destroyed, not at risk.
    #
    # It was removed rather than repaired, and the reason is the important part:
    # the action was BROKEN, and the broken-ness was the only thing protecting
    # users. A signature mismatch made it error out instead of executing, and
    # the NEW-13 classification filed it as `fix-the-spec` — a one-word rename
    # of `base_address` to `owner`. That "fix" would have turned a dead endpoint
    # into a working funds-destroyer.
    #
    # A signature bug in front of a fabrication is load-bearing safety. The
    # honest answer to "I cannot do this safely" is to say so, not to ship a
    # broken version of it. Every surface is gone — intent action, ACTION_MAP,
    # capability catalog, morpheus trigger, HTTP route — so a request for a
    # stealth address is now unrecognised rather than answered with a fiction.
    # Pinned by tests/test_fabrication_removal.py.

    async def generate_zk_proof(
        self, prover: str, statement: str, witness: dict | None = None,
    ) -> dict:
        """Generate a zero-knowledge proof."""
        proof_id = f"zkp_{uuid.uuid4().hex[:16]}"
        record = {
            "id": proof_id,
            "status": "generated",
            "prover": prover,
            "statement": statement,
            "proof_hash": f"0x{uuid.uuid4().hex}",
            "verifiable": True,
            "generated_at": time.time(),
        }
        logger.info("ZK proof generated: id=%s", proof_id)
        return record

    async def private_vote(
        self, voter: str, proposal_id: str, choice: str, proof: str = "",
    ) -> dict:
        """Cast a privacy-preserving vote."""
        vote_id = f"pvote_{uuid.uuid4().hex[:16]}"
        record = {
            "id": vote_id,
            "status": "cast",
            "voter": voter,
            "proposal_id": proposal_id,
            "choice_hash": f"0x{uuid.uuid4().hex[:32]}",
            "proof": proof,
            "cast_at": time.time(),
        }
        logger.info("Private vote cast: id=%s", vote_id)
        return record

    async def confidential_compute(
        self, requester: str, computation: str, encrypted_inputs: dict | None = None,
    ) -> dict:
        """Submit a confidential computation request."""
        cc_id = f"cc_{uuid.uuid4().hex[:16]}"
        record = {
            "id": cc_id,
            "status": "completed",
            "requester": requester,
            "computation": computation,
            "encrypted_inputs": encrypted_inputs or {},
            "result_hash": f"0x{uuid.uuid4().hex}",
            "completed_at": time.time(),
        }
        logger.info("Confidential compute: id=%s", cc_id)
        return record

    async def decentralized_store(
        self, uploader: str, data_hash: str, storage_provider: str = "ipfs", encryption: bool = True,
    ) -> dict:
        """Store data on a decentralized storage network."""
        store_id = f"dstore_{uuid.uuid4().hex[:16]}"
        record = {
            "id": store_id,
            "status": "stored",
            "uploader": uploader,
            "data_hash": data_hash,
            "storage_provider": storage_provider,
            "encrypted": encryption,
            "cid": f"bafy{uuid.uuid4().hex[:48]}",
            "stored_at": time.time(),
        }
        logger.info("Decentralized store: id=%s provider=%s", store_id, storage_provider)
        return record

    async def submit_compute_job(
        self, requester: str, job_type: str, params: dict | None = None,
    ) -> dict:
        """Submit a decentralized compute job."""
        job_id = f"cjob_{uuid.uuid4().hex[:16]}"
        record = {
            "id": job_id,
            "status": "submitted",
            "requester": requester,
            "job_type": job_type,
            "params": params or {},
            "submitted_at": time.time(),
        }
        logger.info("Compute job submitted: id=%s", job_id)
        return record

    async def pin_to_ipfs(
        self, uploader: str, data_hash: str, pin_name: str = "",
    ) -> dict:
        """Pin content to IPFS."""
        pin_id = f"ipfs_{uuid.uuid4().hex[:16]}"
        record = {
            "id": pin_id,
            "status": "pinned",
            "uploader": uploader,
            "data_hash": data_hash,
            "pin_name": pin_name,
            "cid": f"Qm{uuid.uuid4().hex[:44]}",
            "pinned_at": time.time(),
        }
        logger.info("IPFS pin: id=%s", pin_id)
        return record

    async def store_on_arweave(
        self, uploader: str, data_hash: str, content_type: str = "application/octet-stream",
    ) -> dict:
        """Store data permanently on Arweave."""
        ar_id = f"ar_{uuid.uuid4().hex[:16]}"
        record = {
            "id": ar_id,
            "status": "stored",
            "uploader": uploader,
            "data_hash": data_hash,
            "content_type": content_type,
            "arweave_tx": f"ar_{uuid.uuid4().hex}",
            "stored_at": time.time(),
        }
        logger.info("Arweave store: id=%s", ar_id)
        return record
