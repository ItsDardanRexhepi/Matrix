"""
ProductRegistry -- on-chain product registration and search.

Each product gets a unique on-chain ID with SKU, batch, and metadata
tracking. Supports search by manufacturer, SKU, batch, and custom filters.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class ProductRegistry:
    """
    Manages product registration and lookup for the supply chain.

    Each product is assigned a unique on-chain identifier and stored
    with full metadata including SKU, batch number, and manufacturer info.

    Config keys (under config["supply_chain"]):
        require_sku     -- whether SKU is mandatory (default False)
        require_batch   -- whether batch number is mandatory (default False)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        sc = config.get("supply_chain", {})

        self.require_sku: bool = sc.get("require_sku", False)
        self.require_batch: bool = sc.get("require_batch", False)

        # product_id -> product record
        self._products: dict[str, dict[str, Any]] = {}
        # Indices for search
        self._by_manufacturer: dict[str, list[str]] = {}
        self._by_sku: dict[str, list[str]] = {}
        self._by_batch: dict[str, list[str]] = {}

        logger.info(
            "ProductRegistry initialised: require_sku=%s require_batch=%s",
            self.require_sku, self.require_batch,
        )

    async def register(self, product: dict[str, Any]) -> dict[str, Any]:
        """
        Register a new product with a unique on-chain ID.

        Args:
            product: Dict with product details:
                - name (required): Product name
                - manufacturer (required): Manufacturer address/identifier
                - sku (optional): Stock Keeping Unit
                - batch (optional): Batch/lot number
                - description (optional): Product description
                - metadata (optional): Additional key-value metadata
                - location (optional): Manufacturing location

        Returns:
            Dict with product_id, on-chain hash, and registration details.
        """
        name = product.get("name")
        manufacturer = product.get("manufacturer")

        if not name:
            return {"status": "error", "error": "Product name is required"}
        if not manufacturer:
            return {"status": "error", "error": "Manufacturer is required"}

        sku = product.get("sku", "")
        batch = product.get("batch", "")

        if self.require_sku and not sku:
            return {"status": "error", "error": "SKU is required by registry config"}
        if self.require_batch and not batch:
            return {"status": "error", "error": "Batch number is required by registry config"}

        product_id = self._generate_product_id(manufacturer, name, sku, batch)
        timestamp = int(time.time())

        record: dict[str, Any] = {
            "product_id": product_id,
            "name": name,
            "manufacturer": manufacturer,
            "sku": sku,
            "batch": batch,
            "description": product.get("description", ""),
            "metadata": product.get("metadata", {}),
            "location": product.get("location", ""),
            "registered_at": timestamp,
            "updated_at": timestamp,
            "on_chain_hash": self._compute_product_hash(product_id, manufacturer, name, sku, batch),
        }

        self._products[product_id] = record

        # Update indices
        self._by_manufacturer.setdefault(manufacturer, []).append(product_id)
        if sku:
            self._by_sku.setdefault(sku, []).append(product_id)
        if batch:
            self._by_batch.setdefault(batch, []).append(product_id)

        logger.info(
            "Product registered: id=%s name=%s manufacturer=%s sku=%s batch=%s",
            product_id, name, manufacturer, sku, batch,
        )

        return {
            "status": "registered",
            **record,
        }

    async def get_product(self, product_id: str) -> dict[str, Any]:
        """
        Retrieve a product by ID.

        Args:
            product_id: The unique product identifier.

        Returns:
            Dict with full product record, or error if not found.
        """
        product = self._products.get(product_id)
        if product is None:
            return {"status": "error", "error": f"Product not found: {product_id}"}

        return {"status": "found", **product}

    async def search(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Search products by various filters.

        Args:
            filters: Dict with optional filter keys:
                - manufacturer: Filter by manufacturer
                - sku: Filter by SKU
                - batch: Filter by batch number
                - name: Filter by name (substring match)
                - limit: Max results (default 50)

        Returns:
            List of matching product dicts.
        """
        limit = filters.get("limit", 50)
        candidates: set[str] | None = None

        # Apply index-based filters
        if "manufacturer" in filters:
            ids = set(self._by_manufacturer.get(filters["manufacturer"], []))
            candidates = ids if candidates is None else candidates & ids

        if "sku" in filters:
            ids = set(self._by_sku.get(filters["sku"], []))
            candidates = ids if candidates is None else candidates & ids

        if "batch" in filters:
            ids = set(self._by_batch.get(filters["batch"], []))
            candidates = ids if candidates is None else candidates & ids

        # Start with all products if no index filters applied
        if candidates is None:
            candidates = set(self._products.keys())

        results: list[dict[str, Any]] = []
        for pid in candidates:
            product = self._products.get(pid)
            if product is None:
                continue

            # Name substring filter
            if "name" in filters:
                if filters["name"].lower() not in product["name"].lower():
                    continue

            results.append({"status": "found", **product})

            if len(results) >= limit:
                break

        # Sort by registration time (newest first)
        results.sort(key=lambda p: p.get("registered_at", 0), reverse=True)

        return results

    async def update_product(
        self, product_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Update product metadata (not core fields like manufacturer)."""
        product = self._products.get(product_id)
        if product is None:
            return {"status": "error", "error": f"Product not found: {product_id}"}

        immutable = {"product_id", "manufacturer", "registered_at", "on_chain_hash"}
        blocked = set(updates.keys()) & immutable
        if blocked:
            return {
                "status": "error",
                "error": f"Cannot update immutable fields: {sorted(blocked)}",
            }

        for key, value in updates.items():
            if key == "metadata" and isinstance(value, dict):
                product.setdefault("metadata", {}).update(value)
            else:
                product[key] = value

        product["updated_at"] = int(time.time())

        return {"status": "updated", **product}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_product_id(
        manufacturer: str, name: str, sku: str, batch: str
    ) -> str:
        raw = f"{manufacturer}:{name}:{sku}:{batch}:{uuid.uuid4().hex}:{time.time()}"
        return "prod_" + hashlib.sha256(raw.encode()).hexdigest()[:24]

    @staticmethod
    def _compute_product_hash(
        product_id: str, manufacturer: str, name: str, sku: str, batch: str
    ) -> str:
        payload = f"{product_id}|{manufacturer}|{name}|{sku}|{batch}"
        return "0x" + hashlib.sha256(payload.encode()).hexdigest()
