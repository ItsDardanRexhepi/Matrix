"""Discord notification channel (incoming webhook URL)."""

from __future__ import annotations

import logging

from runtime.notifications.base import Channel

logger = logging.getLogger(__name__)


class DiscordChannel(Channel):
    name = "discord"

    @property
    def available(self) -> bool:
        url = str(self._channel_config.get("webhook_url", "") or "")
        return bool(url) and url.startswith("https://")

    async def send(self, message: str, *, level: str = "info", metadata: dict | None = None) -> dict:
        if not self.available:
            return self._not_configured("missing webhook_url")
        try:
            import aiohttp
        except ImportError:
            return self._error("aiohttp not installed")
        url = self._channel_config["webhook_url"]
        color = {"error": 0xE53935, "warn": 0xFB8C00, "info": 0x1E88E5, "success": 0x43A047}.get(level, 0x607D8B)
        payload = {
            "embeds": [{"description": message, "color": color}],
            "username": self._channel_config.get("username", "0pnMatrx"),
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if 200 <= resp.status < 300:
                        return self._ok()
                    return self._error(f"HTTP {resp.status}")
        except Exception as exc:
            return self._error(str(exc))
