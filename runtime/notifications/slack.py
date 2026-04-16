"""Slack notification channel (incoming webhook URL)."""

from __future__ import annotations

from runtime.notifications.base import Channel


class SlackChannel(Channel):
    name = "slack"

    @property
    def available(self) -> bool:
        url = str(self._channel_config.get("webhook_url", "") or "")
        return bool(url) and url.startswith("https://hooks.slack.com/")

    async def send(self, message: str, *, level: str = "info", metadata: dict | None = None) -> dict:
        if not self.available:
            return self._not_configured("missing Slack webhook_url")
        try:
            import aiohttp
        except ImportError:
            return self._error("aiohttp not installed")
        url = self._channel_config["webhook_url"]
        emoji = {"error": ":rotating_light:", "warn": ":warning:", "info": ":information_source:", "success": ":white_check_mark:"}.get(level, "")
        text = f"{emoji} {message}".strip()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json={"text": text}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if 200 <= resp.status < 300:
                        return self._ok()
                    return self._error(f"HTTP {resp.status}")
        except Exception as exc:
            return self._error(str(exc))
