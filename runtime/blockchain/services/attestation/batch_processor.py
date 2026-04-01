"""
Batch Processor for EAS attestations in 0pnMatrx.

Collects non-time-critical attestations and submits them in batches to
reduce gas costs. The batch is flushed when either the batch size limit
is reached or the flush interval elapses — whichever comes first.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


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
        self._lock: asyncio.Lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._running: bool = False
        self._web3 = None

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
        async with self._lock:
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
        async with self._lock:
            if not self._queue:
                return []
            batch = self._queue.copy()
            self._queue.clear()

        logger.info("Flushing batch of %d attestations.", len(batch))

        try:
            results = await self._submit_batch(batch)
            logger.info("Batch of %d attestations submitted successfully.", len(batch))
            return results
        except Exception as exc:
            logger.error("Batch submission failed: %s", exc, exc_info=True)
            # Re-queue failed attestations for retry
            async with self._lock:
                self._queue = batch + self._queue
            logger.warning("Re-queued %d attestations after failure.", len(batch))
            return [
                {
                    "id": att["id"],
                    "status": "failed",
                    "error": str(exc),
                }
                for att in batch
            ]

    async def _submit_batch(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Submit a batch of attestations to the EAS contract.

        Uses the EASClient for each attestation in the batch. In production
        this would use the EAS multiAttest function for a single transaction.
        """
        try:
            from runtime.blockchain.eas_client import EASClient

            client = EASClient(self.config)
            results: list[dict[str, Any]] = []

            for att in batch:
                result = await client.attest(
                    action=att.get("data", {}).get("action", "batch_attestation"),
                    agent=att.get("data", {}).get("agent", "system"),
                    details=att.get("data", {}),
                    recipient=att.get("recipient", "0x0000000000000000000000000000000000000000"),
                )
                result["batch_id"] = att["id"]
                result["queued_at"] = att["queued_at"]
                result["submitted_at"] = time.time()
                results.append(result)

            return results

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
