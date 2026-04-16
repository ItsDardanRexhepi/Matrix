"""
Layer-2 state channels and Raiden-style off-chain payment routing.

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


class PaymentChannelsService:
    """Layer-2 state channels and Raiden-style off-chain payment routing."""

    service_name = "payment_channels"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    async def open_channel(self, **params: Any) -> dict:
        """Stub for open_channel. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "open_channel", "params": params},
        )

    async def route_payment(self, **params: Any) -> dict:
        """Stub for route_payment. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "route_payment", "params": params},
        )

    async def close_channel(self, **params: Any) -> dict:
        """Stub for close_channel. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "close_channel", "params": params},
        )

