"""SMS via Twilio setup."""

from __future__ import annotations

import sys

from setup._shared import (
    ask, header, load_config, save_config, success,
    test_channel_via_dispatcher, update_channel, update_env, warn,
)


def configure(config: dict) -> dict:
    header("SMS (Twilio) Setup")
    existing = config.get("notifications", {}).get("sms", {})
    info_txt = (
        "Get credentials at twilio.com/console. "
        "Phone numbers must include country code, e.g. +15551234567."
    )
    from setup._shared import info as _info; _info(info_txt)
    sid = ask("Twilio Account SID", default=existing.get("account_sid", ""))
    if not sid:
        warn("Skipping SMS.")
        return {}
    token = ask("Twilio Auth Token", default=existing.get("auth_token", ""), password=True)
    from_num = ask("From number (+15551234567)", default=existing.get("from_number", ""))
    to_num = ask("Alert recipient number (+15551234567)", default=existing.get("to_number", ""))
    channel_cfg = {
        "account_sid": sid, "auth_token": token,
        "from_number": from_num, "to_number": to_num,
    }
    update_channel(config, "sms", channel_cfg)
    save_config(config)
    update_env({
        "TWILIO_ACCOUNT_SID": sid,
        "TWILIO_AUTH_TOKEN": token,
        "TWILIO_FROM_NUMBER": from_num,
        "TWILIO_TO_NUMBER": to_num,
    })
    result = test_channel_via_dispatcher(config, "sms")
    if result.get("status") == "ok":
        success("SMS saved and test message sent.")
    else:
        warn(f"SMS saved but test failed: {result.get('error', '')}")
    return channel_cfg


def main() -> int:
    return 0 if configure(load_config()) else 1


if __name__ == "__main__":
    sys.exit(main())
