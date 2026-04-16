"""Generic webhook notification channel."""

from __future__ import annotations

import json

from runtime.notifications.base import Channel


class WebhookChannel(Channel):
    name = "webhook"

    @property
    def available(self) -> bool:
        url = str(self._channel_config.get("url", "") or "")
        return bool(url) and url.startswith(("http://", "https://"))

    async def send(self, message: str, *, level: str = "info", metadata: dict | None = None) -> dict:
        if not self.available:
            return self._not_configured("missing webhook url")
        try:
            import aiohttp
        except ImportError:
            return self._error("aiohttp not installed")
        cfg = self._channel_config
        payload = {"message": message, "level": level, "metadata": metadata or {}}
        headers = cfg.get("headers", {})
        if cfg.get("bearer_token"):
            headers.setdefault("Authorization", f"Bearer {cfg['bearer_token']}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    cfg["url"],
                    data=json.dumps(payload),
                    headers={"Content-Type": "application/json", **headers},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if 200 <= resp.status < 300:
                        return self._ok()
                    return self._error(f"HTTP {resp.status}")
        except Exception as exc:
            return self._error(str(exc))
