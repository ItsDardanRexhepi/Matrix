"""`Channel.available` says "present AND valid". Every override checked presence.

`runtime/notifications/base.py` states the rule twice — the module docstring's
design rules say "`available` is True iff credentials are present AND
non-placeholder", and the property's own docstring says "Return True only if
required credentials are present and valid".

Only `telegram` implemented it. The other seven adapters answer
`all(cfg.get(k) for k in (...))`, which is a truthiness test: a config still
carrying `"auth_key_p8": "YOUR_APNS_KEY_P8"` — the literal value the shipped
example writes — reports the channel as AVAILABLE. That matters because
`available` is what the notification dispatcher and `gateway.doctor` both read
to decide whether a channel will work, so a half-filled config is reported as
ready and the first real send is where it comes apart.

The dispatcher would also crash before reaching any of it: `Channel.__init__`
reads `config.get("notifications", {}).get(self.name, {})`, and a config with
`"notifications": null` makes the second `.get` an AttributeError — the same
shape already fixed in the monitoring bridges, in a constructor every channel
inherits.
"""

from __future__ import annotations

import pytest

from runtime.notifications.discord import DiscordChannel
from runtime.notifications.email_smtp import EmailChannel
from runtime.notifications.ios_push import iOSPushChannel
from runtime.notifications.slack import SlackChannel
from runtime.notifications.sms_twilio import SMSChannel
from runtime.notifications.telegram import TelegramChannel
from runtime.notifications.web_chat import WebChatChannel
from runtime.notifications.webhook import WebhookChannel
from runtime.notifications.whatsapp_twilio import WhatsAppChannel

# (channel class, a config block that is filled but placeholder, a real one)
CASES = [
    (iOSPushChannel, "ios_push",
     {"auth_key_p8": "YOUR_APNS_KEY_P8", "key_id": "YOUR_KEY_ID",
      "team_id": "YOUR_TEAM_ID", "bundle_id": "com.example.app"},
     {"auth_key_p8": "-----BEGIN PRIVATE KEY-----", "key_id": "ABC123",
      "team_id": "TEAM99", "bundle_id": "com.example.app"}),
    (EmailChannel, "email",
     {"smtp_host": "smtp.example.com", "smtp_user": "YOUR_SMTP_USER",
      "smtp_pass": "YOUR_SMTP_PASSWORD", "to": "ops@example.com"},
     {"smtp_host": "smtp.example.com", "smtp_user": "ops",
      "smtp_pass": "hunter2", "to": "ops@example.com"}),
    (SMSChannel, "sms",
     {"account_sid": "YOUR_TWILIO_SID", "auth_token": "YOUR_TWILIO_TOKEN",
      "from_number": "+1000", "to_number": "+1001"},
     {"account_sid": "AC123", "auth_token": "tok",
      "from_number": "+1000", "to_number": "+1001"}),
    (WhatsAppChannel, "whatsapp",
     {"account_sid": "CHANGE_ME", "auth_token": "CHANGE_ME",
      "from_number": "+1000", "to_number": "+1001"},
     {"account_sid": "AC123", "auth_token": "tok",
      "from_number": "+1000", "to_number": "+1001"}),
    (TelegramChannel, "telegram",
     {"bot_token": "YOUR_BOT_TOKEN", "chat_id": "123"},
     {"bot_token": "55:AAH", "chat_id": "123"}),
]


@pytest.mark.parametrize("cls,name,placeholder,real", CASES,
                         ids=[c[1] for c in CASES])
def test_a_placeholder_credential_is_not_available(cls, name, placeholder, real):
    chan = cls({"notifications": {cls.name: placeholder}})
    assert chan.available is False, (
        f"{cls.name} reported itself available on placeholder credentials: "
        f"{placeholder}")


@pytest.mark.parametrize("cls,name,placeholder,real", CASES,
                         ids=[c[1] for c in CASES])
def test_a_real_credential_is_still_available(cls, name, placeholder, real):
    # The guard must not turn into "nothing is ever available".
    assert cls({"notifications": {cls.name: real}}).available is True


# URL-shaped channels have their own shape of the same hole.

@pytest.mark.parametrize("cls,key", [
    (DiscordChannel, "webhook_url"),
    (SlackChannel, "webhook_url"),
    (WebhookChannel, "url"),
])
def test_a_placeholder_url_is_not_available(cls, key):
    chan = cls({"notifications": {cls.name: {key: "https://YOUR_WEBHOOK_URL"}}})
    assert chan.available is False


def test_a_real_slack_url_is_still_available():
    assert SlackChannel({"notifications": {"slack": {
        "webhook_url": "https://hooks.slack.com/services/T/B/x"}}}).available is True


# ── the constructor every channel inherits ──────────────────────────────────

ALL_CHANNELS = [c[0] for c in CASES] + [
    DiscordChannel, SlackChannel, WebhookChannel, WebChatChannel]


@pytest.mark.parametrize("cls", ALL_CHANNELS, ids=[c.name for c in ALL_CHANNELS])
def test_a_null_notifications_block_does_not_raise(cls):
    assert cls({"notifications": None}).available in (True, False)


@pytest.mark.parametrize("cls", ALL_CHANNELS, ids=[c.name for c in ALL_CHANNELS])
def test_a_null_channel_block_does_not_raise(cls):
    assert cls({"notifications": {cls.name: None}}).available in (True, False)


# ── the one channel that claims it needs no credentials at all ──────────────
#
# `WebChatChannel` called itself "Always-available: the web UI is part of the
# gateway itself." It is available only once a broadcaster has been attached to
# the class, and the only attach site sat inside the `try:` that registers the
# 44-service route table — so any failure in `ServiceRoutes(...)` or
# `register_routes(...)` left the gateway with no broadcaster at all, and the
# channel the gateway owns end to end permanently unavailable.


def test_web_chat_is_wired_even_when_service_route_registration_fails(monkeypatch):
    import sys

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    from gateway.server import GatewayServer
    import gateway.service_routes as service_routes

    monkeypatch.setattr(WebChatChannel, "_broadcaster", None)

    def _boom(self, app):
        raise RuntimeError("route table blew up")

    monkeypatch.setattr(service_routes.ServiceRoutes, "register_routes", _boom)

    server = GatewayServer(SWEEP_CONFIG)
    server.create_app()

    assert server.event_broadcaster is not None, (
        "the gateway lost its own event broadcaster because a service-route "
        "registration failure took it with it")
    assert WebChatChannel({}).available is True, (
        "the in-gateway chat channel reported itself unavailable because an "
        "unrelated subsystem failed to register")


def test_web_chat_is_wired_on_the_ordinary_path():
    import sys

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    from gateway.server import GatewayServer

    server = GatewayServer(SWEEP_CONFIG)
    server.create_app()
    assert server.event_broadcaster is not None
    assert WebChatChannel({}).available is True
