"""Discord webhook setup."""

from __future__ import annotations

import sys

from setup._shared import (
    ask, error, header, load_config, save_config, success,
    test_channel_via_dispatcher, update_channel, update_env, warn,
)


def configure(config: dict) -> dict:
    header("Discord Setup")
    existing = config.get("notifications", {}).get("discord", {})
    url = ask("Discord webhook URL (Server Settings → Integrations → Webhooks)",
              default=existing.get("webhook_url", ""))
    if not url:
        warn("Skipping Discord.")
        return {}
    if not url.startswith("https://"):
        error("Invalid URL (must be https://)")
        return {}
    username = ask("Bot username shown in Discord", default=existing.get("username", "0pnMatrx"))
    channel_cfg = {"webhook_url": url, "username": username}
    update_channel(config, "discord", channel_cfg)
    save_config(config)
    update_env({"DISCORD_WEBHOOK_URL": url})
    result = test_channel_via_dispatcher(config, "discord")
    if result.get("status") == "ok":
        success("Discord saved and test message delivered.")
    else:
        warn(f"Discord saved but test failed: {result.get('error', '')}")
    return channel_cfg


def main() -> int:
    return 0 if configure(load_config()) else 1


if __name__ == "__main__":
    sys.exit(main())
