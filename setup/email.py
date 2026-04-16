"""Email (SMTP) setup."""

from __future__ import annotations

import sys

from setup._shared import (
    ask, header, load_config, save_config, success,
    test_channel_via_dispatcher, update_channel, update_env, warn,
)


def configure(config: dict) -> dict:
    header("Email (SMTP) Setup")
    existing = config.get("notifications", {}).get("email", {})
    host = ask("SMTP host (e.g. smtp.gmail.com)", default=existing.get("smtp_host", ""))
    if not host:
        warn("Skipping email.")
        return {}
    port = ask("SMTP port (587 for STARTTLS, 465 for SSL)", default=str(existing.get("smtp_port", 587)))
    user = ask("SMTP username / email", default=existing.get("smtp_user", ""))
    password = ask("SMTP password / app password", password=True)
    from_addr = ask("From address", default=existing.get("from", user))
    to_addr = ask("Notify recipient (To: address)", default=existing.get("to", user))
    use_ssl = ask("Use SSL (yes/no)", default="no").lower().startswith("y")
    channel_cfg = {
        "smtp_host": host, "smtp_port": int(port or 587),
        "smtp_user": user, "smtp_pass": password,
        "from": from_addr, "to": to_addr, "use_ssl": use_ssl,
    }
    update_channel(config, "email", channel_cfg)
    save_config(config)
    update_env({
        "SMTP_HOST": host, "SMTP_PORT": str(port),
        "SMTP_USER": user, "SMTP_PASS": password,
        "SMTP_FROM": from_addr, "SMTP_TO": to_addr,
    })
    result = test_channel_via_dispatcher(config, "email")
    if result.get("status") == "ok":
        success("Email saved and test message sent.")
    else:
        warn(f"Email saved but test failed: {result.get('error', '')}")
    return channel_cfg


def main() -> int:
    return 0 if configure(load_config()) else 1


if __name__ == "__main__":
    sys.exit(main())
