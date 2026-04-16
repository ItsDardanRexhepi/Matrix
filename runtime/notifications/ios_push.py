"""
iOS push notification channel via Apple Push Notification service (APNs).

Requires an APNs auth key (.p8), key_id, team_id, and bundle_id. Device
tokens are registered by the MTRX iOS app at runtime (stored per-session
in the bridge; not on this channel). The platform operator provides the
APNs key; device tokens come from the app.

This adapter is intentionally kept offline-safe: if ``aioapns`` (or
``httpx``) isn't installed or the key isn't configured, ``available``
returns False and ``send()`` returns a not_configured status.
"""

from __future__ import annotations

import json
import time

from runtime.notifications.base import Channel


class iOSPushChannel(Channel):
    name = "ios_push"

    @property
    def available(self) -> bool:
        cfg = self._channel_config
        return all(cfg.get(k) for k in ("auth_key_p8", "key_id", "team_id", "bundle_id"))

    async def send(self, message: str, *, level: str = "info", metadata: dict | None = None) -> dict:
        if not self.available:
            return self._not_configured("missing APNs auth key, key_id, team_id, or bundle_id")
        cfg = self._channel_config
        device_tokens = cfg.get("device_tokens") or (metadata or {}).get("device_tokens") or []
        if not device_tokens:
            return self._not_configured("no device_tokens registered for push")

        try:
            import jwt  # PyJWT
            import aiohttp
        except ImportError:
            return self._error("PyJWT + aiohttp are required for APNs push")

        now = int(time.time())
        token = jwt.encode(
            {"iss": cfg["team_id"], "iat": now},
            cfg["auth_key_p8"],
            algorithm="ES256",
            headers={"kid": cfg["key_id"], "alg": "ES256"},
        )
        payload = {
            "aps": {
                "alert": {"title": "0pnMatrx", "body": message},
                "sound": "default",
            },
            "level": level,
            **(metadata or {}),
        }
        endpoint_host = "api.sandbox.push.apple.com" if cfg.get("sandbox") else "api.push.apple.com"
        url_base = f"https://{endpoint_host}/3/device"
        headers = {
            "authorization": f"bearer {token}",
            "apns-topic": cfg["bundle_id"],
            "apns-push-type": "alert",
            "apns-priority": "10",
        }
        results: list[dict] = []
        try:
            async with aiohttp.ClientSession() as session:
                for dev_tok in device_tokens:
                    async with session.post(
                        f"{url_base}/{dev_tok}",
                        data=json.dumps(payload),
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if 200 <= resp.status < 300:
                            results.append({"device": dev_tok, "status": "ok"})
                        else:
                            text = await resp.text()
                            results.append({"device": dev_tok, "status": "error", "error": text})
            return self._ok(results=results)
        except Exception as exc:
            return self._error(str(exc))
