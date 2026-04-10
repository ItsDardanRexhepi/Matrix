"""Plugin marketplace store with SQLite persistence.

Manages plugin listings, purchases, and download tracking.
Supports free and paid plugins with Stripe integration for
payment processing.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Platform commission on paid plugins
PLATFORM_COMMISSION = 0.10  # 10%


@dataclass
class PluginListing:
    """A plugin available on the marketplace."""
    plugin_id: str = field(default_factory=lambda: f"plugin_{uuid.uuid4().hex[:12]}")
    name: str = ""
    description: str = ""
    author: str = ""
    author_wallet: str = ""
    version: str = "1.0.0"
    price_usd: float = 0.0
    price_type: str = "one_time"  # one_time or monthly
    category: str = "utility"
    min_tier_required: str = "free"
    capabilities: list[str] = field(default_factory=list)
    downloads: int = 0
    rating: float = 5.0
    review_count: int = 0
    status: str = "active"  # pending, active, rejected, disabled
    repository_url: str = ""
    documentation_url: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Serialise for API responses."""
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "version": self.version,
            "price_usd": self.price_usd,
            "price_type": self.price_type,
            "category": self.category,
            "min_tier_required": self.min_tier_required,
            "capabilities": self.capabilities,
            "downloads": self.downloads,
            "rating": self.rating,
            "review_count": self.review_count,
            "status": self.status,
            "repository_url": self.repository_url,
            "documentation_url": self.documentation_url,
        }


# Built-in example plugins
EXAMPLE_PLUGINS: list[dict] = [
    {
        "name": "Hello World Plugin",
        "description": "Example plugin demonstrating the 0pnMatrx plugin API. Adds a /hello command that greets the user.",
        "author": "0pnMatrx Team",
        "version": "1.0.0",
        "price_usd": 0.0,
        "category": "example",
        "min_tier_required": "free",
        "capabilities": ["custom_command"],
        "repository_url": "https://github.com/ItsDardanRexhepi/0pnMatrx",
    },
    {
        "name": "Portfolio Tracker",
        "description": "Track your DeFi portfolio across multiple chains. Automatic balance updates and PnL calculations.",
        "author": "0pnMatrx Team",
        "version": "1.0.0",
        "price_usd": 0.0,
        "category": "finance",
        "min_tier_required": "free",
        "capabilities": ["dashboard_widget", "scheduled_task"],
    },
    {
        "name": "Gas Price Alerts",
        "description": "Get notified when gas prices drop below your threshold. Supports Base, Ethereum, and Polygon.",
        "author": "0pnMatrx Team",
        "version": "1.0.0",
        "price_usd": 0.0,
        "category": "utility",
        "min_tier_required": "free",
        "capabilities": ["notification", "scheduled_task"],
    },
]


