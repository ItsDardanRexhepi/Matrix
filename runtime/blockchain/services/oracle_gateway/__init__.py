"""
Oracle Integration Layer — Component 11.

Single gateway for ALL oracle data requests across the 0pnMatrx platform.
Every component that needs external data (prices, weather, sports,
randomness, etc.) routes through :class:`OracleGateway`.
"""

from .gateway import OracleGateway

__all__ = ["OracleGateway"]
