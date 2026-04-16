"""
Restaking across EigenLayer, Symbiotic, Karak and liquid-restaking protocols.

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


class RestakingService:
    """Restaking across EigenLayer, Symbiotic, Karak and liquid-restaking protocols."""

    service_name = "restaking"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    async def restake(self, **params: Any) -> dict:
        """Stub for restake. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "restake", "params": params},
        )

    async def restake_symbiotic(self, **params: Any) -> dict:
        """Stub for restake_symbiotic. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "restake_symbiotic", "params": params},
        )

    async def restake_karak(self, **params: Any) -> dict:
        """Stub for restake_karak. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "restake_karak", "params": params},
        )

    async def delegate_to_operator(self, **params: Any) -> dict:
        """Stub for delegate_to_operator. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "delegate_to_operator", "params": params},
        )

    async def withdraw_restake(self, **params: Any) -> dict:
        """Stub for withdraw_restake. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "withdraw_restake", "params": params},
        )

    async def liquid_stake_lido(self, **params: Any) -> dict:
        """Stub for liquid_stake_lido. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "liquid_stake_lido", "params": params},
        )

    async def liquid_stake_rocketpool(self, **params: Any) -> dict:
        """Stub for liquid_stake_rocketpool. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "liquid_stake_rocketpool", "params": params},
        )

