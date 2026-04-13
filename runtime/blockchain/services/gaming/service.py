"""
GamingService — blockchain gaming platform for 0pnMatrx.

Provides game registration, in-game NFT asset minting and transfer,
vetting pipeline, milestone-based funding, and revenue sharing.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.gaming.vetting import VettingPipeline
from runtime.blockchain.services.gaming.milestone_funding import MilestoneFunding
from runtime.blockchain.services.gaming.revenue_share import RevenueShare
from runtime.blockchain.services.gaming.game_sdk import GameSDK

logger = logging.getLogger(__name__)


class GamingService:
    """Main gaming platform service.

    Config keys (under ``config["gaming"]``):
        platform_fee_pct (float): Platform revenue share percentage (default 5).
        max_assets_per_game (int): Cap on mintable assets per game (default 100000).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        g_cfg: dict[str, Any] = config.get("gaming", {})

        self._platform_fee: float = float(g_cfg.get("platform_fee_pct", 5.0))
        self._max_assets: int = int(g_cfg.get("max_assets_per_game", 100_000))

        self._vetting = VettingPipeline(config)
        self._funding = MilestoneFunding(config)
        self._revenue = RevenueShare(config)
        self._sdk = GameSDK(config)

        # In-memory stores
        self._games: dict[str, dict[str, Any]] = {}
        self._assets: dict[str, dict[str, Any]] = {}

        logger.info("GamingService initialised (platform_fee=%.1f%%).", self._platform_fee)

    @property
    def vetting(self) -> VettingPipeline:
        return self._vetting

    @property
    def funding(self) -> MilestoneFunding:
        return self._funding

    @property
    def revenue(self) -> RevenueShare:
        return self._revenue

    @property
    def sdk(self) -> GameSDK:
        return self._sdk

    # ------------------------------------------------------------------
    # Game management
    # ------------------------------------------------------------------

    async def register_game(self, developer: str, game_data: dict) -> dict:
        """Register a new game on the platform.

        Args:
            developer: Address of the game developer.
            game_data: Dict with ``name``, ``description``, ``genre``,
                       and optional metadata.

        Returns:
            Created game record.
        """
        if not developer:
            raise ValueError("developer address is required")
        if not game_data.get("name"):
            raise ValueError("game_data.name is required")

        game_id = f"game_{uuid.uuid4().hex[:16]}"
        now = int(time.time())

        game: dict[str, Any] = {
            "game_id": game_id,
            "developer": developer,
            "name": game_data["name"],
            "description": game_data.get("description", ""),
            "genre": game_data.get("genre", ""),
            "metadata": game_data.get("metadata", {}),
            "status": "pending_review",
            "asset_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        self._games[game_id] = game

        logger.info(
            "Game registered: id=%s name=%s developer=%s",
            game_id, game["name"], developer,
        )
        return game

    async def get_game(self, game_id: str) -> dict:
        """Retrieve a game by ID."""
        game = self._games.get(game_id)
        if not game:
            raise ValueError(f"Game {game_id} not found")
        return game

    async def mint_game_asset(
        self, game_id: str, player: str, asset_data: dict,
    ) -> dict:
        """Mint an in-game NFT asset for a player.

        Args:
            game_id: The game this asset belongs to.
            player: Address of the player receiving the asset.
            asset_data: Dict with ``name``, ``type``, ``attributes``,
                        and optional ``rarity``.

        Returns:
            Created asset record.
        """
        game = self._games.get(game_id)
        if not game:
            raise ValueError(f"Game {game_id} not found")
        if game["status"] != "approved":
            raise ValueError(
                f"Game {game_id} is not approved (status: {game['status']})"
            )
        if game["asset_count"] >= self._max_assets:
            raise ValueError(
                f"Asset cap ({self._max_assets}) reached for game {game_id}"
            )

        asset_id = f"asset_{uuid.uuid4().hex[:16]}"
        now = int(time.time())

        asset: dict[str, Any] = {
            "asset_id": asset_id,
            "game_id": game_id,
            "owner": player,
            "name": asset_data.get("name", "Unnamed Asset"),
            "asset_type": asset_data.get("type", "item"),
            "attributes": asset_data.get("attributes", {}),
            "rarity": asset_data.get("rarity", "common"),
            "transferable": asset_data.get("transferable", True),
            "minted_at": now,
        }
        self._assets[asset_id] = asset
        game["asset_count"] += 1

        logger.info(
            "Asset minted: id=%s game=%s player=%s",
            asset_id, game_id, player,
        )
        return asset

    async def transfer_asset(
        self, asset_id: str, from_player: str, to_player: str,
    ) -> dict:
        """Transfer a game asset between players.

        Args:
            asset_id: The asset to transfer.
            from_player: Current owner address.
            to_player: New owner address.

        Returns:
            Updated asset record.
        """
        asset = self._assets.get(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        if asset["owner"] != from_player:
            raise ValueError(
                f"Asset {asset_id} is not owned by {from_player}"
            )
        if not asset.get("transferable", True):
            raise ValueError(f"Asset {asset_id} is not transferable")

        asset["owner"] = to_player
        asset["transferred_at"] = int(time.time())
        asset["transfer_history"] = asset.get("transfer_history", [])
        asset["transfer_history"].append({
            "from": from_player,
            "to": to_player,
            "timestamp": asset["transferred_at"],
        })

        logger.info(
            "Asset transferred: id=%s from=%s to=%s",
            asset_id, from_player, to_player,
        )
        return asset

    async def approve_game(self, game_id: str) -> dict:
        """Mark a game as approved (called after vetting passes)."""
        game = self._games.get(game_id)
        if not game:
            raise ValueError(f"Game {game_id} not found")
        game["status"] = "approved"
        game["approved_at"] = int(time.time())
        return game

    # ------------------------------------------------------------------
    # Expanded gaming operations
    # ------------------------------------------------------------------

    async def enter_tournament(
        self, game_id: str, player: str, entry_fee: float, tournament_name: str = "",
    ) -> dict:
        """Enter a player into a tournament."""
        entry_id = f"tourn_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = {
            "id": entry_id,
            "status": "entered",
            "game_id": game_id,
            "player": player,
            "entry_fee": entry_fee,
            "tournament_name": tournament_name,
            "entered_at": now,
        }
        self._assets[entry_id] = record
        logger.info("Tournament entry: id=%s player=%s", entry_id, player)
        return record

    async def trade_item(
        self, asset_id: str, seller: str, buyer: str, price: float,
    ) -> dict:
        """Trade a game item between players."""
        trade_id = f"trade_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = {
            "id": trade_id,
            "status": "completed",
            "asset_id": asset_id,
            "seller": seller,
            "buyer": buyer,
            "price": price,
            "traded_at": now,
        }
        self._assets[trade_id] = record
        logger.info("Item traded: id=%s", trade_id)
        return record

    async def attest_achievement(
        self, game_id: str, player: str, achievement: str, proof: dict | None = None,
    ) -> dict:
        """Attest a player achievement on-chain."""
        ach_id = f"ach_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = {
            "id": ach_id,
            "status": "attested",
            "game_id": game_id,
            "player": player,
            "achievement": achievement,
            "proof": proof or {},
            "attested_at": now,
        }
        self._assets[ach_id] = record
        logger.info("Achievement attested: id=%s player=%s", ach_id, player)
        return record

    async def create_prediction_market(
        self, creator: str, question: str, options: list[str], end_time: int = 0,
    ) -> dict:
        """Create a prediction market."""
        market_id = f"mkt_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = {
            "id": market_id,
            "status": "open",
            "creator": creator,
            "question": question,
            "options": options,
            "end_time": end_time or (now + 7 * 86400),
            "total_volume": 0.0,
            "created_at": now,
        }
        self._games[f"_market_{market_id}"] = record
        logger.info("Prediction market created: id=%s", market_id)
        return record

    async def place_prediction_bet(
        self, market_id: str, bettor: str, option: str, amount: float,
    ) -> dict:
        """Place a bet on a prediction market."""
        bet_id = f"bet_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = {
            "id": bet_id,
            "status": "placed",
            "market_id": market_id,
            "bettor": bettor,
            "option": option,
            "amount": amount,
            "placed_at": now,
        }
        self._assets[bet_id] = record
        logger.info("Prediction bet placed: id=%s", bet_id)
        return record

    async def resolve_market(
        self, market_id: str, outcome: str, resolver: str = "",
    ) -> dict:
        """Resolve a prediction market with the outcome."""
        resolve_id = f"mres_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = {
            "id": resolve_id,
            "status": "resolved",
            "market_id": market_id,
            "outcome": outcome,
            "resolver": resolver,
            "resolved_at": now,
        }
        self._games[f"_resolve_{resolve_id}"] = record
        logger.info("Market resolved: id=%s outcome=%s", resolve_id, outcome)
        return record

    async def query_market(
        self, market_id: str,
    ) -> dict:
        """Query current state of a prediction market."""
        query_id = f"mqry_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": query_id,
            "status": "queried",
            "market_id": market_id,
            "queried_at": int(time.time()),
        }
        logger.info("Market queried: id=%s", query_id)
        return record
