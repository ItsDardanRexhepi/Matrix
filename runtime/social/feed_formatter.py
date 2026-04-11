"""
runtime/social/feed_formatter.py
================================

Presentation helpers for the social feed — emoji/icon mapping, colour
assignment, and relative-time formatting.

Used by:
- ``gateway/server.py`` when serialising feed events for the REST API
- ``web/social.html`` as a reference for client-side rendering
- ``MTRX/Social/FeedEventRow.swift`` mirrors this logic in SwiftUI
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from runtime.social.feed_engine import FeedEvent


# ── Icon mapping ─────────────────────────────────────────────────────

ICONS: Dict[str, str] = {
    "deploy_contract": "📜",
    "swap_tokens": "🔄",
    "add_liquidity": "💧",
    "remove_liquidity": "💧",
    "mint_nft": "🎨",
    "transfer_nft": "🖼️",
    "create_collection": "🗂️",
    "create_proposal": "📋",
    "vote": "🗳️",
    "execute_proposal": "⚡",
    "create_dao": "🏛️",
    "stake": "🔒",
    "unstake": "🔓",
    "claim_rewards": "🎁",
    "send_payment": "💸",
    "create_invoice": "🧾",
    "register_ip": "©️",
    "create_license": "📄",
    "issue_badge": "🏅",
    "verify_social": "✅",
    "create_social_profile": "👤",
    "deploy_token": "🪙",
    "bridge_assets": "🌉",
    "request_loan": "🏦",
    "repay_loan": "✅",
    "create_insurance_policy": "🛡️",
    "file_insurance_claim": "📑",
    "convert_contract": "🔀",
    "create_game": "🎮",
    "register_supply_item": "📦",
    "verify_product": "🔍",
    "create_attestation": "📝",
    "tokenize_asset": "🏠",
    "list_security": "📊",
    "trade_security": "📈",
    "create_subscription": "💳",
}

# ── Colour tiers (CSS variable names) ───────────────────────────────

SCORE_COLOURS: List[tuple[float, str]] = [
    (0.8, "#00ff41"),  # green — exceptional
    (0.6, "#00cc33"),  # green-dim — high
    (0.4, "#33aa55"),  # muted green — medium
    (0.2, "#666666"),  # grey — low
    (0.0, "#444444"),  # dim — baseline
]

# ── Category groupings ──────────────────────────────────────────────

CATEGORIES: Dict[str, List[str]] = {
    "DeFi": [
        "swap_tokens", "add_liquidity", "remove_liquidity",
        "stake", "unstake", "claim_rewards", "request_loan",
        "repay_loan", "bridge_assets",
    ],
    "NFT": [
        "mint_nft", "transfer_nft", "create_collection",
    ],
    "Governance": [
        "create_proposal", "vote", "execute_proposal", "create_dao",
    ],
    "Contracts": [
        "deploy_contract", "convert_contract", "deploy_token",
    ],
    "Identity": [
        "verify_social", "create_social_profile", "issue_badge",
        "create_attestation",
    ],
    "Finance": [
        "send_payment", "create_invoice", "create_insurance_policy",
        "file_insurance_claim", "create_subscription",
        "tokenize_asset", "list_security", "trade_security",
    ],
    "IP & Supply": [
        "register_ip", "create_license", "register_supply_item",
        "verify_product",
    ],
    "Gaming": [
        "create_game",
    ],
}

# Reverse lookup: action → category
_ACTION_CATEGORY: Dict[str, str] = {}
for _cat, _actions in CATEGORIES.items():
    for _a in _actions:
        _ACTION_CATEGORY[_a] = _cat


class FeedFormatter:
    """Stateless presentation helper for feed events."""

    @staticmethod
    def icon(event_type: str) -> str:
        """Return the emoji icon for an action type."""
        return ICONS.get(event_type, "⚡")

    @staticmethod
    def colour(score: float) -> str:
        """Return a hex colour for a ranked score."""
        for threshold, colour in SCORE_COLOURS:
            if score >= threshold:
                return colour
        return SCORE_COLOURS[-1][1]

    @staticmethod
    def category(event_type: str) -> str:
        """Return the category name for an action type."""
        return _ACTION_CATEGORY.get(event_type, "Other")

    @staticmethod
    def time_ago(ts: float) -> str:
        """Human-readable relative time string."""
        delta = max(0, time.time() - ts)
        if delta < 5:
            return "just now"
        if delta < 60:
            s = int(delta)
            return f"{s}s ago"
        if delta < 3600:
            m = int(delta / 60)
            return f"{m}m ago"
        if delta < 86400:
            h = int(delta / 3600)
            return f"{h}h ago"
        if delta < 604800:
            d = int(delta / 86400)
            return f"{d}d ago"
        w = int(delta / 604800)
        return f"{w}w ago"

    @classmethod
    def format_event(cls, event: FeedEvent) -> Dict[str, Any]:
        """Return a presentation-ready dict for API responses."""
        return {
            **event.to_dict(),
            "icon": cls.icon(event.event_type),
            "colour": cls.colour(event.ranked_score),
            "category": cls.category(event.event_type),
            "time_ago": cls.time_ago(event.timestamp),
        }

    @classmethod
    def format_feed(cls, events: List[FeedEvent]) -> List[Dict[str, Any]]:
        """Format a list of events for API consumption."""
        return [cls.format_event(e) for e in events]
