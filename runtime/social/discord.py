"""Discord integration for 0pnMatrx agents.

Posts agent content to Discord channels via webhook URLs.
No bot token required — uses simple webhook posting.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests as http_requests

logger = logging.getLogger(__name__)


class DiscordClient:
    """Posts content to Discord channels via webhooks.

    Uses Discord webhook URLs — no bot setup required. Each channel
    gets its own webhook URL configured in .env or config.
    """

    def __init__(self, config: dict | None = None):
        """Initialise with optional config.

        Reads webhook URLs from config or environment:
            DISCORD_WEBHOOK_URL — default channel webhook
            DISCORD_ANNOUNCEMENTS_WEBHOOK — announcements channel
        """
        config = config or {}
        social_cfg = config.get("social", {}).get("discord", {})

        self.default_webhook = (
            social_cfg.get("webhook_url")
            or os.environ.get("DISCORD_WEBHOOK_URL", "")
        )
        self.announcements_webhook = (
            social_cfg.get("announcements_webhook")
            or os.environ.get("DISCORD_ANNOUNCEMENTS_WEBHOOK", "")
        )

        self.available = bool(
            self.default_webhook
            and not self.default_webhook.startswith("YOUR_")
        )

    async def post_message(
        self,
        content: str,
        channel: str = "default",
        username: str = "Trinity",
        avatar_url: str | None = None,
        embed: dict | None = None,
    ) -> dict:
        """Post a message to a Discord channel via webhook.

        Parameters
        ----------
        content : str
            Message text (max 2000 characters).
        channel : str
            Channel name: ``default`` or ``announcements``.
        username : str
            Display name for the webhook message.
        avatar_url : str, optional
            Avatar URL for the webhook message.
        embed : dict, optional
            Discord embed object for rich content.

        Returns
        -------
        dict
            Result with message details on success.
        """
        if not self.available:
            return {"status": "not_configured", "message": "Discord webhook not set."}

        webhook_url = self.default_webhook
        if channel == "announcements" and self.announcements_webhook:
            webhook_url = self.announcements_webhook

        try:
            payload: dict[str, Any] = {
                "content": content[:2000],
                "username": username,
            }
            if avatar_url:
                payload["avatar_url"] = avatar_url
            if embed:
                payload["embeds"] = [embed]

            resp = http_requests.post(webhook_url, json=payload, timeout=30)

            if resp.status_code in (200, 204):
                return {
                    "status": "ok",
                    "channel": channel,
                    "message": content[:100],
                }
            else:
                logger.error("Discord post failed (%d): %s", resp.status_code, resp.text)
                return {"status": "error", "message": resp.text}

        except Exception as exc:
            logger.error("Discord post exception: %s", exc)
            return {"status": "error", "message": str(exc)}

    async def post_embed(
        self,
        title: str,
        description: str,
        color: int = 0x00FF41,
        fields: list[dict] | None = None,
        channel: str = "default",
    ) -> dict:
        """Post a rich embed to Discord.

        Parameters
        ----------
        title : str
            Embed title.
        description : str
            Embed description.
        color : int
            Embed colour (default: matrix green).
        fields : list[dict], optional
            Embed fields: ``[{"name": "...", "value": "...", "inline": True}]``.
        channel : str
            Target channel.
        """
        embed: dict[str, Any] = {
            "title": title,
            "description": description[:4096],
            "color": color,
        }
        if fields:
            embed["fields"] = fields[:25]

        return await self.post_message(
            content="",
            channel=channel,
            embed=embed,
        )
