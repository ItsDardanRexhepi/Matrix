"""
SupplyChainService -- end-to-end supply chain verification for 0pnMatrx.

Manages product registration, status tracking, provenance chains,
authenticity verification, and custody transfers. Integrates with
ProductRegistry, QRCodeGenerator, and OwnershipListener.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.supply_chain.product_registry import ProductRegistry
from runtime.blockchain.services.supply_chain.qr_codes import QRCodeGenerator
from runtime.blockchain.services.supply_chain.ownership_listener import OwnershipListener

logger = logging.getLogger(__name__)

VALID_STATUSES = {
    "manufactured",
    "quality_checked",
    "shipped",
    "in_transit",
    "customs",
    "delivered",
    "returned",
}

# Status transition rules: current_status -> set of allowed next statuses
STATUS_TRANSITIONS: dict[str, set[str]] = {
    "manufactured": {"quality_checked", "shipped"},
    "quality_checked": {"shipped", "returned"},
    "shipped": {"in_transit", "delivered"},
    "in_transit": {"customs", "delivered", "returned"},
    "customs": {"in_transit", "delivered", "returned"},
    "delivered": {"returned"},
    "returned": {"quality_checked", "shipped"},
}


class SupplyChainService:
    """
    Main supply chain verification service.

    Provides product lifecycle management from manufacturing through
    delivery, with full provenance tracking and authenticity verification.

    Config keys (under config["supply_chain"]):
        allowed_statuses    -- optional override of valid statuses
        network             -- blockchain network
    Config keys (under config["blockchain"]):
        platform_wallet     -- platform address
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        sc = config.get("supply_chain", {})
        bc = config.get("blockchain", {})

        self.network: str = bc.get("network", "base-sepolia")
        self.allowed_statuses: set[str] = set(
            sc.get("allowed_statuses", VALID_STATUSES)
        )

        # Sub-components
        self._registry = ProductRegistry(config)
        self._qr_generator = QRCodeGenerator(config)
        self._ownership_listener = OwnershipListener(config)

        # product_id -> list of status/event records (provenance chain)
        self._provenance: dict[str, list[dict[str, Any]]] = {}
        # product_id -> current custody holder
        self._custody: dict[str, str] = {}

        logger.info(
            "SupplyChainService initialised: network=%s statuses=%d",
            self.network, len(self.allowed_statuses),
        )

    @property
    def registry(self) -> ProductRegistry:
        return self._registry

    @property
    def qr_generator(self) -> QRCodeGenerator:
        return self._qr_generator

    @property
    def ownership_listener(self) -> OwnershipListener:
        return self._ownership_listener

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def register_product(
        self,
        manufacturer: str,
        product_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Register a new product in the supply chain.

        Args:
            manufacturer: Manufacturer address or identifier.
            product_data: Product details (name, sku, batch, description, metadata).

        Returns:
            Dict with product_id, registration details, and QR code.
        """
        if not manufacturer:
            return {"status": "error", "error": "Manufacturer is required"}

        if not product_data.get("name"):
            return {"status": "error", "error": "Product name is required"}

        # Register in product registry
        product_data["manufacturer"] = manufacturer
        reg_result = await self._registry.register(product_data)

        if reg_result.get("status") == "error":
            return reg_result

        product_id = reg_result["product_id"]
        timestamp = int(time.time())

        # Initialise provenance chain
        genesis_event = {
            "event": "registered",
            "status": "manufactured",
            "manufacturer": manufacturer,
            "handler": manufacturer,
            "location": product_data.get("location", "origin"),
            "timestamp": timestamp,
            "hash": self._compute_event_hash(product_id, "registered", timestamp),
        }
        self._provenance[product_id] = [genesis_event]
        self._custody[product_id] = manufacturer

        # Generate QR code
        qr_result = await self._qr_generator.generate(
            product_id, include_data=["product_id", "manufacturer", "sku"]
        )

        logger.info(
            "Product registered: id=%s manufacturer=%s name=%s",
            product_id, manufacturer, product_data.get("name"),
        )

        return {
            "status": "registered",
            **reg_result,
            "provenance": [genesis_event],
            "current_custody": manufacturer,
            "qr_code": qr_result,
        }

    async def update_status(
        self,
        product_id: str,
        status: str,
        location: str,
        handler: str,
    ) -> dict[str, Any]:
        """
        Update the status of a product in the supply chain.

        Validates status transitions and records the event in the
        provenance chain.

        Args:
            product_id: The product identifier.
            status: New status (must be a valid status value).
            location: Current location of the product.
            handler: Person/entity handling the product.

        Returns:
            Dict with updated status and provenance entry.
        """
        # Validate product exists
        product = await self._registry.get_product(product_id)
        if product.get("status") == "error":
            return product

        status = status.lower()
        if status not in self.allowed_statuses:
            return {
                "status": "error",
                "error": f"Invalid status: {status}. Valid: {sorted(self.allowed_statuses)}",
            }

        # Get current status from provenance
        chain = self._provenance.get(product_id, [])
        if not chain:
            return {"status": "error", "error": f"No provenance chain for product: {product_id}"}

        current_status = chain[-1].get("status", "manufactured")

        # Validate transition
        allowed_next = STATUS_TRANSITIONS.get(current_status, set())
        if status not in allowed_next and status != current_status:
            return {
                "status": "error",
                "error": (
                    f"Invalid status transition: {current_status} -> {status}. "
                    f"Allowed: {sorted(allowed_next)}"
                ),
            }

        timestamp = int(time.time())
        event = {
            "event": "status_update",
            "status": status,
            "previous_status": current_status,
            "location": location,
            "handler": handler,
            "timestamp": timestamp,
            "hash": self._compute_event_hash(product_id, status, timestamp),
            "previous_hash": chain[-1]["hash"],
        }

        chain.append(event)

        logger.info(
            "Status updated: product=%s %s -> %s location=%s handler=%s",
            product_id, current_status, status, location, handler,
        )

        return {
            "status": "updated",
            "product_id": product_id,
            "new_status": status,
            "previous_status": current_status,
            "event": event,
            "chain_length": len(chain),
        }

    async def track(self, product_id: str) -> dict[str, Any]:
        """
        Get the full provenance chain for a product.

        Args:
            product_id: The product identifier.

        Returns:
            Dict with product info, full provenance chain, and current status.
        """
        product = await self._registry.get_product(product_id)
        if product.get("status") == "error":
            return product

        chain = self._provenance.get(product_id, [])
        current_status = chain[-1]["status"] if chain else "unknown"
        current_handler = self._custody.get(product_id, "unknown")

        # Verify chain integrity
        integrity = self._verify_chain_integrity(chain)

        return {
            "status": "tracked",
            "product_id": product_id,
            "product": product,
            "current_status": current_status,
            "current_custody": current_handler,
            "provenance_chain": chain,
            "chain_length": len(chain),
            "chain_integrity": integrity,
        }

    async def verify(self, product_id: str) -> dict[str, Any]:
        """
        Verify the authenticity of a product.

        Checks product registration, provenance chain integrity,
        and on-chain hash validity.

        Args:
            product_id: The product identifier.

        Returns:
            Dict with verification result (authentic/suspicious/unknown).
        """
        product = await self._registry.get_product(product_id)
        if product.get("status") == "error":
            return {
                "verified": False,
                "product_id": product_id,
                "result": "unknown",
                "reason": "Product not found in registry",
            }

        chain = self._provenance.get(product_id, [])
        if not chain:
            return {
                "verified": False,
                "product_id": product_id,
                "result": "suspicious",
                "reason": "No provenance chain found",
            }

        # Verify chain integrity
        integrity = self._verify_chain_integrity(chain)

        # Verify on-chain hash
        on_chain_hash = product.get("on_chain_hash", "")
        hash_valid = bool(on_chain_hash and on_chain_hash.startswith("0x"))

        is_authentic = integrity["valid"] and hash_valid

        return {
            "verified": is_authentic,
            "product_id": product_id,
            "result": "authentic" if is_authentic else "suspicious",
            "chain_integrity": integrity,
            "on_chain_hash_valid": hash_valid,
            "on_chain_hash": on_chain_hash,
            "chain_length": len(chain),
            "manufacturer": product.get("manufacturer", "unknown"),
            "registered_at": product.get("registered_at"),
        }

    async def transfer_custody(
        self,
        product_id: str,
        from_handler: str,
        to_handler: str,
    ) -> dict[str, Any]:
        """
        Transfer custody of a product from one handler to another.

        Args:
            product_id: The product identifier.
            from_handler: Current custody holder.
            to_handler: New custody holder.

        Returns:
            Dict with custody transfer details.
        """
        product = await self._registry.get_product(product_id)
        if product.get("status") == "error":
            return product

        current_holder = self._custody.get(product_id)
        if current_holder is None:
            return {
                "status": "error",
                "error": f"No custody record for product: {product_id}",
            }

        if current_holder != from_handler:
            return {
                "status": "error",
                "error": (
                    f"Custody mismatch: current holder is '{current_holder}', "
                    f"not '{from_handler}'"
                ),
            }

        if from_handler == to_handler:
            return {"status": "error", "error": "Cannot transfer custody to the same handler"}

        timestamp = int(time.time())

        # Record custody transfer in provenance chain
        chain = self._provenance.get(product_id, [])
        event = {
            "event": "custody_transfer",
            "status": chain[-1]["status"] if chain else "unknown",
            "from_handler": from_handler,
            "to_handler": to_handler,
            "timestamp": timestamp,
            "hash": self._compute_event_hash(
                product_id, f"custody:{from_handler}->{to_handler}", timestamp
            ),
            "previous_hash": chain[-1]["hash"] if chain else None,
        }
        chain.append(event)

        # Update custody
        self._custody[product_id] = to_handler

        logger.info(
            "Custody transferred: product=%s %s -> %s",
            product_id, from_handler, to_handler,
        )

        return {
            "status": "transferred",
            "product_id": product_id,
            "from_handler": from_handler,
            "to_handler": to_handler,
            "timestamp": timestamp,
            "event": event,
            "chain_length": len(chain),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_event_hash(
        product_id: str, event_data: str, timestamp: int
    ) -> str:
        payload = f"{product_id}|{event_data}|{timestamp}"
        return "0x" + hashlib.sha256(payload.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Expanded supply chain operations
    # ------------------------------------------------------------------

    async def log_event(
        self, product_id: str, event_type: str, data: dict[str, Any], handler: str = "",
    ) -> dict[str, Any]:
        """Log a custom provenance event."""
        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        chain = self._provenance.get(product_id, [])
        event = {
            "id": event_id,
            "event": event_type,
            "data": data,
            "handler": handler,
            "timestamp": now,
            "hash": self._compute_event_hash(product_id, event_type, now),
            "previous_hash": chain[-1]["hash"] if chain else None,
        }
        self._provenance.setdefault(product_id, []).append(event)
        record: dict[str, Any] = {
            "id": event_id,
            "status": "logged",
            "product_id": product_id,
            "event_type": event_type,
            "data": data,
            "handler": handler,
            "logged_at": now,
        }
        logger.info("Provenance event logged: id=%s", event_id)
        return record

    async def track_batch(
        self, batch_id: str, product_ids: list[str], location: str = "", handler: str = "",
    ) -> dict[str, Any]:
        """Track a batch of products together."""
        track_id = f"batch_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = {
            "id": track_id,
            "status": "tracked",
            "batch_id": batch_id,
            "product_ids": product_ids,
            "product_count": len(product_ids),
            "location": location,
            "handler": handler,
            "tracked_at": now,
        }
        logger.info("Batch tracked: id=%s products=%d", track_id, len(product_ids))
        return record

    async def verify_authenticity(
        self, product_id: str, verifier: str = "",
    ) -> dict[str, Any]:
        """Verify product authenticity via provenance chain."""
        auth_id = f"auth_{uuid.uuid4().hex[:16]}"
        chain = self._provenance.get(product_id, [])
        integrity = self._verify_chain_integrity(chain) if chain else {"valid": False, "length": 0, "issues": ["No provenance chain"]}
        record: dict[str, Any] = {
            "id": auth_id,
            "status": "verified",
            "product_id": product_id,
            "verifier": verifier,
            "authentic": integrity["valid"],
            "chain_length": integrity["length"],
            "issues": integrity.get("issues", []),
            "verified_at": int(time.time()),
        }
        logger.info("Authenticity verified: id=%s authentic=%s", auth_id, integrity["valid"])
        return record

    @staticmethod
    def _verify_chain_integrity(chain: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Verify the integrity of a provenance chain by checking hash links.

        Each event (after the first) should reference the previous event's hash.
        """
        if not chain:
            return {"valid": True, "length": 0, "issues": []}

        issues: list[str] = []

        for i in range(1, len(chain)):
            prev_hash = chain[i - 1].get("hash")
            ref_hash = chain[i].get("previous_hash")

            if ref_hash is not None and ref_hash != prev_hash:
                issues.append(
                    f"Chain break at index {i}: expected previous_hash "
                    f"'{prev_hash}' but got '{ref_hash}'"
                )

            if not chain[i].get("hash"):
                issues.append(f"Missing hash at index {i}")

        return {
            "valid": len(issues) == 0,
            "length": len(chain),
            "issues": issues,
        }
