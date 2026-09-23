"""
Blockchain Module — on-chain capabilities for The Matrix.

Gas is sponsored by the platform within the operator's sponsorship policy
(sponsorship.py), with the exemptions listed there. ServiceDispatcher records
an EAS attestation, best effort, for a state-changing action that completed;
a refusal or an unconfirmed broadcast is not attested as done.

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
