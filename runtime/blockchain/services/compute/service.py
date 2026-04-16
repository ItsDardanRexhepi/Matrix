"""
Decentralized compute (Akash, Gensyn, Render) and DePIN device rentals.

This service is a stub until real protocol integrations are wired in.
Every method returns the canonical not_deployed_response until the
backend contracts / adapter SDKs are configured. Once the platform
operator populates the relevant config keys, individual methods can
swap their bodies for the real implementation without changing the
service interface.

All state-modifying methods MUST route on-chain transactions through
``runtime.blockchain.gas_sponsor.GasSponsor`` so the platform pays gas.
"""

from __future__ import annotations

import logging
from typing import Any

from runtime.blockchain.web3_manager import Web3Manager, not_deployed_response

logger = logging.getLogger(__name__)


class DecentralizedComputeService:
    """Decentralized compute (Akash, Gensyn, Render) and DePIN device rentals."""

    service_name = "compute"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    async def submit_compute_job(self, **params: Any) -> dict:
        """Stub for submit_compute_job. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "submit_compute_job", "params": params},
        )

    async def rent_device(self, **params: Any) -> dict:
        """Stub for rent_device. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "rent_device", "params": params},
        )

    async def claim_compute_reward(self, **params: Any) -> dict:
        """Stub for claim_compute_reward. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "claim_compute_reward", "params": params},
        )

