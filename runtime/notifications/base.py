"""
Notification channel base class.

Every channel adapter (Telegram, Discord, Slack, SMS, Email, WhatsApp,
Web chat, iOS push, Webhook) implements this minimal interface. Adapters
read their credentials from a per-channel subtree of
``config["notifications"][<channel_name>]`` and expose a single
``send(message, level, metadata)`` coroutine.

Design rules:
    * `available` is True iff credentials are present AND non-placeholder.
    * `send()` never raises on transport errors — returns a status dict.
    * Adapters are cheap to instantiate; the dispatcher may recreate them.
"""

from __future__ import annotations

from typing import Any


# Status strings that every adapter uses consistently.
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_DISABLED = "disabled"


class Channel:
    """Abstract notification channel."""

    #: Identifier used in config dict. Subclasses MUST override.
    name: str = ""

    def __init__(self, config: dict) -> None:
        self._config = config
        self._channel_config: dict[str, Any] = (
            config.get("notifications", {}).get(self.name, {})
        )

    @property
    def enabled(self) -> bool:
        """Whether this channel is enabled in config."""
        val = self._channel_config.get("enabled")
        # If "enabled" omitted but credentials present, consider it on.
        if val is None:
            return self.available
        return bool(val)

    @property
    def available(self) -> bool:
        """Return True only if required credentials are present and valid.

        Subclasses override with channel-specific checks.
        """
        return False

    async def send(
        self,
        message: str,
        *,
        level: str = "info",
        metadata: dict | None = None,
    ) -> dict:
        """Send *message* via this channel.

        Returns a dict with at least::

            {"status": "ok" | "error" | "not_configured" | "disabled",
             "channel": self.name,
             "message_id": <optional provider id>,
             "error": <optional error text>}
        """
        raise NotImplementedError

    # ── Helpers ──────────────────────────────────────────────────────────

    def _not_configured(self, reason: str = "") -> dict:
        out = {"status": STATUS_NOT_CONFIGURED, "channel": self.name}
        if reason:
            out["reason"] = reason
        return out

    def _error(self, reason: str) -> dict:
        return {"status": STATUS_ERROR, "channel": self.name, "error": reason}

    def _ok(self, **extra: Any) -> dict:
        return {"status": STATUS_OK, "channel": self.name, **extra}
