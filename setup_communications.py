#!/usr/bin/env python3
"""
setup_communications.py — configure Trinity's notification channels.

This is a standalone, re-runnable driver. Run it to add or update any
communication channel (Telegram, Discord, Slack, Email, SMS, WhatsApp,
Web chat, iOS push, Webhook). You can run it any time — before, during,
or after initial setup.

Usage:
    python setup_communications.py              # interactive menu
    python setup_communications.py telegram     # jump to one channel
    python setup_communications.py --list       # show enabled channels
    python setup_communications.py --help
"""

from __future__ import annotations

import sys
from typing import Callable

from setup._shared import (
    BOLD, CYAN, DIM, GREEN, RESET, YELLOW,
    ask, error, header, info, load_config, success, warn,
)

# Each channel maps to its configure() function.
CHANNELS: dict[str, tuple[str, str, Callable[[dict], dict]]] = {}


def _register_channels() -> None:
    from setup import telegram, discord, slack, email, sms, whatsapp, web_chat, ios_push, webhook
    CHANNELS["telegram"]  = ("Telegram",      "Bot messages (most popular choice)", telegram.configure)
    CHANNELS["discord"]   = ("Discord",       "Webhook into a Discord channel",      discord.configure)
    CHANNELS["slack"]     = ("Slack",         "Webhook into a Slack channel",        slack.configure)
    CHANNELS["email"]     = ("Email",         "Via SMTP (Gmail, SES, Mailgun, …)",   email.configure)
    CHANNELS["sms"]       = ("SMS",           "Text messages via Twilio",             sms.configure)
    CHANNELS["whatsapp"]  = ("WhatsApp",      "Via Twilio's WhatsApp API",            whatsapp.configure)
    CHANNELS["web_chat"]  = ("Web chat",      "Live feed in the built-in chat UI",    web_chat.configure)
    CHANNELS["ios_push"]  = ("iOS Push",      "APNs for the MTRX iOS app",            ios_push.configure)
    CHANNELS["webhook"]   = ("Generic",       "POST JSON to any URL of your choice", webhook.configure)


def show_list(config: dict) -> None:
    try:
        from runtime.notifications import NotificationDispatcher
        d = NotificationDispatcher(config)
        status = d.list_channels()
    except Exception as exc:
        error(f"Failed to inspect channels: {exc}")
        return
    header("Communication Channels")
    for entry in status:
        name = entry["name"]
        avail = "✓" if entry["available"] else ("…" if entry["enabled"] else " ")
        state = f"{GREEN}available{RESET}" if entry["available"] else (
            f"{YELLOW}configured, unreachable{RESET}" if entry["enabled"] else f"{DIM}not set{RESET}"
        )
        label = CHANNELS.get(name, (name,))[0]
        print(f"  [{avail}] {BOLD}{label:<10}{RESET}  {state}")


def show_menu(config: dict) -> str | None:
    header("Pick a channel to configure")
    ordered = list(CHANNELS.keys())
    for i, key in enumerate(ordered, 1):
        label, desc, _ = CHANNELS[key]
        configured = key in config.get("notifications", {})
        check = f"{GREEN}✓{RESET}" if configured else " "
        print(f"  {BOLD}{i:>2}{RESET} [{check}] {CYAN}{label:<10}{RESET} {DIM}— {desc}{RESET}")
    print(f"  {BOLD}  l{RESET}      {DIM}show status of all channels{RESET}")
    print(f"  {BOLD}  q{RESET}      {DIM}quit{RESET}")
    print()
    choice = ask("Choice (1-9, l, q)")
    if choice.lower() == "q" or not choice:
        return None
    if choice.lower() == "l":
        show_list(config)
        return ""  # re-show menu
    try:
        idx = int(choice)
        if 1 <= idx <= len(ordered):
            return ordered[idx - 1]
    except ValueError:
        pass
    return ordered[0] if choice in ordered else None


def main() -> int:
    _register_channels()
    config = load_config()

    # CLI: --list
    if len(sys.argv) > 1 and sys.argv[1] in ("--list", "-l"):
        show_list(config)
        return 0
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print(__doc__)
        return 0

    # CLI: direct channel name
    if len(sys.argv) > 1 and sys.argv[1] in CHANNELS:
        _, _, fn = CHANNELS[sys.argv[1]]
        fn(config)
        return 0

    # Interactive menu loop.
    while True:
        pick = show_menu(config)
        if pick is None:
            info("Done.")
            return 0
        if pick == "":  # list toggle re-shows menu
            continue
        if pick not in CHANNELS:
            warn("Unknown choice.")
            continue
        _, _, fn = CHANNELS[pick]
        fn(config)
        config = load_config()  # re-read after save
        print()


if __name__ == "__main__":
    sys.exit(main())
