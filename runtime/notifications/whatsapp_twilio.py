"""WhatsApp notification channel via Twilio WhatsApp sandbox/Business API."""

from __future__ import annotations

import base64

from runtime.notifications.base import Channel


class WhatsAppChannel(Channel):
    name = "whatsapp"

    @property
    def available(self) -> bool:
        cfg = self._channel_config
        return all(cfg.get(k) for k in ("account_sid", "auth_token", "from_number", "to_number"))

    async def send(self, message: str, *, level: str = "info", metadata: dict | None = None) -> dict:
        if not self.available:
            return self._not_configured("missing Twilio WhatsApp credentials")
        try:
            import aiohttp
        except ImportError:
            return self._error("aiohttp not installed")
        cfg = self._channel_config
        sid = cfg["account_sid"]
        token = cfg["auth_token"]
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        auth = base64.b64encode(f"{sid}:{token}".encode()).decode()

        def _wa(num: str) -> str:
            return num if num.startswith("whatsapp:") else f"whatsapp:{num}"

        data = {"From": _wa(cfg["from_number"]), "To": _wa(cfg["to_number"]), "Body": message[:1600]}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    data=data,
                    headers={"Authorization": f"Basic {auth}"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    js = await resp.json()
                    if 200 <= resp.status < 300:
                        return self._ok(message_id=js.get("sid"))
                    return self._error(js.get("message", f"HTTP {resp.status}"))
        except Exception as exc:
            return self._error(str(exc))
