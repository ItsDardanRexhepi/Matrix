"""
Universal EAS Attestation Layer for 0pnMatrx.

Handles ALL attestations across the platform using Ethereum Attestation
Service (EAS) on Base. Time-critical attestations (disputes, bans, etc.)
are never batched — they attest immediately. Regular attestations can be
batched for gas efficiency.
"""

from runtime.blockchain.services.attestation.service import AttestationService

__all__ = ["AttestationService"]
