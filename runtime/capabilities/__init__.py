"""
0pnMatrx Capability Framework.

A thin, data-driven layer on top of the ServiceRegistry + ServiceDispatcher
that turns the platform from a flat service list into 221 discrete Web3
capabilities across 21 categories, without file sprawl.

Public API:
    from runtime.capabilities import CapabilityRegistry, catalog

    registry = CapabilityRegistry(config)
    registry.list_capabilities()
    registry.list_by_category()
    registry.describe("restake_eigenlayer")
    await registry.invoke("restake_eigenlayer", {"amount": 1.0})
"""

from __future__ import annotations

from runtime.capabilities.registry import CapabilityRegistry
from runtime.capabilities import catalog

__all__ = ["CapabilityRegistry", "catalog"]
