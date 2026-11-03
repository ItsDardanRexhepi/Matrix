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
    """The one channel that needs no external credentials: it IS the gateway.

    Not "always available", which is what this line used to say. The channel
    publishes into the gateway's live ``EventBroadcaster``, and it can only do
    that once the gateway has handed it one — so ``available`` is False in any
    process that has not built a gateway (a CLI run of the dispatcher, a test,
    a worker). What is true is the part that matters to an operator filling in
    a config: there is nothing here for them to fill in.
    """

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
        """True once the gateway has attached its broadcaster and nobody has
        switched the channel off. No credential is consulted, because there is
        none: the subscriber on the other end is the gateway's own SSE feed."""
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
