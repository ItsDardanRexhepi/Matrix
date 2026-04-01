"""
OwnershipListener -- listens for RWA ownership transfer events.

Integrates with Component 4 (RWA Tokenization) to update supply chain
records when real-world asset ownership changes. Maintains a complete
ownership history per asset.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Valid ownership event types
VALID_EVENT_TYPES = {
    "ownership_transfer",
    "fractional_transfer",
    "custody_change",
    "lien_placed",
    "lien_released",
}


class OwnershipListener:
    """
    Listens for and processes ownership transfer events from Component 4.

    When an RWA ownership changes on-chain, this listener updates the
    corresponding supply chain records and maintains a full ownership
    history for audit purposes.

    Config keys (under config["supply_chain"]):
        auto_update_custody -- auto-update custody on ownership transfer (default True)
        event_retention_days-- how long to retain processed events (default 365)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        sc = config.get("supply_chain", {})

        self.auto_update_custody: bool = sc.get("auto_update_custody", True)
        self.event_retention_days: int = sc.get("event_retention_days", 365)

        # asset_id -> list of ownership records
        self._ownership_history: dict[str, list[dict[str, Any]]] = {}
        # asset_id -> current owner
        self._current_owners: dict[str, str] = {}
        # Processed events log
        self._processed_events: list[dict[str, Any]] = []

        # Callback for notifying supply chain service of custody changes
        self._custody_callback: Any = None

        logger.info(
            "OwnershipListener initialised: auto_update_custody=%s retention=%d days",
            self.auto_update_custody, self.event_retention_days,
        )

    def set_custody_callback(self, callback: Any) -> None:
        """Set a callback to be invoked when custody needs updating."""
        self._custody_callback = callback

    async def on_ownership_transfer(self, event: dict[str, Any]) -> dict[str, Any]:
        """
        Process an ownership transfer event from Component 4.

        Updates ownership history and optionally triggers custody
        updates in the supply chain.

        Args:
            event: Ownership event dict with:
                - asset_id (required): The RWA/product identifier
                - from_owner (required): Previous owner address
                - to_owner (required): New owner address
                - event_type (optional): Type of ownership event
                - tx_hash (optional): On-chain transaction hash
                - block_number (optional): Block number of the event
                - metadata (optional): Additional event metadata

        Returns:
            Dict with processing result and updated ownership info.
        """
        asset_id = event.get("asset_id")
        from_owner = event.get("from_owner")
        to_owner = event.get("to_owner")
        event_type = event.get("event_type", "ownership_transfer")

        # Validation
        if not asset_id:
            return {"status": "error", "error": "asset_id is required"}
        if not from_owner:
            return {"status": "error", "error": "from_owner is required"}
        if not to_owner:
            return {"status": "error", "error": "to_owner is required"}

        if event_type not in VALID_EVENT_TYPES:
            return {
                "status": "error",
                "error": f"Invalid event_type: {event_type}. Valid: {sorted(VALID_EVENT_TYPES)}",
            }

        # Verify from_owner matches current owner (if we have records)
        current = self._current_owners.get(asset_id)
        if current is not None and current != from_owner:
            logger.warning(
                "Ownership mismatch for asset %s: expected owner %s but event says %s",
                asset_id, current, from_owner,
            )
            # Still process the event but flag the mismatch
            mismatch_warning = (
                f"Current owner mismatch: records show '{current}' "
                f"but event from '{from_owner}'"
            )
        else:
            mismatch_warning = None

        timestamp = int(time.time())

        # Create ownership record
        ownership_record: dict[str, Any] = {
            "asset_id": asset_id,
            "from_owner": from_owner,
            "to_owner": to_owner,
            "event_type": event_type,
            "tx_hash": event.get("tx_hash", ""),
            "block_number": event.get("block_number"),
            "timestamp": timestamp,
            "metadata": event.get("metadata", {}),
            "record_hash": self._compute_record_hash(
                asset_id, from_owner, to_owner, timestamp
            ),
        }

        # Update ownership history
        self._ownership_history.setdefault(asset_id, []).append(ownership_record)
        self._current_owners[asset_id] = to_owner

        # Record processed event
        processed = {
            "event": ownership_record,
            "processed_at": timestamp,
            "auto_custody_update": self.auto_update_custody,
        }
        self._processed_events.append(processed)

        # Trigger custody callback if configured
        custody_updated = False
        if self.auto_update_custody and self._custody_callback is not None:
            try:
                await self._custody_callback(asset_id, from_owner, to_owner)
                custody_updated = True
            except Exception as exc:
                logger.error(
                    "Custody callback failed for asset %s: %s", asset_id, exc
                )

        logger.info(
            "Ownership transfer processed: asset=%s %s -> %s type=%s",
            asset_id, from_owner, to_owner, event_type,
        )

        result: dict[str, Any] = {
            "status": "processed",
            "asset_id": asset_id,
            "from_owner": from_owner,
            "to_owner": to_owner,
            "event_type": event_type,
            "timestamp": timestamp,
            "record_hash": ownership_record["record_hash"],
            "ownership_count": len(self._ownership_history[asset_id]),
            "custody_updated": custody_updated,
        }

        if mismatch_warning:
            result["warning"] = mismatch_warning

        return result

    async def get_ownership_history(self, asset_id: str) -> list[dict[str, Any]]:
        """
        Get the complete ownership history for an asset.

        Args:
            asset_id: The asset/product identifier.

        Returns:
            List of ownership records, oldest first.
        """
        history = self._ownership_history.get(asset_id, [])

        if not history:
            return []

        return [
            {
                **record,
                "index": i,
                "is_current": i == len(history) - 1,
            }
            for i, record in enumerate(history)
        ]

    async def get_current_owner(self, asset_id: str) -> dict[str, Any]:
        """Get the current owner of an asset."""
        owner = self._current_owners.get(asset_id)
        if owner is None:
            return {
                "asset_id": asset_id,
                "owner": None,
                "status": "unknown",
            }

        history = self._ownership_history.get(asset_id, [])
        latest = history[-1] if history else {}

        return {
            "asset_id": asset_id,
            "owner": owner,
            "status": "known",
            "since": latest.get("timestamp"),
            "transfer_count": len(history),
        }

    async def get_processed_events(
        self, limit: int = 50, asset_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Get recently processed ownership events."""
        events = self._processed_events

        if asset_id is not None:
            events = [
                e for e in events
                if e["event"].get("asset_id") == asset_id
            ]

        return events[-limit:]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_record_hash(
        asset_id: str, from_owner: str, to_owner: str, timestamp: int
    ) -> str:
        payload = f"{asset_id}|{from_owner}|{to_owner}|{timestamp}"
        return "0x" + hashlib.sha256(payload.encode()).hexdigest()
