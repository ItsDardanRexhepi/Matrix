"""Web chat channel setup (always-on; just toggle)."""

from __future__ import annotations

import sys

from setup._shared import (
    header, info, load_config, save_config, success,
    update_channel, yes_no,
)


def configure(config: dict) -> dict:
    header("Web Chat Setup")
    info("The web chat UI at /chat is served by the gateway itself — no external credentials.")
    info("Notifications to the web chat appear in real time via Server-Sent Events.")
    enable = yes_no("Enable web chat notifications?", default=True)
    channel_cfg = {"enabled": enable}
    update_channel(config, "web_chat", channel_cfg)
    save_config(config)
    success("Web chat " + ("enabled." if enable else "disabled."))
    return channel_cfg


def main() -> int:
    return 0 if configure(load_config()) else 1


if __name__ == "__main__":
    sys.exit(main())
