#!/usr/bin/env python3
"""
setup_telegram.py — Standalone Telegram bot configuration.

Run this AFTER initial `setup.py` to add or update the Telegram
integration without re-running the full setup wizard.

Usage:
    python setup_telegram.py
    python -m setup_telegram

What it does:
  1. Prompts for your bot token (from @BotFather)
  2. Auto-discovers your chat ID by waiting for you to send a message
  3. Verifies the bot can reach you by sending a test message
  4. Updates openmatrix.config.json and .env with the credentials
  5. Restarts gateway (if running) so changes take effect

Requires: `requests` (already a runtime dependency)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: The 'requests' package is required. Run: pip install requests")
    sys.exit(1)

# ANSI color codes
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"

CONFIG_PATH = Path("openmatrix.config.json")
ENV_PATH = Path(".env")


def info(msg: str) -> None:
    print(f"{DIM}• {msg}{RESET}")


def success(msg: str) -> None:
    print(f"{GREEN}✓ {msg}{RESET}")


def warn(msg: str) -> None:
    print(f"{YELLOW}! {msg}{RESET}")


def error(msg: str) -> None:
    print(f"{RED}✗ {msg}{RESET}")


def ask(question: str, default: str = "") -> str:
    """Prompt for input with an optional default."""
    suffix = f" [{default}]" if default else ""
    resp = input(f"{BOLD}? {question}{suffix}:{RESET} ").strip()
    return resp or default


def verify_bot_token(token: str) -> dict | None:
    """Call Telegram getMe to confirm the token works."""
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            return data["result"]
        error(f"Telegram rejected the token: {data.get('description', 'unknown error')}")
        return None
    except requests.RequestException as exc:
        error(f"Could not reach Telegram API: {exc}")
        return None


def discover_chat_id(token: str, timeout_s: int = 120) -> str | None:
    """
    Wait for the user to message the bot, then pluck their chat_id
    from getUpdates. This avoids the user having to find it manually.
    """
    print()
    info("Open Telegram. Find your bot and send it ANY message (e.g. 'hi').")
    info(f"Waiting up to {timeout_s}s for your first message...")
    print()

    # Drain any existing updates so we only pick up new ones
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10)
        last_update_id = 0
        for upd in r.json().get("result", []):
            last_update_id = max(last_update_id, upd.get("update_id", 0))
    except requests.RequestException:
        last_update_id = 0

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": last_update_id + 1, "timeout": 5},
                timeout=10,
            )
            data = r.json()
            if data.get("ok"):
                for upd in data.get("result", []):
                    msg = upd.get("message") or upd.get("channel_post") or {}
                    chat = msg.get("chat") or {}
                    chat_id = chat.get("id")
                    if chat_id is not None:
                        name = chat.get("first_name") or chat.get("title") or "unknown"
                        success(f"Detected chat with {name} (id: {chat_id})")
                        return str(chat_id)
                    last_update_id = max(last_update_id, upd.get("update_id", 0))
        except requests.RequestException:
            pass
        time.sleep(1)

    error("Timed out waiting for a message.")
    return None


def send_test_message(token: str, chat_id: str) -> bool:
    """Send a hello-world message to confirm everything works."""
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": (
                    "✅ *0pnMatrx is connected.*\n\n"
                    "This bot will now send you notifications from the gateway.\n"
                    "Approval requests, errors, and status updates will arrive here."
                ),
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        return bool(r.json().get("ok"))
    except requests.RequestException:
        return False


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            warn("Existing config is not valid JSON. Starting with an empty config.")
    return {}


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def update_env(token: str, chat_id: str) -> None:
    """Merge TELEGRAM_BOT_TOKEN and OWNER_TELEGRAM_ID into .env."""
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    def set_or_append(var: str, value: str) -> None:
        nonlocal lines
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{var}="):
                lines[i] = f"{var}={value}"
                found = True
                break
        if not found:
            lines.append(f"{var}={value}")

    set_or_append("TELEGRAM_BOT_TOKEN", token)
    set_or_append("OWNER_TELEGRAM_ID", chat_id)
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    print()
    print(f"{BOLD}=== 0pnMatrx Telegram Setup ==={RESET}")
    print()

    token = os.environ.get("TELEGRAM_BOT_TOKEN") or ask(
        "Telegram Bot Token (from @BotFather)"
    )
    if not token:
        error("Bot token is required.")
        return 1

    info("Verifying token with Telegram...")
    bot_info = verify_bot_token(token)
    if not bot_info:
        return 1
    success(f"Connected to bot: @{bot_info.get('username', '?')}")

    chat_id = ask(
        "Your Telegram chat/user ID (leave blank to auto-detect)",
        default="",
    )
    if not chat_id:
        chat_id = discover_chat_id(token) or ""
    if not chat_id:
        error("No chat ID. Rerun and send a message to the bot.")
        return 1

    info("Sending test message...")
    if not send_test_message(token, chat_id):
        warn("Test message failed, but saving config anyway.")
    else:
        success("Test message delivered.")

    # Persist
    config = load_config()
    notifications = config.setdefault("notifications", {})
    notifications["telegram"] = {
        "enabled": True,
        "bot_token": token,
        "chat_id": chat_id,
        "owner_id": chat_id,
    }
    save_config(config)
    update_env(token, chat_id)

    print()
    success("Telegram integration saved.")
    info(f"Updated: {CONFIG_PATH}")
    info(f"Updated: {ENV_PATH}")
    print()
    info("If the gateway is running, restart it to pick up the new config:")
    print(f"  {DIM}docker compose restart gateway{RESET}  # Docker")
    print(f"  {DIM}# or kill and relaunch `python -m gateway.server`{RESET}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
