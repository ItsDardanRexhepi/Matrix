"""
0pnMatrx setup package — modular, re-runnable channel configurators.

Each module in this package configures one notification channel
(telegram, discord, slack, email, sms, whatsapp, web_chat, ios_push,
webhook). Each module exposes a `configure(config)` function that
prompts for only its own credentials, verifies the channel by sending a
test message, and returns the updated channel config dict.

The top-level ``setup_communications.py`` is the human entry point:

    python setup_communications.py            # interactive menu
    python setup_communications.py telegram   # straight to Telegram
    python setup_communications.py --list     # show enabled channels
"""

from __future__ import annotations

__all__ = ["_shared"]
