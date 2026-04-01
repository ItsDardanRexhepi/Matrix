"""
Supply Chain Verification -- Component 12.

Provides end-to-end supply chain tracking with product registration,
provenance chains, QR code generation, custody transfers, and
integration with RWA ownership events from Component 4.
"""

from runtime.blockchain.services.supply_chain.service import SupplyChainService

__all__ = ["SupplyChainService"]
