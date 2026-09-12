"""Developer plugin marketplace for 0pnMatrx.

Lists plugins that extend the platform and installs free ones. Paid plugin
sales are not built: the purchase route answers 501 for a paid plugin, and no
server path records a paid purchase or pays out revenue. The commission that
would apply is configuration (``plugin_marketplace.commission_rate``), not a
number in this package.
"""

from runtime.marketplace.plugin_store import PluginMarketplace, PluginListing

__all__ = ["PluginMarketplace", "PluginListing"]
