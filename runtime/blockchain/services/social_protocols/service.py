"""
Lens, Farcaster, Push Protocol integrations and social/creator token launches.

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


class SocialProtocolsService:
    """Lens, Farcaster, Push Protocol integrations and social/creator token launches."""

    service_name = "social_protocols"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    async def create_lens_profile(self, **params: Any) -> dict:
        """Stub for create_lens_profile. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "create_lens_profile", "params": params},
        )

    async def publish_cast(self, **params: Any) -> dict:
        """Stub for publish_cast. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "publish_cast", "params": params},
        )

    async def push_subscribe(self, **params: Any) -> dict:
        """Stub for push_subscribe. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "push_subscribe", "params": params},
        )

    async def launch_social_token(self, **params: Any) -> dict:
        """Stub for launch_social_token. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "launch_social_token", "params": params},
        )

    async def launch_creator_coin(self, **params: Any) -> dict:
        """Stub for launch_creator_coin. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "launch_creator_coin", "params": params},
        )

