"""
Cross-chain messaging and bridging via CCIP, Hyperlane, Wormhole, Axelar, Stargate.

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


class CrossChainMessagingService:
    """Cross-chain messaging and bridging via CCIP, Hyperlane, Wormhole, Axelar, Stargate."""

    service_name = "ccip"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    async def bridge_token_ccip(self, **params: Any) -> dict:
        """Stub for bridge_token_ccip. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "bridge_token_ccip", "params": params},
        )

    async def send_cross_chain_message(self, **params: Any) -> dict:
        """Stub for send_cross_chain_message. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "send_cross_chain_message", "params": params},
        )

    async def bridge_hyperlane(self, **params: Any) -> dict:
        """Stub for bridge_hyperlane. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "bridge_hyperlane", "params": params},
        )

    async def bridge_wormhole(self, **params: Any) -> dict:
        """Stub for bridge_wormhole. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "bridge_wormhole", "params": params},
        )

    async def bridge_axelar(self, **params: Any) -> dict:
        """Stub for bridge_axelar. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "bridge_axelar", "params": params},
        )

    async def bridge_stargate(self, **params: Any) -> dict:
        """Stub for bridge_stargate. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "bridge_stargate", "params": params},
        )

    async def query_remote_chain(self, **params: Any) -> dict:
        """Stub for query_remote_chain. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "query_remote_chain", "params": params},
        )

