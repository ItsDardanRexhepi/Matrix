"""Plugin marketplace store with SQLite persistence.

Manages plugin listings and download tracking.

Nothing here installs a plugin. A free listing counts as owned by every caller
(`has_purchased`), so its purchase route records nothing and places no code; a
plugin runs only when its package is put in `plugins/installed/`, where
runtime/plugins/loader.py finds it. Paid plugin purchases are NOT built: there is no App
Store product for a plugin (gateway/iap.py) and no server path that records a
paid plugin purchase, so the paid branch answers `not_built` rather than
pointing the caller at a checkout that does not exist.
"""

from __future__ import annotations

import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)



def platform_commission_rate(config: dict | None) -> float | None:
    """The commission this deployment applies to paid plugin sales, or None.

    Configuration (`plugin_marketplace.commission_rate`, a fraction in [0, 1]),
    not a constant in the public repository — the same reason subscription
    prices left runtime/subscriptions. Unset is unknown, and so is anything
    that is not a finite fraction: reporting a guessed rate as the platform's
    term would be worse than reporting none.
    """
    raw = ((config or {}).get("plugin_marketplace") or {}).get("commission_rate")
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        # float(True) is 1.0: `"commission_rate": true` would read as the whole sale.
        logger.error("plugin_marketplace.commission_rate is %r, a boolean, not a "
                     "fraction; treating the commission as unknown", raw)
        return None
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        logger.error("plugin_marketplace.commission_rate is %r, not a number; "
                     "treating the commission as unknown", raw)
        return None
    if not math.isfinite(rate) or not 0.0 <= rate <= 1.0:
        logger.error("plugin_marketplace.commission_rate is %r, not a fraction "
                     "in [0, 1]; treating the commission as unknown", raw)
        return None
    return rate


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


# Built-in example listings. Each must name a plugin that exists in this tree
# (tests/test_plugin_marketplace_installs_nothing.py): two listings described
# plugins with no implementation anywhere, and the marketplace page rendered
# them as plugins on the gateway.
EXAMPLE_PLUGINS: list[dict] = [
    {
        "name": "Hello World Plugin",
        "description": ("Example plugin demonstrating the 0pnMatrx plugin API: a /hello "
                        "command and a greeting tool (runtime/plugins/example_plugin.py). "
                        "Listing it does not install it."),
        "author": "0pnMatrx Team",
        "version": "1.0.0",
        "price_usd": 0.0,
        "category": "example",
        "min_tier_required": "free",
        "capabilities": ["custom_command"],
        "repository_url": "https://github.com/ItsDardanRexhepi/0pnMatrx",
    },
]


class PluginMarketplace:
    """Developer plugin marketplace backed by SQLite.

    Manages plugin listings, purchases, downloads, and submissions.
    """

    def __init__(self, config: dict | None = None, db=None, **_unused):
        """Initialise the marketplace.

        Parameters
        ----------
        config : dict, optional
            Platform configuration.
        db : Database, optional
            SQLite database for persistence.

        Paid plugin purchases are not built (see the module docstring):
        nothing on this server records one.
        """
        self.config = config or {}
        self.db = db
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
        """Answer a plugin purchase request. Installs nothing.

        A free listing counts as owned by every caller, so it answers
        ``already_purchased`` with ``installed: False`` and records nothing. A
        paid listing answers ``status: not_built`` — no purchase path exists to
        complete one.

        Parameters
        ----------
        wallet_address : str
            The buyer's wallet address.
        plugin_id : str
            The plugin to purchase.

        Returns
        -------
        dict
            Purchase result; ``not_built`` for a paid plugin.
        """
        listing = self.listings.get(plugin_id)
        if not listing:
            return {"status": "error", "message": "Plugin not found."}

        # A free listing is owned by every caller (has_purchased), so the free
        # "instant purchase" branch that used to follow this check could never
        # run, and nothing anywhere installed the plugin it named. Say so.
        if await self.has_purchased(wallet_address, plugin_id):
            return {
                "status": "already_purchased",
                "plugin_id": plugin_id,
                "installed": False,
                "message": (
                    "Nothing to buy or record: this listing is already owned. The "
                    "marketplace does not install plugins; a plugin runs when its "
                    "package is placed in plugins/installed/ on the gateway."
                ),
            }

        # Paid plugins. This used to answer `requires_iap` with a 10/90 split
        # of the sticker price and "complete the purchase in the MTRX iOS app".
        # There is no App Store product for a plugin, /api/v1/iap/verify never
        # records plugin ownership, and no code records a paid purchase (the
        # free-branch recorder was unreachable and is gone) — so that purchase
        # could not be completed, and
        # the "developer_revenue" figure ignored the App Store commission that
        # comes off an IAP sale first. No proceeds figure is returned: there is
        # no sale to have proceeds.
        return {
            "status": "not_built",
            "plugin_id": plugin_id,
            "price_usd": listing.price_usd,
            "platform_commission_rate": platform_commission_rate(self.config),
            "message": (
                "Paid plugin purchases are not available: no App Store product "
                "exists for a plugin and no server path records a paid plugin "
                "purchase, so nothing can complete or verify one yet."
            ),
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
        """Store a new plugin listing with status pending. Nothing reviews,
        approves or activates it.

        No subscription tier is checked here or in the route handler; the
        route is behind the gateway API key. ``author`` is whatever the
        caller supplied and is not verified.

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
            "message": ("Plugin listing stored with status pending. It is not listed "
                        "until it is made active; this gateway has no approval route."),
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
