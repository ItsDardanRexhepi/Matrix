"""
Blockchain Module — on-chain capabilities for 0pnMatrx.

Gas is paid by the platform within its sponsorship policy (ERC-4337 paymaster).
A request past the per-identity daily cap is refused, not charged to the user.
Every state-changing action is attested via EAS.

This package exposes ``Web3Manager`` (and the ``not_deployed_response``
helper) so services across the platform share a single web3 connection
and a uniform fallback shape for offline / pre-deployment environments.
"""

from runtime.blockchain.web3_manager import (
    Web3Manager,
    is_placeholder_value,
    not_deployed_response,
)

__all__ = ["Web3Manager", "is_placeholder_value", "not_deployed_response"]
