"""
Chainlink price feed integration for Base L2.

Reads on-chain aggregator contracts to return latest and historical
prices.  All feed addresses are config-driven with sensible defaults
for Base mainnet.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Chainlink Aggregator V3 ABI (read-only subset) ──────────────────

AGGREGATOR_ABI: list[dict[str, Any]] = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "_roundId", "type": "uint80"}],
        "name": "getRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "description",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# ── Default Chainlink feed addresses on Base ─────────────────────────

CHAINLINK_FEEDS: dict[str, str] = {
    "ETH/USD":  "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70",
    "BTC/USD":  "0x0FB99723Aee6f420beAD13e6bBB79cE7e6076B4F",
    "USDC/USD": "0x7e860098F58bBFC8648a4311b374B1D669a2bc6B",
    "LINK/USD": "0x17CAb8FE31cA45e4677d77Ca3e18AB6BE03e4aDa",
    "DAI/USD":  "0x591e79239a7d679378eC8c847e5038150364C78F",
    "USDT/USD": "0xf19d560eB8d2ADf07BD6D13ed03e1D11215721F9",
}


class PriceFeedProvider:
    """Reads Chainlink aggregator contracts on Base L2.

    Parameters
    ----------
    config : dict
        Full platform config.  Reads ``oracle.price_feeds`` for
        feed-address overrides and ``blockchain.rpc_url`` for the Web3
        provider.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        oracle_cfg = config.get("oracle", {})
        feed_overrides: dict[str, str] = oracle_cfg.get("price_feeds", {})
        self._feeds: dict[str, str] = {**CHAINLINK_FEEDS, **feed_overrides}

        self._rpc_url: str = config.get("blockchain", {}).get("rpc_url", "")
        self._web3: Any = None

    # ------------------------------------------------------------------
    # Lazy Web3 initialisation
    # ------------------------------------------------------------------

    @property
    def web3(self) -> Any:
        if self._web3 is None:
            try:
                from web3 import Web3
                self._web3 = Web3(Web3.HTTPProvider(self._rpc_url))
            except ImportError:
                raise RuntimeError(
                    "web3 package is required — run: pip install web3"
                )
        return self._web3

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_latest_price(self, pair: str) -> dict[str, Any]:
        """Fetch the most recent price for *pair* (e.g. ``ETH/USD``).

        Returns
        -------
        dict
            Keys: ``pair``, ``price``, ``raw_answer``, ``decimals``,
            ``timestamp``, ``round_id``.
        """
        pair = pair.upper()
        contract = self._get_contract(pair)

        try:
            round_data = contract.functions.latestRoundData().call()
            decimals = contract.functions.decimals().call()
            description = contract.functions.description().call()
        except Exception as exc:
            logger.error("Failed to read Chainlink feed for %s: %s", pair, exc)
            raise RuntimeError(f"Price feed read failed for {pair}") from exc

        price = round_data[1] / (10 ** decimals)

        return {
            "pair": description,
            "price": price,
            "raw_answer": str(round_data[1]),
            "decimals": decimals,
            "timestamp": round_data[3],
            "round_id": str(round_data[0]),
        }

    async def get_historical_price(
        self, pair: str, round_id: int
    ) -> dict[str, Any]:
        """Fetch the price for a specific *round_id*.

        Returns the same shape as :meth:`get_latest_price`.
        """
        pair = pair.upper()
        contract = self._get_contract(pair)

        try:
            round_data = contract.functions.getRoundData(round_id).call()
            decimals = contract.functions.decimals().call()
            description = contract.functions.description().call()
        except Exception as exc:
            logger.error(
                "Historical price read failed for %s round %s: %s",
                pair, round_id, exc,
            )
            raise RuntimeError(
                f"Historical price read failed for {pair} round {round_id}"
            ) from exc

        price = round_data[1] / (10 ** decimals)

        return {
            "pair": description,
            "price": price,
            "raw_answer": str(round_data[1]),
            "decimals": decimals,
            "timestamp": round_data[3],
            "round_id": str(round_data[0]),
        }

    def list_supported_pairs(self) -> list[str]:
        """Return every pair name that has a configured feed address."""
        return sorted(self._feeds.keys())

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_contract(self, pair: str) -> Any:
        """Resolve pair to a Web3 contract instance."""
        from web3 import Web3

        address = self._feeds.get(pair)
        if address is None:
            raise ValueError(
                f"Unsupported pair '{pair}'. "
                f"Available: {', '.join(self.list_supported_pairs())}"
            )

        return self.web3.eth.contract(
            address=Web3.to_checksum_address(address),
            abi=AGGREGATOR_ABI,
        )
