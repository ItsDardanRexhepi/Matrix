"""iOS push notification setup (APNs)."""

from __future__ import annotations

import sys
from pathlib import Path

from setup._shared import (
    ask, error, header, info, load_config, save_config, success,
    update_channel, update_env, warn, yes_no,
)


def configure(config: dict) -> dict:
    header("iOS Push (APNs) Setup")
    info("You need: APNs .p8 auth key, Key ID, Team ID, and your app's Bundle ID.")
    info("Generate these at developer.apple.com → Certificates, Identifiers & Profiles → Keys.")
    existing = config.get("notifications", {}).get("ios_push", {})

    p8_path = ask("Path to .p8 auth key file", default=existing.get("auth_key_path", ""))
    if not p8_path:
        warn("Skipping iOS push.")
        return {}
    p8 = Path(p8_path).expanduser()
    if not p8.exists():
        error(f"File not found: {p8}")
        return {}
    auth_key = p8.read_text(encoding="utf-8")

    key_id = ask("Key ID (10 char alphanumeric)", default=existing.get("key_id", ""))
    team_id = ask("Team ID (10 char alphanumeric)", default=existing.get("team_id", ""))
    bundle_id = ask("App bundle id", default=existing.get("bundle_id", "com.opnmatrx.mtrx"))
    sandbox = yes_no("Use sandbox (development)?", default=False)

    channel_cfg = {
        "auth_key_p8": auth_key,
        "auth_key_path": str(p8),
        "key_id": key_id,
        "team_id": team_id,
        "bundle_id": bundle_id,
        "sandbox": sandbox,
        "device_tokens": existing.get("device_tokens", []),
    }
    update_channel(config, "ios_push", channel_cfg)
    save_config(config)
    update_env({
        "APNS_KEY_ID": key_id,
        "APNS_TEAM_ID": team_id,
        "APNS_BUNDLE_ID": bundle_id,
    })
    success("iOS push saved. Device tokens are registered at runtime from the app.")
    return channel_cfg


def main() -> int:
    return 0 if configure(load_config()) else 1


if __name__ == "__main__":
    sys.exit(main())
