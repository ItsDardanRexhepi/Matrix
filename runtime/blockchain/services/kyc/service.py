"""
KYC/AML via Sumsub, Persona, or self-sovereign credentials.

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


class KYCService:
    """KYC/AML via Sumsub, Persona, or self-sovereign credentials."""

    service_name = "kyc"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    async def start_kyc(self, **params: Any) -> dict:
        """Stub for start_kyc. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "start_kyc", "params": params},
        )

    async def check_aml_risk(self, **params: Any) -> dict:
        """Stub for check_aml_risk. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "check_aml_risk", "params": params},
        )

    async def issue_kyc_credential(self, **params: Any) -> dict:
        """Stub for issue_kyc_credential. Returns not_deployed until the adapter is wired."""
        return not_deployed_response(
            self.service_name,
            extra={"method": "issue_kyc_credential", "params": params},
        )

