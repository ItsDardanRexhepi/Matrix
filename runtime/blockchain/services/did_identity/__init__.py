"""
Decentralized Identity (DID) — Component 5.

Decentralized Identifiers and credentials shaped after the W3C DID Core and
Verifiable Credentials data models, with selective disclosure and
zero-knowledge proof capabilities.

Shaped after, not compliant with: nothing in this package holds a key or makes
a signature. A credential's or a presentation's "proof" is a SHA-256 digest
this process records, labelled as a digest; a DID document's public key is a
hash of the DID; and every store is in memory. Only this process can check a
proof, by comparing against what it recorded.
"""

from .service import DIDService

__all__ = ["DIDService"]
