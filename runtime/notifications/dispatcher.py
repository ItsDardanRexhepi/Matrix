"""
Notification dispatcher — fan-out to every enabled channel.

Reads the unified ``config["notifications"]`` subtree and forwards each
message to every channel that has `available` == True. Channels can be
disabled individually with ``enabled: false``. Always returns per-channel
results so callers can log success/failure per endpoint.

Backwards-compat:
    * Legacy ``config["communications"]`` is migrated into
      ``config["notifications"]`` once, at first instantiation.
    * Legacy ``config["social"]["discord"]["webhook_url"]`` is merged into
      ``config["notifications"]["discord"]["webhook_url"]`` if not set.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable

from runtime.notifications.base import Channel
from runtime.notifications.discord import DiscordChannel
from runtime.notifications.email_smtp import EmailChannel
from runtime.notifications.ios_push import iOSPushChannel
from runtime.notifications.slack import SlackChannel
from runtime.notifications.sms_twilio import SMSChannel
from runtime.notifications.telegram import TelegramChannel
from runtime.notifications.web_chat import WebChatChannel
from runtime.notifications.webhook import WebhookChannel
from runtime.notifications.whatsapp_twilio import WhatsAppChannel

logger = logging.getLogger(__name__)


# Ordered registry — the dispatcher instantiates each channel once.
CHANNEL_CLASSES: list[type[Channel]] = [
    TelegramChannel,
    DiscordChannel,
    SlackChannel,
    EmailChannel,
    SMSChannel,
    WhatsAppChannel,
    WebChatChannel,
    iOSPushChannel,
    WebhookChannel,
]


def _migrate_legacy_config(config: dict) -> None:
    """Merge legacy config keys into config["notifications"] in place."""
    notif = config.setdefault("notifications", {})

    # Legacy communications block from the old setup.py.
    legacy_comms = config.get("communications") or {}
    for k, v in legacy_comms.items():
        if k not in notif and isinstance(v, dict):
            notif[k] = v

    # Legacy discord webhook in config["social"]["discord"].
    soc_discord = (config.get("social") or {}).get("discord") or {}
    if soc_discord.get("webhook_url") and not notif.get("discord", {}).get("webhook_url"):
        notif.setdefault("discord", {}).update(soc_discord)


class NotificationDispatcher:
    """Fan-out message dispatcher across configured notification channels."""

    def __init__(self, config: dict) -> None:
        self._config = config
        _migrate_legacy_config(config)
        self._channels: dict[str, Channel] = {
            cls.name: cls(config) for cls in CHANNEL_CLASSES
        }

    # ── Introspection ────────────────────────────────────────────────────

    def list_channels(self) -> list[dict]:
        return [
            {"name": c.name, "enabled": c.enabled, "available": c.available}
            for c in self._channels.values()
        ]

    def list_enabled_channels(self) -> list[str]:
        return [name for name, c in self._channels.items() if c.enabled and c.available]

    def get(self, name: str) -> Channel | None:
        return self._channels.get(name)

    # ── Delivery ─────────────────────────────────────────────────────────

    async def broadcast(
        self,
        message: str,
        *,
        level: str = "info",
        channels: Iterable[str] | None = None,
        metadata: dict | None = None,
    ) -> dict[str, dict]:
        """Send to all enabled channels (or a subset).

        Returns `{channel_name: result_dict}`. Never raises — every channel
        returns a status dict even on failure.
        """
        targets: list[Channel] = []
        if channels is None:
            targets = [c for c in self._channels.values() if c.enabled and c.available]
        else:
            for name in channels:
                c = self._channels.get(name)
                if c is not None and c.enabled:
                    targets.append(c)

        if not targets:
            return {}

        results = await asyncio.gather(
            *(self._send_safe(c, message, level, metadata) for c in targets),
            return_exceptions=False,
        )
        return {c.name: r for c, r in zip(targets, results)}

    async def _send_safe(self, channel: Channel, message: str, level: str, metadata: dict | None) -> dict:
        try:
            return await channel.send(message, level=level, metadata=metadata)
        except Exception as exc:
            logger.warning("Channel %s raised: %s", channel.name, exc)
            return {"status": "error", "channel": channel.name, "error": str(exc)}

    async def test_channel(self, name: str) -> dict:
        """Send a canned test message to a single channel for setup verification."""
        c = self._channels.get(name)
        if c is None:
            return {"status": "error", "error": f"unknown channel: {name}"}
        return await c.send(
            "✅ 0pnMatrx test notification. If you see this, the channel is wired correctly.",
            level="success",
        )


__all__ = [
    "NotificationDispatcher",
    "CHANNEL_CLASSES",
]
