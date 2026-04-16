"""
Shared helpers for the modular setup wizards.

Every channel configurator uses these for consistent prompts, config
persistence, and `.env` updates.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ANSI colors
BOLD  = "\033[1m"
DIM   = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED   = "\033[31m"
CYAN  = "\033[36m"
RESET = "\033[0m"

CONFIG_PATH = Path("openmatrix.config.json")
ENV_PATH = Path(".env")


# ── Output helpers ──────────────────────────────────────────────────────

def info(msg: str) -> None:
    print(f"{DIM}• {msg}{RESET}")

def success(msg: str) -> None:
    print(f"{GREEN}✓ {msg}{RESET}")

def warn(msg: str) -> None:
    print(f"{YELLOW}! {msg}{RESET}")

def error(msg: str) -> None:
    print(f"{RED}✗ {msg}{RESET}")

def header(title: str) -> None:
    print()
    print(f"{BOLD}{CYAN}=== {title} ==={RESET}")
    print()


# ── Input helpers ───────────────────────────────────────────────────────

def ask(question: str, default: str = "", *, password: bool = False) -> str:
    """Prompt for input with an optional default."""
    suffix = f" [{default}]" if default else ""
    prompt = f"{BOLD}? {question}{suffix}:{RESET} "
    if password:
        import getpass
        resp = getpass.getpass(prompt)
    else:
        resp = input(prompt).strip()
    return resp or default


def yes_no(question: str, default: bool = False) -> bool:
    default_str = "yes" if default else "no"
    resp = ask(question, default=default_str)
    return resp.lower().startswith("y")


# ── Config persistence ─────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            warn("Existing config is not valid JSON. Starting with an empty config.")
    return {}


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def update_channel(config: dict, channel_name: str, channel_cfg: dict) -> None:
    """Merge *channel_cfg* into config['notifications'][channel_name]."""
    notif = config.setdefault("notifications", {})
    existing = notif.get(channel_name, {})
    existing.update(channel_cfg)
    existing["enabled"] = True
    notif[channel_name] = existing


def update_env(updates: dict[str, str]) -> None:
    """Merge key=value pairs into the top-level .env file."""
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    for var, value in updates.items():
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{var}="):
                lines[i] = f"{var}={value}"
                found = True
                break
        if not found:
            lines.append(f"{var}={value}")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Channel test ────────────────────────────────────────────────────────

def test_channel_via_dispatcher(config: dict, channel_name: str) -> dict:
    """Instantiate the NotificationDispatcher and fire a test message.

    Returns the adapter's result dict. Never raises.
    """
    try:
        from runtime.notifications import NotificationDispatcher
    except Exception as exc:
        return {"status": "error", "error": f"failed to import dispatcher: {exc}"}

    import asyncio
    dispatcher = NotificationDispatcher(config)
    try:
        return asyncio.run(dispatcher.test_channel(channel_name))
    except RuntimeError:
        # If an event loop is already running we can't use asyncio.run().
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(dispatcher.test_channel(channel_name))
        finally:
            loop.close()
