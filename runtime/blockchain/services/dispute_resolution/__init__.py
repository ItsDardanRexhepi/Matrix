"""
Component 30 — Decentralized Dispute Resolution for 0pnMatrx.

Handles all bilateral (user-to-user) disputes across the platform.
Platform governance lives in Component 19; this component covers
transaction disputes, NFT ownership, IP rights, contract breach,
fraud, and service quality claims.
"""

from .service import DisputeResolution

__all__ = ["DisputeResolution"]
