"""
GameSDK — helper methods for game developers on the 0pnMatrx platform.

Provides convenience functions for item types, achievements,
leaderboards, and match recording.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class GameSDK:
    """Developer SDK for building games on 0pnMatrx.

    Config keys (under ``config["gaming"]``):
        leaderboard_max_entries (int): Max leaderboard size (default 1000).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        g_cfg = config.get("gaming", {})
        self._lb_max: int = int(g_cfg.get("leaderboard_max_entries", 1_000))

        # game_id -> list of item types
        self._item_types: dict[str, list[dict[str, Any]]] = {}
        # game_id -> player -> list of achievements
        self._achievements: dict[str, dict[str, list[dict[str, Any]]]] = {}
        # game_id -> metric -> sorted list of (score, player, timestamp)
        self._leaderboards: dict[str, dict[str, list[dict[str, Any]]]] = {}
        # game_id -> list of match records
        self._matches: dict[str, list[dict[str, Any]]] = {}

    async def create_item_type(
        self, game_id: str, item_type: dict,
    ) -> dict:
        """Define a new item type for a game.

        Args:
            game_id: The game this item type belongs to.
            item_type: Dict with ``name``, ``category``, ``max_supply``,
                       ``tradeable``, and ``attributes_schema``.

        Returns:
            Created item type record.
        """
        if not item_type.get("name"):
            raise ValueError("item_type.name is required")

        type_id = f"itype_{uuid.uuid4().hex[:12]}"
        now = int(time.time())

        record: dict[str, Any] = {
            "type_id": type_id,
            "game_id": game_id,
            "name": item_type["name"],
            "category": item_type.get("category", "general"),
            "max_supply": int(item_type.get("max_supply", 0)),  # 0 = unlimited
            "tradeable": bool(item_type.get("tradeable", True)),
            "attributes_schema": item_type.get("attributes_schema", {}),
            "minted_count": 0,
            "created_at": now,
        }

        self._item_types.setdefault(game_id, []).append(record)

        logger.info(
            "Item type created: id=%s game=%s name=%s",
            type_id, game_id, record["name"],
        )
        return record

    async def award_achievement(
        self, game_id: str, player: str, achievement: dict,
    ) -> dict:
        """Award an achievement to a player.

        Args:
            game_id: The game context.
            player: Player address.
            achievement: Dict with ``name``, ``description``, ``points``,
                         and optional ``icon_url``.

        Returns:
            Achievement record.
        """
        if not achievement.get("name"):
            raise ValueError("achievement.name is required")

        achievement_id = f"ach_{uuid.uuid4().hex[:12]}"
        now = int(time.time())

        record: dict[str, Any] = {
            "achievement_id": achievement_id,
            "game_id": game_id,
            "player": player,
            "name": achievement["name"],
            "description": achievement.get("description", ""),
            "points": int(achievement.get("points", 0)),
            "icon_url": achievement.get("icon_url", ""),
            "awarded_at": now,
        }

        game_achs = self._achievements.setdefault(game_id, {})
        game_achs.setdefault(player, []).append(record)

        # Update leaderboard for achievement points
        await self._update_leaderboard(
            game_id, "achievement_points", player, record["points"],
        )

        logger.info(
            "Achievement awarded: id=%s game=%s player=%s name=%s",
            achievement_id, game_id, player, record["name"],
        )
        return record

    async def get_leaderboard(
        self, game_id: str, metric: str, limit: int = 100,
    ) -> list:
        """Get the leaderboard for a game metric.

        Args:
            game_id: The game.
            metric: Leaderboard metric (e.g. "score", "wins",
                    "achievement_points").
            limit: Max entries to return (default 100).

        Returns:
            Sorted list of leaderboard entries (descending by value).
        """
        lb = self._leaderboards.get(game_id, {}).get(metric, [])
        # Sort descending by value
        sorted_lb = sorted(lb, key=lambda e: e["value"], reverse=True)
        return sorted_lb[:limit]

    async def record_match(
        self, game_id: str, match_data: dict,
    ) -> dict:
        """Record a completed match.

        Args:
            game_id: The game.
            match_data: Dict with ``players`` (list of addresses),
                        ``winner`` (address or None for draw),
                        ``scores`` (dict player -> score),
                        ``duration_seconds``, ``mode``.

        Returns:
            Match record.
        """
        match_id = f"match_{uuid.uuid4().hex[:12]}"
        now = int(time.time())

        players = match_data.get("players", [])
        winner = match_data.get("winner")
        scores = match_data.get("scores", {})

        record: dict[str, Any] = {
            "match_id": match_id,
            "game_id": game_id,
            "players": players,
            "winner": winner,
            "scores": scores,
            "duration_seconds": int(match_data.get("duration_seconds", 0)),
            "mode": match_data.get("mode", "standard"),
            "metadata": match_data.get("metadata", {}),
            "recorded_at": now,
        }
        self._matches.setdefault(game_id, []).append(record)

        # Update leaderboards for scores and wins
        for player, score in scores.items():
            await self._update_leaderboard(
                game_id, "score", player, float(score),
            )

        if winner:
            await self._update_leaderboard(game_id, "wins", winner, 1)

        logger.info(
            "Match recorded: id=%s game=%s players=%d winner=%s",
            match_id, game_id, len(players), winner or "draw",
        )
        return record

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _update_leaderboard(
        self,
        game_id: str,
        metric: str,
        player: str,
        value: float,
    ) -> None:
        """Add value to a player's leaderboard score."""
        game_lbs = self._leaderboards.setdefault(game_id, {})
        lb = game_lbs.setdefault(metric, [])

        # Find existing entry
        for entry in lb:
            if entry["player"] == player:
                entry["value"] += value
                entry["updated_at"] = int(time.time())
                return

        # New entry
        lb.append({
            "player": player,
            "value": value,
            "updated_at": int(time.time()),
        })

        # Trim to max
        if len(lb) > self._lb_max:
            lb.sort(key=lambda e: e["value"], reverse=True)
            game_lbs[metric] = lb[: self._lb_max]
