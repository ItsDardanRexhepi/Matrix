"""Slack incoming webhook setup."""

from __future__ import annotations

import sys

from setup._shared import (
    ask, error, header, load_config, save_config, success,
    test_channel_via_dispatcher, update_channel, update_env, warn,
)


def configure(config: dict) -> dict:
    header("Slack Setup")
    existing = config.get("notifications", {}).get("slack", {})
    url = ask(
        "Slack webhook URL (Apps → Incoming Webhooks → New webhook)",
        default=existing.get("webhook_url", ""),
    )
    if not url:
        warn("Skipping Slack.")
        return {}
    if not url.startswith("https://hooks.slack.com/"):
        error("Invalid URL. Slack webhook URLs start with https://hooks.slack.com/")
        return {}
    channel_cfg = {"webhook_url": url}
    update_channel(config, "slack", channel_cfg)
    save_config(config)
    update_env({"SLACK_WEBHOOK_URL": url})
    result = test_channel_via_dispatcher(config, "slack")
    if result.get("status") == "ok":
        success("Slack saved and test message delivered.")
    else:
        warn(f"Slack saved but test failed: {result.get('error', '')}")
    return channel_cfg


def main() -> int:
    return 0 if configure(load_config()) else 1


if __name__ == "__main__":
    sys.exit(main())
