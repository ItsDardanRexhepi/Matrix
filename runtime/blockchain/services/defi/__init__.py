"""
DeFi Layer — Component 2.

Provides lending, borrowing, collateral management, peer-to-peer lending,
token whitelist governance, and lender reputation tracking for the
0pnMatrx platform.
"""

from runtime.blockchain.services.defi.service import DeFiService

__all__ = ["DeFiService"]
