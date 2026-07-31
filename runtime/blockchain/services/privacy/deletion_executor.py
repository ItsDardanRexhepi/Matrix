"""Deletion Executor - Component 29 — OFFLINE (NEW-38).

This module used to claim it "executes data deletion requests by removing
off-chain data and marking on-chain records as deleted", and to attest that
completion via Component 8. It did neither. It is now offline: every entry
point refuses, and no entry point can report success.

WHAT IT ACTUALLY DID
--------------------
`execute_deletion` walked a hardcoded nine-item list of category NAMES
("profile_data", "message_history", ...), and for each one computed
`sha256(f"{request_id}:{category}:{now}")` and appended
`{"category": ..., "status": "deleted", "deletion_hash": ...}`. No database,
no object store, no cache, no chain. Its own comments said so:
"Simulate deletion of each data type", "In production, this would iterate
over actual data stores".

The `try` block contained only a hash computation, so `failed_items` could
never populate, so `success = len(failed_items) == 0` was unconditionally
True. It reported `"total_deleted": 9` and `"on_chain_status":
"marked_deleted"` for a user whose data it had never looked for. Reproduced
end-to-end against an address that has no data anywhere on the platform:

    request_deletion -> request_id=del_947a4c5d0f05, status=pending
    (elapse cooldown — the only gate)
    execute_deletion  -> success=True, total_deleted=9, total_failed=0,
                         on_chain_status='marked_deleted',
                         request status -> 'completed'

`verify_deletion` then read the same in-memory dict the fake write had just
populated, concluded `all_verified=True` because each item said "deleted",
and minted `attestation_uid = f"attest_{uuid4().hex[:16]}"` labelled
"Component 8 (EAS Attestation)". It was not an attestation; it was a random
hex string. The pair is the pattern: **a fabricated operation plus a
fabricated attestation certifying it.** Each one is the other's evidence, so
neither looks like a stub from the inside.

WHY OFFLINE RATHER THAN FIXED
-----------------------------
Real erasure is not a code gap — it is an inventory of every store that
holds user data, a per-store delete path, and a legal review of what may be
erased versus what must be retained. That is a project, not a patch, and it
is the owner's call to schedule. Until then the honest answer to "delete my
data" is that the platform cannot do it yet, which is a defensible position;
telling a user their data is gone when it is not is not.

Nothing was drained from the queue in the meantime: `execute_pending_deletion`
had no internal callers, no cron, and no scheduler, so requests sat in
`_deletion_requests` until the process died.

CONSTRAINT ON ANY REVIVAL
-------------------------
`tests/test_deletion_executor_offline.py` asserts that no path obtains
`success: true` from this class. Restoring a success-shaped return requires
that test to be rewritten against a real deletion, with a store that can be
checked for absence afterwards. Do not re-enable this by deleting the test.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# NEW-38: the single refusal reason, shared by every entry point so no
# surface can drift into a softer story than the others.
_OFFLINE_MESSAGE = (
    "Data deletion is not available. The platform does not currently have a "
    "verified erasure path across its data stores, and it will not report a "
    "deletion it did not perform. No data has been deleted by this call."
)


def _offline(entry_point: str, request_id: str | None = None) -> dict:
    """The refusal. Never success-shaped, on any surface.

    `status: "error"` + `error_category: "not_implemented"` is the shape the
    gateway already maps to HTTP 501 (`_ERROR_CATEGORY_HTTP` in
    gateway/service_routes.py), matching /api/v1/contracts/deploy. Both
    "error" and "unavailable" are in `_FAILURE_STATUSES`, so the RUN-4
    envelope refuses to dress this as a 200; 501 is preferred over 503
    because 503 implies "retry later" and there is nothing to retry.

    `success: False` is explicit rather than merely absent: the previous
    caller branched on `exec_result.get("success")`, and a missing key
    happening to be falsy is a coincidence, not a guarantee.
    """
    response: dict[str, Any] = {
        "status": "error",
        "error_category": "not_implemented",
        "success": False,
        "error": "deletion_not_implemented",
        "message": _OFFLINE_MESSAGE,
        "entry_point": entry_point,
        "deleted_items": [],
        "failed_items": [],
        "total_deleted": 0,
        "total_failed": 0,
        "on_chain_status": "none",
        "attestation_uid": None,
    }
    if request_id is not None:
        response["request_id"] = request_id
    return response

# Data types that cannot be deleted under certain conditions
UNDELETABLE_CONDITIONS = {
    "active_dispute_evidence": "Evidence in active disputes cannot be deleted until resolution",
    "legal_hold": "Data under legal hold cannot be deleted",
    "active_financial_positions": "Active financial positions (loans, escrow) must be settled first",
}


class DeletionExecutor:
    """Executes data deletion and verifies completion.

    Handles the actual removal of off-chain data and marking of on-chain
    records. Cannot delete active dispute evidence, legal hold data,
    or active financial positions.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._executions: dict[str, dict] = {}
        self._verifications: dict[str, dict] = {}
        logger.info("DeletionExecutor initialised")

    async def execute_deletion(self, request_id: str) -> dict:
        """OFFLINE (NEW-38) — refuses. Deletes nothing and says so.

        The refusal lives HERE, in the executor, rather than only in the
        callers. Two of the six frames this engagement has already broken
        were caller-enumeration frames: a route can exist that no one
        registered, and an action can be reachable through a tool surface
        nobody thought to check. Disabling the callers I could find would
        leave the guarantee resting on my enumeration being complete. A
        refusal at the leaf holds for callers that do not exist yet.

        Nothing is recorded in `self._executions`, so `verify_deletion` and
        `get_execution_status` have nothing to build a story on top of.
        """
        if not request_id:
            raise ValueError("request_id is required")

        logger.warning(
            "execute_deletion refused for request %s — deletion is OFFLINE "
            "(NEW-38); no data store was touched",
            request_id,
        )
        return _offline("execute_deletion", request_id)

    async def verify_deletion(self, request_id: str) -> dict:
        """OFFLINE (NEW-38) — refuses. Mints no attestation.

        This was the second half of the pair: it read back the dict the fake
        write had just populated, found every item marked "deleted", and
        issued a random hex string as an EAS attestation UID. There is
        nothing to verify and no attestation to make.

        It refuses unconditionally rather than relying on `_executions` being
        empty. An empty dict is a consequence of the executor above; if a
        future caller populates `_executions` directly, an
        absence-based refusal would quietly start attesting again.
        """
        logger.warning(
            "verify_deletion refused for request %s — deletion is OFFLINE "
            "(NEW-38); no attestation was created",
            request_id,
        )
        return _offline("verify_deletion", request_id)

    async def get_execution_status(self, request_id: str) -> dict:
        """Report that no execution exists — which is now always the truth.

        The first version of this kept the old relay branch, reasoning that
        "`_executions` can no longer be populated by this class, so
        'not_started' is accurate for every request_id."

        That is absence-based reasoning — the exact argument this module
        rejects two methods above for `verify_deletion`, applied here without
        noticing. An adversarial pass demonstrated the cost: give
        `execute_deletion` a body that returns the honest refusal but ALSO
        writes `{"success": True, "total_deleted": 2}` into `self._executions`,
        and this method relays `{"status": "executed", "execution": {"success":
        True, ...}}` to any caller — a fabricated deletion, served by the
        module that refuses to fabricate deletions, with the pin test still
        green.

        So it no longer relays. A stored record is reported as PRESENT without
        reproducing its claims, and flagged, because under NEW-38 nothing
        legitimate writes that dict: anything in there is a bug or a
        resurrection attempt, and the honest response is to say so rather than
        to pass its contents along as status.
        """
        execution = self._executions.get(request_id)
        if not execution:
            return {
                "request_id": request_id,
                "status": "not_started",
                "deletion_available": False,
                "message": _OFFLINE_MESSAGE,
            }

        logger.error(
            "get_execution_status found a stored execution record for %s while "
            "deletion is OFFLINE (NEW-38). Nothing should populate _executions; "
            "its contents are NOT being reported as a deletion.",
            request_id,
        )
        return {
            "request_id": request_id,
            "status": "error",
            "error_category": "not_implemented",
            "success": False,
            "deletion_available": False,
            "unexpected_execution_record": True,
            "message": (
                "An execution record exists for this request, but data deletion "
                "is not available and no deletion was performed. The record is "
                "not evidence of a deletion. " + _OFFLINE_MESSAGE
            ),
        }
