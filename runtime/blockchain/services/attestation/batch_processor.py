"""
Batch Processor for EAS attestations in The Matrix.

Collects non-time-critical attestations and submits them in batches to
reduce gas costs. The batch is flushed when either the batch size limit
is reached or the flush interval elapses — whichever comes first.

A FLUSH IS JUDGED PER ATTESTATION, BY WHAT THE CLIENT RETURNED.
`EASClient.attest` reports failure by RETURNING a structure — `{"status":
"skipped", "reason": "blockchain not configured"}` when the chain is not
configured, `{"status": "failed", "error": ...}` when the transaction reverts —
and it raises almost never. `flush()` took the queue, CLEARED it, submitted, and
then logged "submitted successfully" on the strength of nothing having been
raised; the only re-queue sat under an `except` that a returned refusal cannot
reach. So an unconfigured deployment lost every attestation it ever queued, and
said it had written them.

Each result is now read with `report_of`, the same predicate outcome learning
uses, so a refusal is a refusal here whatever idiom the client reports it in.
Anything that did not land goes back on the queue rather than being reported
as submitted — except an attestation that was sent and that no receipt has
confirmed, which is logged under its hash and not sent a second time; `_MAX_ATTEMPTS` bounds that so a permanently unconfigured
deployment cannot grow the queue without limit — and when it gives up it says
which ids it abandoned, by id, at ERROR. A record that stops is not the same as
a record that never existed.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from runtime.protocols.outcome_truth import SUCCESS, report_of

logger = logging.getLogger(__name__)

#: How many flushes an attestation may fail to land in before the processor
#: stops re-queueing it. It is then reported abandoned, by id, at ERROR — the
#: queue is bounded and the loss is stated rather than silent.
_MAX_ATTEMPTS = 5


def _eas_client_for(config: dict[str, Any]):
    """The EAS client this processor submits through.

    A named seam rather than an inline import: the submission path is the one
    thing in this module that has to be substitutable to be testable at all, and
    an inline `from ... import EASClient` inside a `try: ... except ImportError`
    is not.
    """
    from runtime.blockchain.eas_client import EASClient

    return EASClient(config)


class BatchProcessor:
    """
    Collects attestations and submits them in batches for gas efficiency.

    Attestations are queued via `add()` and submitted either when the batch
    reaches `batch_size` or when `flush_interval_seconds` elapses. A
    background task handles auto-flushing.
    """

    def __init__(
        self,
        config: dict,
        batch_size: int = 50,
        flush_interval_seconds: float = 60.0,
    ):
        self.config = config
        self.batch_size: int = batch_size
        self.flush_interval: float = flush_interval_seconds

        bc = config.get("blockchain", {})
        self.rpc_url: str = bc.get("rpc_url", "")
        self.eas_contract: str = bc.get("eas_contract", "")
        self.paymaster_key: str = bc.get("paymaster_private_key", "")
        self.platform_wallet: str = bc.get("platform_wallet", "")
        self.chain_id: int = bc.get("chain_id", 84532)

        self._queue: list[dict[str, Any]] = []
        self._lock = None  # lazy: created on first async use (Py3.9 has no loop in __init__)
        self._flush_task: asyncio.Task | None = None
        self._running: bool = False
        self._web3 = None

    def _get_lock(self) -> asyncio.Lock:
        """Lazily create the lock so __init__ doesn't need a running event loop
        (asyncio.Lock() in __init__ raises 'no current event loop' on Python 3.9)."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def web3(self):
        """Lazy-load Web3 connection."""
        if self._web3 is None:
            from web3 import Web3
            self._web3 = Web3(Web3.HTTPProvider(self.rpc_url))
        return self._web3

    @property
    def pending_count(self) -> int:
        """Number of attestations waiting in the queue."""
        return len(self._queue)

    @property
    def is_running(self) -> bool:
        """True only when the interval auto-flush task is actually running.

        NEW-51: added so `AttestationService.attest` can state the truth about
        submission rather than implying one. This distinguishes the two drain
        paths: the SIZE-THRESHOLD flush in `add()` works unconditionally, but
        the INTERVAL flush requires `start()` — which currently has no caller
        anywhere in the repo, so this returns False in production.

        Checks the task as well as the flag: `_running` is set to True by
        `start()` before the task is created, so the flag alone would report a
        running loop during a window where none exists, and would keep
        reporting one if the task died.
        """
        return self._running and self._flush_task is not None and not self._flush_task.done()

    async def start(self) -> None:
        """Start the background auto-flush task."""
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(self._auto_flush_loop())
        logger.info(
            "BatchProcessor started: batch_size=%d flush_interval=%.1fs",
            self.batch_size, self.flush_interval,
        )

    async def stop(self) -> None:
        """Stop the background task and flush remaining attestations."""
        self._running = False
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

        # Flush anything remaining
        if self._queue:
            await self.flush()
        logger.info("BatchProcessor stopped.")

    async def add(self, attestation: dict[str, Any]) -> None:
        """
        Add an attestation to the batch queue.

        If the queue reaches `batch_size`, an immediate flush is triggered.

        Args:
            attestation: Dict containing schema_uid, data, and recipient.
        """
        async with self._get_lock():
            entry = {
                "id": str(uuid.uuid4()),
                "queued_at": time.time(),
                **attestation,
            }
            self._queue.append(entry)
            queue_len = len(self._queue)

        logger.debug("Attestation queued (pending=%d): %s", queue_len, entry["id"])

        if queue_len >= self.batch_size:
            logger.info("Batch size reached (%d) — triggering flush.", queue_len)
            await self.flush()

    async def flush(self) -> list[dict[str, Any]]:
        """
        Submit all queued attestations as a batch.

        Returns:
            List of result dicts, one per attestation in the batch.
        """
        async with self._get_lock():
            if not self._queue:
                return []
            batch = self._queue.copy()
            self._queue.clear()

        logger.info("Flushing batch of %d attestations.", len(batch))

        try:
            results = await self._submit_batch(batch)
        except Exception as exc:
            logger.error("Batch submission failed: %s", exc, exc_info=True)
            results = [
                {
                    "id": att["id"],
                    "status": "failed",
                    "error": str(exc),
                }
                for att in batch
            ]

        return await self._reconcile(batch, results)

    async def _reconcile(
        self, batch: list[dict[str, Any]], results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Put back what did not land, and report each attestation as itself.

        The verdict is `report_of` on the result the client returned — the same
        predicate outcome learning reads — never on whether this coroutine
        reached its last line. An UNKNOWN is treated like a failure HERE and
        only here: the queue's question is "may this attestation still be
        owed?", and the honest answer to an unestablished submission is yes.

        Except one that was SENT. A result carrying `broadcast: True` without
        `settled: True` went out under a hash and may be mined; sending it again
        is how one attestation becomes two. It leaves the queue and its hash is
        logged.
        """
        # `_submit_batch` is contracted to return one result per attestation, in
        # order, so the pairing is POSITIONAL — matching on `id` alone would
        # silently treat every result from a submitter that does not echo the id
        # as a non-landing and re-queue a batch that went through.
        if len(results) == len(batch):
            paired = dict(zip((att["id"] for att in batch), results))
        else:
            paired = {r.get("id"): r for r in results if isinstance(r, dict)}

        landed: list[dict[str, Any]] = []
        requeue: list[dict[str, Any]] = []
        abandoned: list[str] = []
        sent_unconfirmed: list[str] = []

        for att in batch:
            result = paired.get(att["id"])
            if result is not None and report_of(result) is SUCCESS:
                landed.append(att)
                continue
            if (isinstance(result, dict) and result.get("broadcast") is True
                    and result.get("settled") is not True):
                # SENT, AND NOT CONFIRMED: NOT OWED AGAIN. The client signed and
                # sent this attestation and no receipt answered in time. It may
                # be mined. Re-queueing it — which is what an UNKNOWN gets —
                # signs and sends it a second time, and if the first lands the
                # chain holds two claims where one was made. So it leaves the
                # queue, and the hash it went out under is recorded, which is
                # what anyone checking it needs.
                sent_unconfirmed.append(f"{att['id']} tx={result.get('tx_hash')}")
                continue
            attempts = int(att.get("attempts", 0)) + 1
            att["attempts"] = attempts
            if attempts >= _MAX_ATTEMPTS:
                abandoned.append(att["id"])
            else:
                requeue.append(att)

        if requeue:
            async with self._get_lock():
                self._queue = requeue + self._queue

        if abandoned:
            logger.error(
                "Abandoning %d attestation(s) after %d failed flushes — these "
                "were NOT written to the chain: %s",
                len(abandoned), _MAX_ATTEMPTS, ", ".join(abandoned),
            )

        if sent_unconfirmed:
            logger.warning(
                "%d attestation(s) were SENT and no receipt confirmed them; they "
                "may still be mined, so they are not sent again: %s",
                len(sent_unconfirmed), ", ".join(sent_unconfirmed),
            )

        logger.info(
            "Flush complete: %d of %d attestations landed, %d sent and unconfirmed, "
            "%d re-queued, %d abandoned.",
            len(landed), len(batch), len(sent_unconfirmed), len(requeue), len(abandoned),
        )
        return results

    async def _submit_batch(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Submit a batch of attestations to the EAS contract.

        Uses the EASClient for each attestation in the batch. In production
        this would use the EAS multiAttest function for a single transaction.
        """
        try:
            client = _eas_client_for(self.config)
        except ImportError as exc:
            logger.warning("Batch submission skipped — missing dependency: %s", exc)
            return [
                {
                    "id": att["id"],
                    "status": "skipped",
                    "reason": f"Missing dependency: {exc}",
                }
                for att in batch
            ]

        results: list[dict[str, Any]] = []
        for att in batch:
            # PER ATTESTATION. A raise used to unwind past every result already
            # collected, and `flush`'s handler then re-queued the WHOLE batch:
            # the ones that HAD landed lost their record and were queued to be
            # written to the chain a second time.
            try:
                result = await client.attest(
                    action=att.get("data", {}).get("action", "batch_attestation"),
                    agent=att.get("data", {}).get("agent", "system"),
                    details=att.get("data", {}),
                    recipient=att.get("recipient", "0x0000000000000000000000000000000000000000"),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — one failure is not the batch's
                logger.error("Attestation %s failed: %s", att["id"], exc)
                result = {"status": "failed", "error": str(exc)}
            if not isinstance(result, dict):
                result = {"status": "unknown", "returned": str(result)}
            # `id` is the key the queue and every failure path use; the success
            # path set only `batch_id`, so a landed attestation and a failed one
            # could not be matched back to the same entry.
            result["id"] = att["id"]
            result["batch_id"] = att["id"]
            result["queued_at"] = att["queued_at"]
            result["submitted_at"] = time.time()
            results.append(result)

        return results

    async def _auto_flush_loop(self) -> None:
        """Background loop that auto-flushes the queue at the configured interval."""
        while self._running:
            try:
                await asyncio.sleep(self.flush_interval)
                if self._queue:
                    logger.debug("Auto-flush triggered (pending=%d).", len(self._queue))
                    await self.flush()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Auto-flush error: %s", exc, exc_info=True)
