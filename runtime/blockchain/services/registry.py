"""Service registry with lazy initialization and caching."""

from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Mapping of service name -> (module_name, class_name)
_SERVICE_MAP: dict[str, tuple[str, str]] = {
    "contract_conversion": (".contract_conversion", "ContractConversionService"),
    "defi": (".defi", "DeFiService"),
    "nft_services": (".nft_services", "NFTService"),
    "rwa_tokenization": (".rwa_tokenization", "RWAService"),
    "did_identity": (".did_identity", "DIDService"),
    "dao_management": (".dao_management", "DAOService"),
    "stablecoin": (".stablecoin", "StablecoinService"),
    "attestation": (".attestation", "AttestationService"),
    "agent_identity": (".agent_identity", "AgentIdentityService"),
    "x402_payments": (".x402_payments", "X402PaymentService"),
    "oracle_gateway": (".oracle_gateway", "OracleGateway"),
    "supply_chain": (".supply_chain", "SupplyChainService"),
    "insurance": (".insurance", "InsuranceService"),
    "gaming": (".gaming", "GamingService"),
    "ip_royalties": (".ip_royalties", "IPRoyaltyService"),
    "staking": (".staking", "StakingService"),
    "cross_border": (".cross_border", "CrossBorderService"),
    "securities_exchange": (".securities_exchange", "SecuritiesExchangeService"),
    "governance": (".governance", "GovernanceService"),
    "dashboard": (".dashboard", "DashboardService"),
    "dex": (".dex", "DEXService"),
    "fundraising": (".fundraising", "FundraisingService"),
    "loyalty": (".loyalty", "LoyaltyService"),
    "marketplace": (".marketplace", "MarketplaceService"),
    "cashback": (".cashback", "CashbackService"),
    "brand_rewards": (".brand_rewards", "BrandRewardService"),
    "subscriptions": (".subscriptions", "SubscriptionService"),
    "social": (".social", "SocialService"),
    "privacy": (".privacy", "PrivacyService"),
    "dispute_resolution": (".dispute_resolution", "DisputeResolution"),
}

_PACKAGE = __package__


class ServiceRegistry:
    """Registry that lazily initializes and caches service instances.

    Services are imported via importlib on first access to avoid circular
    imports at module load time.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._instances: dict[str, Any] = {}
        logger.debug("ServiceRegistry created with %d available services", len(_SERVICE_MAP))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, service_name: str) -> Any:
        """Return a cached service instance, creating it on first access.

        Args:
            service_name: One of the registered service keys.

        Returns:
            An initialized service instance.

        Raises:
            KeyError: If *service_name* is not a registered service.
            ImportError: If the backing module cannot be imported.
        """
        if service_name in self._instances:
            return self._instances[service_name]

        if service_name not in _SERVICE_MAP:
            raise KeyError(
                f"Unknown service {service_name!r}. "
                f"Available: {', '.join(sorted(_SERVICE_MAP))}"
            )

        module_path, class_name = _SERVICE_MAP[service_name]
        logger.info("Lazily importing %s from %s", class_name, module_path)

        module = importlib.import_module(module_path, package=_PACKAGE)
        cls = getattr(module, class_name)

        instance = cls(self._config)
        self._instances[service_name] = instance
        logger.info("Service %r initialized (%s)", service_name, class_name)
        return instance

    def list_services(self) -> list[str]:
        """Return a sorted list of all registered service names."""
        return sorted(_SERVICE_MAP)

    def get_all(self) -> dict[str, Any]:
        """Initialize (if needed) and return every registered service."""
        for name in _SERVICE_MAP:
            if name not in self._instances:
                try:
                    self.get(name)
                except Exception:
                    logger.exception("Failed to initialize service %r", name)
        return dict(self._instances)
