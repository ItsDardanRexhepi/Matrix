"""
Pyth, RedStone, API3 data feeds and Chainlink Keepers automation.

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


class OraclesPlusService:
    """Pyth, RedStone, API3 data feeds and Chainlink Keepers automation."""

    service_name = "oracles_plus"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    async def pyth_pull(self, **params: Any) -> dict:
        """Stub for pyth_pull. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "pyth_pull", "params": params},
        )

    async def redstone_request(self, **params: Any) -> dict:
        """Stub for redstone_request. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "redstone_request", "params": params},
        )

    async def api3_query(self, **params: Any) -> dict:
        """Stub for api3_query. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "api3_query", "params": params},
        )

    async def register_keeper_job(self, **params: Any) -> dict:
        """Stub for register_keeper_job. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "register_keeper_job", "params": params},
        )

