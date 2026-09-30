"""
Blockchain Module — on-chain capabilities for The Matrix.

Gas for an operation the platform signs is paid by the platform within the
deployment's sponsorship policy (runtime/blockchain/sponsorship.py): an
operation off the action allowlist, when one is set, is refused with or
without a cap; with a per-identity daily cap set, a request past it or not
attributable to a signed-in identity is refused too, rather than charged to
the user; with no cap, nothing limits what the platform spends on what the
allowlist lets through, or on every operation where no allowlist is set; with
no paymaster key, nothing is sponsored. The platform's own records, listed
there, are exempt.
ServiceDispatcher queues an EAS attestation, best effort, for a state-changing
action that completed, written to the chain once 50 have gathered in the same
process; a refusal or an unconfirmed broadcast is not attested as done.

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
