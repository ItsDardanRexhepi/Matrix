"""Generic webhook setup."""

from __future__ import annotations

import sys

from setup._shared import (
    ask, error, header, load_config, save_config, success,
    test_channel_via_dispatcher, update_channel, update_env, warn,
)


def configure(config: dict) -> dict:
    header("Generic Webhook Setup")
    existing = config.get("notifications", {}).get("webhook", {})
    url = ask("Webhook URL (POST endpoint that accepts JSON)",
              default=existing.get("url", ""))
    if not url:
        warn("Skipping webhook.")
        return {}
    if not url.startswith(("http://", "https://")):
        error("Invalid URL.")
        return {}
    bearer = ask("Optional Bearer token (leave blank for no auth)",
                  default=existing.get("bearer_token", ""))
    channel_cfg = {"url": url, "bearer_token": bearer}
    update_channel(config, "webhook", channel_cfg)
    save_config(config)
    update_env({"NOTIFY_WEBHOOK_URL": url})
    result = test_channel_via_dispatcher(config, "webhook")
    if result.get("status") == "ok":
        success("Webhook saved and test delivered.")
    else:
        warn(f"Webhook saved but test failed: {result.get('error', '')}")
    return channel_cfg


def main() -> int:
    return 0 if configure(load_config()) else 1


if __name__ == "__main__":
    sys.exit(main())
