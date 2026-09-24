"""
Blockchain Module — on-chain capabilities for The Matrix.

Gas for the transactions THE PLATFORM signs is sponsored within the
operator's sponsorship policy (sponsorship.py), with the exemptions listed
there. That is not every transaction a user takes part in: several services
prepare an unsigned transaction for the user's own wallet to sign and send
(advanced governance, auctions), and that wallet pays its gas.

Attestation is narrower than "every state-changing action". The
ServiceDispatcher queues an EAS attestation, best effort, for a
state-modifying action that it dispatched and that completed, written to the
chain once 50 have gathered in the same process; a refusal or an unconfirmed
broadcast is not attested as done. Without EAS configured, EASClient answers
``skipped`` and the action still happens. A blockchain capability called as
an agent tool directly (``smart_contract``, ``nfts`` and the rest) does not
pass through the dispatcher and is not attested there.

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
