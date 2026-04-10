"""Multi-chain abstraction layer for 0pnMatrx.

Provides a unified interface for interacting with multiple EVM-compatible
blockchains. The platform defaults to Base but can route transactions to
any configured chain.

Supported chains:
  - Base (default) -- Coinbase's L2, low fees, high throughput
  - Ethereum -- mainnet, highest security
  - Optimism -- OP Stack L2
  - Arbitrum -- Nitro L2
  - Polygon -- sidechain, very low fees
  - Avalanche -- C-Chain, fast finality
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ChainId(int, Enum):
    """Well-known EVM chain IDs."""
    # Mainnets
    ETHEREUM = 1
    OPTIMISM = 10
    POLYGON = 137
    ARBITRUM = 42161
    AVALANCHE = 43114
    BASE = 8453

    # Testnets
    ETHEREUM_SEPOLIA = 11155111
    OPTIMISM_SEPOLIA = 11155420
    BASE_SEPOLIA = 84532
    ARBITRUM_SEPOLIA = 421614
    POLYGON_AMOY = 80002
    AVALANCHE_FUJI = 43113


@dataclass
class ChainConfig:
    """Configuration for a single blockchain network."""
    chain_id: int
    name: str
    display_name: str
    rpc_url: str
    explorer_url: str
    native_currency: str
    native_decimals: int = 18
    is_testnet: bool = False
    is_l2: bool = False
    avg_block_time: float = 2.0
    supports_eip1559: bool = True
    paymaster_enabled: bool = False
    eas_contract: str = ""
    max_gas_price_gwei: float = 100.0

    @property
    def explorer_tx_url(self) -> str:
        """URL template for transaction explorer links."""
        return f"{self.explorer_url}/tx/"

    @property
    def explorer_address_url(self) -> str:
        """URL template for address explorer links."""
        return f"{self.explorer_url}/address/"


# -- Default Chain Configurations ---------------------------------------------

DEFAULT_CHAINS: dict[int, ChainConfig] = {
    ChainId.BASE: ChainConfig(
        chain_id=ChainId.BASE,
        name="base",
        display_name="Base",
        rpc_url="https://mainnet.base.org",
        explorer_url="https://basescan.org",
        native_currency="ETH",
        is_l2=True,
        avg_block_time=2.0,
        paymaster_enabled=True,
        eas_contract="0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587",
    ),
    ChainId.ETHEREUM: ChainConfig(
        chain_id=ChainId.ETHEREUM,
        name="ethereum",
        display_name="Ethereum",
        rpc_url="https://eth.llamarpc.com",
        explorer_url="https://etherscan.io",
        native_currency="ETH",
        avg_block_time=12.0,
        eas_contract="0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587",
    ),
    ChainId.OPTIMISM: ChainConfig(
        chain_id=ChainId.OPTIMISM,
        name="optimism",
        display_name="Optimism",
        rpc_url="https://mainnet.optimism.io",
        explorer_url="https://optimistic.etherscan.io",
        native_currency="ETH",
        is_l2=True,
        avg_block_time=2.0,
        eas_contract="0x4200000000000000000000000000000000000021",
    ),
    ChainId.ARBITRUM: ChainConfig(
        chain_id=ChainId.ARBITRUM,
        name="arbitrum",
        display_name="Arbitrum One",
        rpc_url="https://arb1.arbitrum.io/rpc",
        explorer_url="https://arbiscan.io",
        native_currency="ETH",
        is_l2=True,
        avg_block_time=0.25,
        eas_contract="0xbD75f629A22Dc1ceD33dDA0b68c546A1c035c458",
    ),
    ChainId.POLYGON: ChainConfig(
        chain_id=ChainId.POLYGON,
        name="polygon",
        display_name="Polygon",
        rpc_url="https://polygon-rpc.com",
        explorer_url="https://polygonscan.com",
        native_currency="MATIC",
        avg_block_time=2.0,
        max_gas_price_gwei=500.0,
    ),
    ChainId.AVALANCHE: ChainConfig(
        chain_id=ChainId.AVALANCHE,
        name="avalanche",
        display_name="Avalanche C-Chain",
        rpc_url="https://api.avax.network/ext/bc/C/rpc",
        explorer_url="https://snowtrace.io",
        native_currency="AVAX",
        avg_block_time=2.0,
    ),
    # Testnets
    ChainId.BASE_SEPOLIA: ChainConfig(
        chain_id=ChainId.BASE_SEPOLIA,
        name="base-sepolia",
        display_name="Base Sepolia",
        rpc_url="https://sepolia.base.org",
        explorer_url="https://sepolia.basescan.org",
        native_currency="ETH",
        is_testnet=True,
        is_l2=True,
        avg_block_time=2.0,
        paymaster_enabled=True,
        eas_contract="0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587",
    ),
    ChainId.ETHEREUM_SEPOLIA: ChainConfig(
        chain_id=ChainId.ETHEREUM_SEPOLIA,
        name="ethereum-sepolia",
        display_name="Ethereum Sepolia",
        rpc_url="https://rpc.sepolia.org",
        explorer_url="https://sepolia.etherscan.io",
        native_currency="ETH",
        is_testnet=True,
        avg_block_time=12.0,
    ),
    ChainId.OPTIMISM_SEPOLIA: ChainConfig(
        chain_id=ChainId.OPTIMISM_SEPOLIA,
        name="optimism-sepolia",
        display_name="Optimism Sepolia",
        rpc_url="https://sepolia.optimism.io",
        explorer_url="https://sepolia-optimism.etherscan.io",
        native_currency="ETH",
        is_testnet=True,
        is_l2=True,
    ),
    ChainId.ARBITRUM_SEPOLIA: ChainConfig(
        chain_id=ChainId.ARBITRUM_SEPOLIA,
        name="arbitrum-sepolia",
        display_name="Arbitrum Sepolia",
        rpc_url="https://sepolia-rollup.arbitrum.io/rpc",
        explorer_url="https://sepolia.arbiscan.io",
        native_currency="ETH",
        is_testnet=True,
        is_l2=True,
    ),
    ChainId.POLYGON_AMOY: ChainConfig(
        chain_id=ChainId.POLYGON_AMOY,
        name="polygon-amoy",
        display_name="Polygon Amoy",
        rpc_url="https://rpc-amoy.polygon.technology",
        explorer_url="https://amoy.polygonscan.com",
        native_currency="MATIC",
        is_testnet=True,
    ),
    ChainId.AVALANCHE_FUJI: ChainConfig(
        chain_id=ChainId.AVALANCHE_FUJI,
        name="avalanche-fuji",
        display_name="Avalanche Fuji",
        rpc_url="https://api.avax-test.network/ext/bc/C/rpc",
        explorer_url="https://testnet.snowtrace.io",
        native_currency="AVAX",
        is_testnet=True,
    ),
}


class ChainRouter:
    """Routes blockchain operations to the appropriate chain.

    Maintains a registry of configured chains and provides methods
    to resolve chain configs, select the best chain for an operation,
    and validate chain availability.
    """

    def __init__(self, config: dict | None = None):
        """Initialise the chain router.

        Parameters
        ----------
        config : dict, optional
            Platform configuration. Chain-specific overrides can be
            provided under ``blockchain.chains``.
        """
        self.chains: dict[int, ChainConfig] = dict(DEFAULT_CHAINS)
        self._default_chain_id: int = ChainId.BASE_SEPOLIA

        if config:
            self._apply_config(config)

    def _apply_config(self, config: dict) -> None:
        """Apply configuration overrides for chains."""
        bc = config.get("blockchain", {})

        # Set default chain from config
        chain_id = bc.get("chain_id")
        if chain_id and int(chain_id) in self.chains:
            self._default_chain_id = int(chain_id)

        # Override RPC URL for default chain
        rpc_url = bc.get("rpc_url", "")
        if rpc_url and not rpc_url.startswith("YOUR_"):
            if self._default_chain_id in self.chains:
                self.chains[self._default_chain_id].rpc_url = rpc_url

        # Apply per-chain overrides from config
        chain_overrides = bc.get("chains", {})
        for chain_name, overrides in chain_overrides.items():
            chain = self.get_by_name(chain_name)
            if chain:
                if "rpc_url" in overrides:
                    chain.rpc_url = overrides["rpc_url"]
                if "paymaster_enabled" in overrides:
                    chain.paymaster_enabled = overrides["paymaster_enabled"]
                if "eas_contract" in overrides:
                    chain.eas_contract = overrides["eas_contract"]

    @property
    def default_chain(self) -> ChainConfig:
        """The platform's default chain configuration."""
        return self.chains[self._default_chain_id]

    def get(self, chain_id: int) -> ChainConfig | None:
        """Get a chain config by chain ID."""
        return self.chains.get(chain_id)

    def get_by_name(self, name: str) -> ChainConfig | None:
        """Get a chain config by name (e.g. 'base', 'ethereum')."""
        name_lower = name.lower().replace(" ", "-")
        for chain in self.chains.values():
            if chain.name == name_lower:
                return chain
        return None

    def resolve(self, chain: str | int | None = None) -> ChainConfig:
        """Resolve a chain identifier to a ChainConfig.

        Accepts chain ID (int), chain name (str), or None for default.

        Parameters
        ----------
        chain : str | int | None
            Chain identifier. None uses the default chain.

        Returns
        -------
        ChainConfig
            The resolved chain configuration.

        Raises
        ------
        ValueError
            If the chain identifier is not recognised.
        """
        if chain is None:
            return self.default_chain

        if isinstance(chain, int):
            config = self.get(chain)
            if config:
                return config
            raise ValueError(f"Unknown chain ID: {chain}")

        if isinstance(chain, str):
            # Try as name first
            config = self.get_by_name(chain)
            if config:
                return config
            # Try as numeric string
            try:
                return self.resolve(int(chain))
            except (ValueError, KeyError):
                pass
            raise ValueError(f"Unknown chain: {chain}")

        raise ValueError(f"Invalid chain identifier: {chain}")

    def available_chains(self, include_testnets: bool = False) -> list[ChainConfig]:
        """List all available chains.

        Parameters
        ----------
        include_testnets : bool
            Whether to include testnet chains (default False).
        """
        chains = list(self.chains.values())
        if not include_testnets:
            chains = [c for c in chains if not c.is_testnet]
        return sorted(chains, key=lambda c: c.name)

    def l2_chains(self) -> list[ChainConfig]:
        """List all Layer 2 chains."""
        return [c for c in self.chains.values() if c.is_l2 and not c.is_testnet]

    def chains_with_eas(self) -> list[ChainConfig]:
        """List chains that have EAS (Ethereum Attestation Service) deployed."""
        return [c for c in self.chains.values() if c.eas_contract and not c.is_testnet]

    def cheapest_chain(self) -> ChainConfig:
        """Return the chain with the lowest expected transaction cost.

        Heuristic: L2s with paymasters are cheapest.
        """
        candidates = [c for c in self.chains.values() if not c.is_testnet]
        # Prefer: paymaster-enabled L2 > L2 > L1
        def cost_score(c: ChainConfig) -> int:
            score = 0
            if c.is_l2:
                score -= 2
            if c.paymaster_enabled:
                score -= 3
            return score
        return min(candidates, key=cost_score, default=self.default_chain)

    def to_dict(self) -> dict:
        """Serialise all chains to a dict for API responses."""
        return {
            "default_chain": self.default_chain.name,
            "chains": {
                chain.name: {
                    "chain_id": chain.chain_id,
                    "display_name": chain.display_name,
                    "native_currency": chain.native_currency,
                    "is_l2": chain.is_l2,
                    "is_testnet": chain.is_testnet,
                    "explorer_url": chain.explorer_url,
                    "supports_eip1559": chain.supports_eip1559,
                    "paymaster_enabled": chain.paymaster_enabled,
                    "has_eas": bool(chain.eas_contract),
                }
                for chain in sorted(self.chains.values(), key=lambda c: c.name)
            },
        }
