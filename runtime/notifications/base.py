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

#: Prefixes and exact values the shipped example config and the setup wizard
#: write into a credential slot that has not been filled in yet.
_PLACEHOLDER_PREFIXES = ("YOUR_", "CHANGE_", "REPLACE_", "<")
_PLACEHOLDER_EXACT = {"...", "changeme", "todo", "xxx", "placeholder"}


def is_placeholder(value: Any) -> bool:
    """True when *value* is empty or is a slot nobody has filled in.

    The design rule at the top of this module has always said `available` is
    True "iff credentials are present AND non-placeholder". Only the Telegram
    adapter implemented the second half; the rest asked `all(cfg.get(k) ...)`,
    which is a truthiness test, so a config still carrying
    ``"auth_key_p8": "YOUR_APNS_KEY_P8"`` reported the channel as ready. That
    answer is what the dispatcher and `gateway.doctor` both read, so a
    half-filled config looked configured right up until the first real send.
    """
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    if text.lower() in _PLACEHOLDER_EXACT:
        return True
    upper = text.upper()
    if any(upper.startswith(p) for p in _PLACEHOLDER_PREFIXES):
        return True
    # A URL whose host is still a placeholder: https://YOUR_WEBHOOK_URL
    return any(f"/{p}" in upper or f"//{p}" in upper
               for p in ("YOUR_", "CHANGE_", "REPLACE_"))


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
        # `.get("notifications", {})` applies its default only to a MISSING
        # key, so `"notifications": null` used to make the next `.get` an
        # AttributeError — out of a constructor every channel inherits, before
        # any adapter code runs.
        self._channel_config: dict[str, Any] = self._subtree(config)

    @classmethod
    def _subtree(cls, config: Any) -> dict[str, Any]:
        block = config.get("notifications") if isinstance(config, dict) else None
        block = block if isinstance(block, dict) else {}
        channel = block.get(cls.name)
        return channel if isinstance(channel, dict) else {}

    def _filled(self, *keys: str) -> bool:
        """True when every named credential is present and is not a placeholder.

        The check the design rule at the top of this module describes, in one
        place, so an adapter cannot implement half of it by accident.
        """
        cfg = self._channel_config
        return all(not is_placeholder(cfg.get(k)) for k in keys)

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
