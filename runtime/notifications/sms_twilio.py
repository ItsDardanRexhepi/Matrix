"""SMS notification channel via Twilio REST API."""

from __future__ import annotations

import base64

from runtime.notifications.base import Channel


class SMSChannel(Channel):
    name = "sms"

    @property
    def available(self) -> bool:
        cfg = self._channel_config
        return all(cfg.get(k) for k in ("account_sid", "auth_token", "from_number", "to_number"))

    async def send(self, message: str, *, level: str = "info", metadata: dict | None = None) -> dict:
        if not self.available:
            return self._not_configured("missing Twilio credentials or phone numbers")
        try:
            import aiohttp
        except ImportError:
            return self._error("aiohttp not installed")
        cfg = self._channel_config
        sid = cfg["account_sid"]
        token = cfg["auth_token"]
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
        data = {"From": cfg["from_number"], "To": cfg["to_number"], "Body": message[:1600]}
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
