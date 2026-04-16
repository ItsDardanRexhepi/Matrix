"""Telegram bot setup — idempotent, re-runnable."""

from __future__ import annotations

import sys
import time

from setup._shared import (
    ask, error, header, info, load_config, save_config,
    success, update_channel, update_env, warn,
)

try:
    import requests
except ImportError:
    requests = None  # type: ignore


def _verify_token(token: str) -> dict | None:
    if requests is None:
        error("The 'requests' package is required. pip install requests")
        return None
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        data = r.json()
        if data.get("ok"):
            return data["result"]
        error(f"Telegram rejected the token: {data.get('description', 'unknown')}")
    except requests.RequestException as exc:
        error(f"Could not reach Telegram: {exc}")
    return None


def _discover_chat_id(token: str, timeout_s: int = 120) -> str | None:
    info("Open Telegram, find your bot, send it ANY message (e.g. 'hi').")
    info(f"Waiting up to {timeout_s}s for your first message...")
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10)
        last = max([u.get("update_id", 0) for u in r.json().get("result", [])] or [0])
    except requests.RequestException:
        last = 0
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": last + 1, "timeout": 5}, timeout=10,
            )
            for upd in r.json().get("result", []):
                msg = upd.get("message") or upd.get("channel_post") or {}
                chat = msg.get("chat") or {}
                if chat.get("id") is not None:
                    name = chat.get("first_name") or chat.get("title") or "unknown"
                    success(f"Detected chat with {name} (id: {chat['id']})")
                    return str(chat["id"])
                last = max(last, upd.get("update_id", 0))
        except requests.RequestException:
            pass
        time.sleep(1)
    error("Timed out waiting for a message.")
    return None


def configure(config: dict) -> dict:
    header("Telegram Setup")
    existing = config.get("notifications", {}).get("telegram", {})
    token = ask("Bot token (from @BotFather)", default=existing.get("bot_token", ""))
    if not token:
        warn("Skipping Telegram.")
        return {}
    bot = _verify_token(token)
    if bot is None:
        return {}
    success(f"Connected to bot @{bot.get('username', '?')}")
    chat_id = ask("Your chat/user ID (leave blank to auto-detect)",
                  default=str(existing.get("chat_id", "")))
    if not chat_id:
        chat_id = _discover_chat_id(token) or ""
    if not chat_id:
        error("No chat ID. Rerun after messaging the bot.")
        return {}
    channel_cfg = {"bot_token": token, "chat_id": chat_id, "owner_id": chat_id}
    update_channel(config, "telegram", channel_cfg)
    save_config(config)
    update_env({"TELEGRAM_BOT_TOKEN": token, "OWNER_TELEGRAM_ID": chat_id})
    success("Telegram saved.")
    return channel_cfg


def main() -> int:
    config = load_config()
    result = configure(config)
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
