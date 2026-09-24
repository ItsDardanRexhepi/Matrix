"""Developer plugin marketplace for The Matrix.

Lists plugins that extend the platform and records a free one as owned.
A paid plugin's price is quoted with the split PLATFORM_COMMISSION sets in
plugin_store.py, and the sale stops there: nothing in this repository takes a
payment, records a paid purchase or pays a developer. A submitted listing is
stored as pending, and nothing here reviews or approves one.
"""

from runtime.marketplace.plugin_store import PluginMarketplace, PluginListing

__all__ = ["PluginMarketplace", "PluginListing"]
