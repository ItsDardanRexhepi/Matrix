"""
Oracles — query and interact with on-chain oracles on Base L2.

Supports Chainlink price feeds and custom oracle contracts.
Read operations are gas-free. Write operations have gas covered by platform.
"""

import json
import logging

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)

CHAINLINK_AGGREGATOR_ABI = [
    {"inputs": [], "name": "latestRoundData", "outputs": [
        {"name": "roundId", "type": "uint80"},
        {"name": "answer", "type": "int256"},
        {"name": "startedAt", "type": "uint256"},
        {"name": "updatedAt", "type": "uint256"},
        {"name": "answeredInRound", "type": "uint80"},
    ], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "description", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
]

# Chainlink price feed addresses on Base
BASE_PRICE_FEEDS = {
    "ETH/USD": "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70",
    "BTC/USD": "0x0FB99723Aee6f420beAD13e6bBB79cE7e6076B4F",
    "USDC/USD": "0x7e860098F58bBFC8648a4311b374B1D669a2bc6B",
}


class Oracles(BlockchainInterface):

    @property
    def name(self) -> str:
        return "oracle"

    @property
    def description(self) -> str:
        return "Query Chainlink price feeds and custom oracles on Base L2."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get_price", "list_feeds", "query_custom"]},
                "pair": {"type": "string", "description": "Price pair (e.g., ETH/USD)"},
                "oracle_address": {"type": "string", "description": "Custom oracle contract address"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "get_price":
            return await self._get_price(kwargs)
        elif action == "list_feeds":
            return await self._list_feeds(kwargs)
        elif action == "query_custom":
            return await self._query_custom(kwargs)
        return f"Unknown oracle action: {action}"

    async def _get_price(self, params: dict) -> str:
        """Get latest price from Chainlink feed."""
        try:
            from web3 import Web3
            pair = params.get("pair", "ETH/USD").upper()
            feed_address = BASE_PRICE_FEEDS.get(pair)
            if not feed_address:
                # Try custom oracle address
                feed_address = params.get("oracle_address", "")
                if not feed_address:
                    return f"Unknown price pair: {pair}. Available: {', '.join(BASE_PRICE_FEEDS.keys())}"

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(feed_address),
                abi=CHAINLINK_AGGREGATOR_ABI,
            )

            round_data = contract.functions.latestRoundData().call()
            decimals = contract.functions.decimals().call()
            description = contract.functions.description().call()

            price = round_data[1] / (10 ** decimals)

            return json.dumps({
                "pair": description,
                "price": f"${price:,.2f}",
                "raw_price": str(round_data[1]),
                "decimals": decimals,
                "updated_at": round_data[3],
                "round_id": str(round_data[0]),
                "network": self.network,
            }, indent=2)
        except Exception as e:
            return f"Price query failed: {e}"

    async def _list_feeds(self, params: dict) -> str:
        return json.dumps({
            "network": self.network,
            "feeds": {pair: addr for pair, addr in BASE_PRICE_FEEDS.items()},
        }, indent=2)

    async def _query_custom(self, params: dict) -> str:
        """Query a custom oracle contract's latestRoundData."""
        oracle_addr = params.get("oracle_address", "")
        if not oracle_addr:
            return "Error: oracle_address required"
        return await self._get_price({"pair": "CUSTOM", "oracle_address": oracle_addr})
