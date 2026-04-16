"""
NFT-backed loans (BendDAO, NFTfi, Arcade) and NFT breeding mechanics.

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


class NFTLendingService:
    """NFT-backed loans (BendDAO, NFTfi, Arcade) and NFT breeding mechanics."""

    service_name = "nft_lending"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    async def borrow_against_nft(self, **params: Any) -> dict:
        """Stub for borrow_against_nft. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "borrow_against_nft", "params": params},
        )

    async def liquidate_nft_loan(self, **params: Any) -> dict:
        """Stub for liquidate_nft_loan. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "liquidate_nft_loan", "params": params},
        )

    async def breed_nft(self, **params: Any) -> dict:
        """Stub for breed_nft. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "breed_nft", "params": params},
        )

