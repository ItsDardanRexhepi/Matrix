"""WhatsApp via Twilio setup."""

from __future__ import annotations

import sys

from setup._shared import (
    ask, header, info, load_config, save_config, success,
    test_channel_via_dispatcher, update_channel, update_env, warn,
)


def configure(config: dict) -> dict:
    header("WhatsApp (Twilio) Setup")
    info("Uses Twilio's WhatsApp API. Sandbox is free; production requires approved sender.")
    existing = config.get("notifications", {}).get("whatsapp", {})
    sid = ask("Twilio Account SID", default=existing.get("account_sid", ""))
    if not sid:
        warn("Skipping WhatsApp.")
        return {}
    token = ask("Twilio Auth Token", default=existing.get("auth_token", ""), password=True)
    from_num = ask("From WhatsApp number (+14155238886 for sandbox)",
                    default=existing.get("from_number", ""))
    to_num = ask("Recipient WhatsApp number (+15551234567)",
                  default=existing.get("to_number", ""))
    channel_cfg = {
        "account_sid": sid, "auth_token": token,
        "from_number": from_num, "to_number": to_num,
    }
    update_channel(config, "whatsapp", channel_cfg)
    save_config(config)
    update_env({
        "TWILIO_WHATSAPP_FROM": from_num,
        "TWILIO_WHATSAPP_TO": to_num,
    })
    result = test_channel_via_dispatcher(config, "whatsapp")
    if result.get("status") == "ok":
        success("WhatsApp saved and test message sent.")
    else:
        warn(f"WhatsApp saved but test failed: {result.get('error', '')}")
    return channel_cfg


def main() -> int:
    return 0 if configure(load_config()) else 1


if __name__ == "__main__":
    sys.exit(main())
