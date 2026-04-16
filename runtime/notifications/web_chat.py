"""
Web chat notification channel.

Posts messages into the gateway's live EventBroadcaster feed (Server-Sent
Events). The browser chat UI at ``/chat`` subscribes to
``/api/v1/events/stream`` and receives notifications in real time without
any external credentials.
"""

from __future__ import annotations

from runtime.notifications.base import Channel


class WebChatChannel(Channel):
    """Always-available: the web UI is part of the gateway itself."""

    name = "web_chat"

    #: The global EventBroadcaster instance is attached by GatewayServer at
    #: startup via set_broadcaster(). The Channel subclass has no reliable
    #: way to reach the gateway instance directly, so the broadcaster is
    #: registered as a class-level attribute.
    _broadcaster = None

    @classmethod
    def set_broadcaster(cls, broadcaster) -> None:
        cls._broadcaster = broadcaster

    @property
    def available(self) -> bool:
        # If the broadcaster was attached and the channel isn't explicitly
        # disabled, it is available.
        return WebChatChannel._broadcaster is not None and (
            self._channel_config.get("enabled", True) is not False
        )

    async def send(self, message: str, *, level: str = "info", metadata: dict | None = None) -> dict:
        if not self.available:
            return self._not_configured("broadcaster not attached")
        try:
            from gateway.event_broadcaster import BroadcastEvent
            event = BroadcastEvent(
                event_type="notification",
                data={"message": message, "level": level, "metadata": metadata or {}},
            )
            await WebChatChannel._broadcaster.publish(event)
            return self._ok()
        except Exception as exc:
            return self._error(str(exc))
