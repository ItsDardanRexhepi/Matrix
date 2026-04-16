"""Telegram notification channel (bot_token + chat_id)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from runtime.notifications.base import Channel

logger = logging.getLogger(__name__)


def _placeholder(v: str) -> bool:
    if not v:
        return True
    return v.startswith(("YOUR_", "CHANGE_")) or v == "..."


class TelegramChannel(Channel):
    name = "telegram"

    @property
    def available(self) -> bool:
        cfg = self._channel_config
        token = str(cfg.get("bot_token", "") or "")
        chat_id = str(cfg.get("chat_id", cfg.get("owner_id", "")) or "")
        return bool(token) and bool(chat_id) and not _placeholder(token)

    async def send(
        self,
        message: str,
        *,
        level: str = "info",
        metadata: dict | None = None,
    ) -> dict:
        if not self.available:
            return self._not_configured("missing bot_token or chat_id")
        cfg = self._channel_config
        token = cfg["bot_token"]
        chat_id = cfg.get("chat_id") or cfg.get("owner_id")
        try:
            import aiohttp
        except ImportError:
            return self._error("aiohttp not installed")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        prefix = {"error": "🚨", "warn": "⚠️", "info": "ℹ️", "success": "✅"}.get(level, "")
        text = f"{prefix} {message}".strip()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        return self._ok(message_id=data.get("result", {}).get("message_id"))
                    return self._error(data.get("description", "telegram rejected"))
        except Exception as exc:
            return self._error(str(exc))
