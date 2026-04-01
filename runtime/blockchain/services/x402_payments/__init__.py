"""
x402 Agentic Payments -- Component 10.

Implements the x402 protocol for autonomous agent-to-agent payments
with spend enforcement, limit management, and HTTP header integration
on the 0pnMatrx platform.
"""

from runtime.blockchain.services.x402_payments.service import X402PaymentService

__all__ = ["X402PaymentService"]