class PluginMarketplace:
    """Developer plugin marketplace backed by SQLite.

    Manages plugin listings, purchases, downloads, and submissions.
    """

    def __init__(self, config: dict | None = None, db=None, stripe_client=None):
        """Initialise the marketplace.

        Parameters
        ----------
        config : dict, optional
            Platform configuration.
        db : Database, optional
            SQLite database for persistence.
        stripe_client : StripeClient, optional
            Stripe client for processing paid plugin purchases.
        """
        self.config = config or {}
        self.db = db
        self.stripe = stripe_client
        self.listings: dict[str, PluginListing] = {}
        self.purchases: dict[str, set[str]] = {}  # wallet -> set of plugin_ids
        self._initialised = False

    async def initialize(self) -> None:
        """Create tables and seed example plugins."""
        if self._initialised:
            return

        if self.db:
            await self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS plugin_listings (
                    plugin_id           TEXT PRIMARY KEY,
                    name                TEXT NOT NULL,
                    description         TEXT,
                    author              TEXT NOT NULL,
                    author_wallet       TEXT,
                    version             TEXT DEFAULT '1.0.0',
                    price_usd           REAL DEFAULT 0.0,
                    price_type          TEXT DEFAULT 'one_time',
                    category            TEXT DEFAULT 'utility',
                    min_tier_required   TEXT DEFAULT 'free',
                    capabilities        TEXT,
                    downloads           INTEGER DEFAULT 0,
                    rating              REAL DEFAULT 5.0,
                    review_count        INTEGER DEFAULT 0,
                    status              TEXT DEFAULT 'active',
                    repository_url      TEXT,
                    documentation_url   TEXT,
                    created_at          REAL NOT NULL,
                    updated_at          REAL NOT NULL
                )
                """,
                commit=True,
            )
            await self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS plugin_purchases (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address      TEXT NOT NULL,
                    plugin_id           TEXT NOT NULL,
                    price_paid          REAL DEFAULT 0.0,
                    stripe_session      TEXT,
                    purchased_at        REAL NOT NULL,
                    UNIQUE(wallet_address, plugin_id)
                )
                """,
                commit=True,
            )

        # Seed example plugins
        for plugin_data in EXAMPLE_PLUGINS:
            listing = PluginListing(**plugin_data)
            self.listings[listing.plugin_id] = listing

        self._initialised = True
        logger.info("Plugin marketplace initialised with %d example plugins", len(EXAMPLE_PLUGINS))

    async def list_plugins(
        self,
        tier: str | None = None,
        category: str | None = None,
        status: str = "active",
    ) -> list[dict]:
        """List available plugins, optionally filtered.

        Parameters
        ----------
        tier : str, optional
            Filter by minimum tier requirement.
        category : str, optional
            Filter by category.
        status : str
            Filter by status (default: active).
        """
        plugins = list(self.listings.values())

        if status:
            plugins = [p for p in plugins if p.status == status]
        if category:
            plugins = [p for p in plugins if p.category == category]
        if tier:
            tier_order = {"free": 0, "pro": 1, "enterprise": 2}
            tier_level = tier_order.get(tier.lower(), 0)
            plugins = [
                p for p in plugins
                if tier_order.get(p.min_tier_required, 0) <= tier_level
            ]

        return [p.to_dict() for p in plugins]

    async def get_plugin(self, plugin_id: str) -> dict | None:
        """Get a single plugin by ID."""
        listing = self.listings.get(plugin_id)
        return listing.to_dict() if listing else None

    async def purchase(
        self,
        wallet_address: str,
        plugin_id: str,
    ) -> dict:
        """Initiate a plugin purchase.

        For free plugins, completes immediately. For paid plugins,
        creates a Stripe checkout session.

        Parameters
        ----------
        wallet_address : str
            The buyer's wallet address.
        plugin_id : str
            The plugin to purchase.

        Returns
        -------
        dict
            Purchase result with checkout URL for paid plugins.
        """
        listing = self.listings.get(plugin_id)
        if not listing:
            return {"status": "error", "message": "Plugin not found."}

        # Check if already purchased
        if await self.has_purchased(wallet_address, plugin_id):
            return {"status": "already_purchased", "plugin_id": plugin_id}

        # Free plugins — instant purchase
        if listing.price_usd <= 0:
            await self._record_purchase(wallet_address, plugin_id, 0.0)
            return {
                "status": "ok",
                "plugin_id": plugin_id,
                "purchased": True,
                "price_paid": 0.0,
            }

        # Paid plugins — create Stripe session
        if self.stripe and self.stripe.available:
            base_url = self.config.get("gateway", {}).get(
                "public_url", "http://localhost:18790"
            )
            result = await self.stripe.create_checkout_session(
                tier=f"plugin_{plugin_id}",
                wallet_address=wallet_address,
                success_url=f"{base_url}/marketplace/plugins/{plugin_id}?status=purchased",
                cancel_url=f"{base_url}/marketplace",
            )
            if result.get("status") == "ok":
                return {
                    "status": "checkout",
                    "plugin_id": plugin_id,
                    "price_usd": listing.price_usd,
                    "platform_fee": round(listing.price_usd * PLATFORM_COMMISSION, 2),
                    "developer_revenue": round(listing.price_usd * (1 - PLATFORM_COMMISSION), 2),
                    "checkout_url": result["url"],
                }

        return {
            "status": "not_configured",
            "message": "Payment processing not available. Contact support.",
        }

    async def has_purchased(self, wallet_address: str, plugin_id: str) -> bool:
        """Check if a wallet has purchased a plugin."""
        if wallet_address in self.purchases:
            if plugin_id in self.purchases[wallet_address]:
                return True

        # Free plugins are always "purchased"
        listing = self.listings.get(plugin_id)
        if listing and listing.price_usd <= 0:
            return True

        if self.db:
            row = await self.db.fetchone(
                """
                SELECT 1 FROM plugin_purchases
                WHERE wallet_address = ? AND plugin_id = ?
                """,
                (wallet_address, plugin_id),
            )
            return row is not None

        return False

    async def get_purchased(self, wallet_address: str) -> list[dict]:
        """List all plugins purchased by a wallet."""
        purchased_ids = self.purchases.get(wallet_address, set())
        # Include all free plugins
        free_ids = {pid for pid, p in self.listings.items() if p.price_usd <= 0}
        all_purchased = purchased_ids | free_ids

        return [
            self.listings[pid].to_dict()
            for pid in all_purchased
            if pid in self.listings
        ]

    async def submit_listing(self, author: str, listing_data: dict) -> dict:
        """Submit a new plugin listing for review.

        Only Enterprise tier users can submit plugins.

        Parameters
        ----------
        author : str
            The author's wallet address or identifier.
        listing_data : dict
            Plugin listing fields.

        Returns
        -------
        dict
            Submission confirmation with plugin_id.
        """
        listing = PluginListing(
            name=listing_data.get("name", ""),
            description=listing_data.get("description", ""),
            author=author,
            author_wallet=listing_data.get("author_wallet", author),
            version=listing_data.get("version", "1.0.0"),
            price_usd=float(listing_data.get("price_usd", 0)),
            price_type=listing_data.get("price_type", "one_time"),
            category=listing_data.get("category", "utility"),
            min_tier_required=listing_data.get("min_tier_required", "free"),
            capabilities=listing_data.get("capabilities", []),
            repository_url=listing_data.get("repository_url", ""),
            documentation_url=listing_data.get("documentation_url", ""),
            status="pending",
        )

        self.listings[listing.plugin_id] = listing

        if self.db:
            await self.db.execute(
                """
                INSERT INTO plugin_listings
                    (plugin_id, name, description, author, author_wallet, version,
                     price_usd, price_type, category, min_tier_required, capabilities,
                     status, repository_url, documentation_url, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    listing.plugin_id, listing.name, listing.description,
                    listing.author, listing.author_wallet, listing.version,
                    listing.price_usd, listing.price_type, listing.category,
                    listing.min_tier_required, json.dumps(listing.capabilities),
                    "pending", listing.repository_url, listing.documentation_url,
                    listing.created_at, listing.updated_at,
                ),
                commit=True,
            )

        return {
            "status": "submitted",
            "plugin_id": listing.plugin_id,
            "message": "Plugin submitted for review. You will be notified when approved.",
        }

    async def record_download(self, plugin_id: str) -> None:
        """Increment the download counter for a plugin."""
        listing = self.listings.get(plugin_id)
        if listing:
            listing.downloads += 1

        if self.db:
            await self.db.execute(
                "UPDATE plugin_listings SET downloads = downloads + 1 WHERE plugin_id = ?",
                (plugin_id,),
                commit=True,
            )

    async def _record_purchase(
        self,
        wallet_address: str,
        plugin_id: str,
        price_paid: float,
    ) -> None:
        """Record a completed purchase."""
        if wallet_address not in self.purchases:
            self.purchases[wallet_address] = set()
        self.purchases[wallet_address].add(plugin_id)

        if self.db:
            await self.db.execute(
                """
                INSERT OR IGNORE INTO plugin_purchases
                    (wallet_address, plugin_id, price_paid, purchased_at)
                VALUES (?, ?, ?, ?)
                """,
                (wallet_address, plugin_id, price_paid, time.time()),
                commit=True,
            )
