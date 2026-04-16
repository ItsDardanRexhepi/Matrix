"""
0pnMatrx unified notification layer.

Drop-in multi-channel dispatcher that fans out a single message across
every enabled channel (Telegram, Discord, Slack, Email, SMS, WhatsApp,
Web chat, iOS push, and arbitrary webhooks). Config lives under the
``notifications`` subtree of ``openmatrix.config.json``.

    from runtime.notifications import NotificationDispatcher
    notifier = NotificationDispatcher(config)
    await notifier.broadcast("Trinity says hi", level="info")
"""

from __future__ import annotations

from runtime.notifications.base import (
    Channel,
    STATUS_OK,
    STATUS_ERROR,
    STATUS_NOT_CONFIGURED,
    STATUS_DISABLED,
)
from runtime.notifications.dispatcher import (
    NotificationDispatcher,
    CHANNEL_CLASSES,
)

__all__ = [
    "Channel",
    "NotificationDispatcher",
    "CHANNEL_CLASSES",
    "STATUS_OK",
    "STATUS_ERROR",
    "STATUS_NOT_CONFIGURED",
    "STATUS_DISABLED",
]
