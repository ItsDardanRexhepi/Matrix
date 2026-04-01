"""Marketplace Service - Component 24.

Provides listing, buying, searching, and cancellation for a multi-type
marketplace with 5 percent platform fee and compliance filtering.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from .compliance_filter import ComplianceFilter
from .appeals import AppealProcess

logger = logging.getLogger(__name__)

VALID_ITEM_TYPES = {"nft", "physical", "digital", "service", "rwa"}

DEFAULT_CONFIG: dict[str, Any] = {
    "platform_fee_pct": 5.0,
    "platform_wallet": "0xPLATFORM_TREASURY",
    "min_price": 0.01,
    "max_price": 1_000_000_000.0,
    "allowed_item_types": list(VALID_ITEM_TYPES),
}


class MarketplaceService:
    """Multi-type marketplace with compliance filtering and appeals.

    Supports NFTs, physical goods, digital goods, services, and real-world
    assets. Applies a 5% platform fee on all sales.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self._listings: dict[str, dict] = {}
        self._sales: list[dict] = []
        self.compliance = ComplianceFilter(self.config)
        self.appeals = AppealProcess(self.config)
        logger.info(
            "MarketplaceService initialised (fee=%.1f%%, wallet=%s)",
            self.config["platform_fee_pct"],
            self.config["platform_wallet"],
        )

    async def list_item(self, seller: str, item_type: str, metadata: dict, price: float) -> dict:
        """Create a new marketplace listing.

        Args:
            seller: Seller's wallet address.
            item_type: One of 'nft', 'physical', 'digital', 'service', 'rwa'.
            metadata: Item details (title, description, images, attributes).
            price: Listing price in platform currency.

        Returns:
            The created listing record with compliance check result.
        """
        if not seller:
            raise ValueError("seller is required")
        if item_type not in VALID_ITEM_TYPES:
            raise ValueError(f"Invalid item_type '{item_type}'. Must be one of: {VALID_ITEM_TYPES}")
        if price < self.config["min_price"]:
            raise ValueError(f"Price must be at least {self.config['min_price']}")
        if price > self.config["max_price"]:
            raise ValueError(f"Price cannot exceed {self.config['max_price']}")
        if not metadata.get("title"):
            raise ValueError("metadata.title is required")

        listing_id = f"lst_{uuid.uuid4().hex[:12]}"
        now = time.time()

        listing = {
            "listing_id": listing_id,
            "seller": seller,
            "item_type": item_type,
            "metadata": metadata,
            "price": price,
            "status": "pending_review",
            "created_at": now,
            "updated_at": now,
        }

        # Run compliance check
        compliance_result = await self.compliance.check_listing(listing)
        if compliance_result["decision"] == "rejected":
            listing["status"] = "rejected"
            listing["rejection_reason"] = compliance_result["reason"]
            self._listings[listing_id] = listing
            logger.warning("Listing %s rejected: %s", listing_id, compliance_result["reason"])
            return {**listing, "compliance": compliance_result}

        if compliance_result["decision"] == "flagged":
            listing["status"] = "flagged"
            listing["flag_reason"] = compliance_result["reason"]
        else:
            listing["status"] = "active"

        self._listings[listing_id] = listing
        logger.info("Listed item %s by seller %s (type=%s, price=%.2f)", listing_id, seller, item_type, price)
        return {**listing, "compliance": compliance_result}

    async def buy_item(self, listing_id: str, buyer: str) -> dict:
        """Purchase a listed item.

        Applies the platform fee and records the sale.

        Args:
            listing_id: The listing to purchase.
            buyer: Buyer's wallet address.

        Returns:
            Sale record with fee breakdown.
        """
        if not buyer:
            raise ValueError("buyer is required")

        listing = self._listings.get(listing_id)
        if not listing:
            raise ValueError(f"Listing '{listing_id}' not found")
        if listing["status"] != "active":
            raise ValueError(f"Listing '{listing_id}' is not active (status={listing['status']})")
        if listing["seller"] == buyer:
            raise ValueError("Buyer cannot be the seller")

        fee_pct = self.config["platform_fee_pct"] / 100.0
        platform_fee = round(listing["price"] * fee_pct, 8)
        seller_proceeds = round(listing["price"] - platform_fee, 8)

        sale_id = f"sale_{uuid.uuid4().hex[:12]}"
        now = time.time()

        sale = {
            "sale_id": sale_id,
            "listing_id": listing_id,
            "buyer": buyer,
            "seller": listing["seller"],
            "item_type": listing["item_type"],
            "price": listing["price"],
            "platform_fee": platform_fee,
            "platform_wallet": self.config["platform_wallet"],
            "seller_proceeds": seller_proceeds,
            "completed_at": now,
        }

        listing["status"] = "sold"
        listing["buyer"] = buyer
        listing["sold_at"] = now
        listing["updated_at"] = now

        self._sales.append(sale)
        logger.info(
            "Sale %s completed: listing=%s, buyer=%s, price=%.2f, fee=%.2f",
            sale_id, listing_id, buyer, listing["price"], platform_fee,
        )
        return sale

    async def cancel_listing(self, listing_id: str, seller: str) -> dict:
        """Cancel an active listing.

        Args:
            listing_id: The listing to cancel.
            seller: Must match the listing's seller.

        Returns:
            The updated listing record.
        """
        listing = self._listings.get(listing_id)
        if not listing:
            raise ValueError(f"Listing '{listing_id}' not found")
        if listing["seller"] != seller:
            raise ValueError("Only the seller can cancel a listing")
        if listing["status"] not in ("active", "flagged", "pending_review"):
            raise ValueError(f"Cannot cancel listing with status '{listing['status']}'")

        listing["status"] = "cancelled"
        listing["updated_at"] = time.time()
        logger.info("Listing %s cancelled by seller %s", listing_id, seller)
        return listing

    async def search(self, query: dict) -> list:
        """Search listings by criteria.

        Args:
            query: Search filters. Supported keys:
                - item_type: filter by type
                - min_price / max_price: price range
                - seller: filter by seller
                - keyword: search in title/description
                - status: filter by status (default 'active')
                - limit: max results (default 50)
                - offset: pagination offset (default 0)

        Returns:
            List of matching listings.
        """
        results = []
        status_filter = query.get("status", "active")
        item_type_filter = query.get("item_type")
        min_price = query.get("min_price", 0)
        max_price = query.get("max_price", float("inf"))
        seller_filter = query.get("seller")
        keyword = query.get("keyword", "").lower()
        limit = query.get("limit", 50)
        offset = query.get("offset", 0)

        for listing in self._listings.values():
            if status_filter and listing["status"] != status_filter:
                continue
            if item_type_filter and listing["item_type"] != item_type_filter:
                continue
            if listing["price"] < min_price or listing["price"] > max_price:
                continue
            if seller_filter and listing["seller"] != seller_filter:
                continue
            if keyword:
                title = listing["metadata"].get("title", "").lower()
                desc = listing["metadata"].get("description", "").lower()
                if keyword not in title and keyword not in desc:
                    continue
            results.append(listing)

        # Sort by most recent first
        results.sort(key=lambda x: x["created_at"], reverse=True)
        return results[offset: offset + limit]

    async def get_listing(self, listing_id: str) -> dict:
        """Get a single listing by ID.

        Returns:
            The listing record.
        """
        listing = self._listings.get(listing_id)
        if not listing:
            raise ValueError(f"Listing '{listing_id}' not found")
        return listing
