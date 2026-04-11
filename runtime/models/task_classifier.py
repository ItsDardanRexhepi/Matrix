"""Task complexity classifier for intelligent model routing.

Analyses user messages and conversation context to determine the
appropriate model tier.  Simple tasks go to fast models, complex
tasks to the most capable, and critical (irreversible / high-value)
tasks always route to the best available model regardless of cost.
"""

from __future__ import annotations

import hashlib
import re
from enum import Enum
from typing import Any


class TaskComplexity(str, Enum):
    """Ordered tiers of task complexity."""
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    CRITICAL = "critical"


# ── Keyword sets for classification ────────────────────────────────

_CRITICAL_KEYWORDS: set[str] = {
    "deploy", "transfer", "burn", "revoke", "destroy", "irreversible",
    "selfdestruct", "renounce", "upgrade proxy", "self-destruct",
    "delete account", "ownership", "approve all", "setApprovalForAll",
}

_COMPLEX_KEYWORDS: set[str] = {
    "audit", "security", "vulnerability", "generate contract",
    "write contract", "create contract", "convert contract",
    "flash loan", "liquidat", "multi-step", "strategy",
    "optimise", "optimize", "analyse", "analyze", "explain code",
    "architecture", "migration", "reentrancy", "governance attack",
}

_SIMPLE_KEYWORDS: set[str] = {
    "hello", "hi", "hey", "thanks", "thank you", "ok", "okay",
    "what can you do", "help", "status", "balance", "price",
    "how are you", "good morning", "good evening", "gm",
}

_STATE_MODIFYING_TOOLS: set[str] = {
    "deploy_contract", "smart_contract", "send_payment",
    "swap_tokens", "stake", "unstake", "create_loan",
    "repay_loan", "mint_nft", "burn_nft", "list_nft_for_sale",
    "buy_nft", "create_dao", "vote", "create_proposal",
    "create_insurance", "file_insurance_claim", "register_ip",
    "tokenize_asset", "create_did", "create_campaign",
    "subscribe", "list_marketplace", "transfer_ownership",
    "convert_contract",
}

# Pattern to detect dollar amounts >= $1,000
_HIGH_VALUE_PATTERN = re.compile(
    r"\$\s*([0-9,]+(?:\.\d+)?)"
    r"|(\d{1,3}(?:,\d{3})+(?:\.\d+)?)\s*(?:dollars|usd|usdc|usdt|dai)",
    re.IGNORECASE,
)


def classify_task(
    messages: list[Any],
    tools: list[dict] | None = None,
) -> TaskComplexity:
    """Classify the complexity of a task based on conversation context.

    Examines the most recent user message, available tools, and
    conversation length to determine the appropriate model tier.
    """
    # Extract the last user message
    last_user_msg = ""
    for msg in reversed(messages):
        role = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else "")
        if role == "user":
            content = getattr(msg, "content", None) or (msg.get("content", "") if isinstance(msg, dict) else "")
            last_user_msg = str(content).lower()
            break

    if not last_user_msg:
        return TaskComplexity.MODERATE

    # ── Critical: irreversible or high-value ───────────────────────
    if any(kw in last_user_msg for kw in _CRITICAL_KEYWORDS):
        return TaskComplexity.CRITICAL

    # Check for high dollar amounts (>= $1,000)
    for match in _HIGH_VALUE_PATTERN.finditer(last_user_msg):
        amount_str = (match.group(1) or match.group(2) or "0").replace(",", "")
        try:
            if float(amount_str) >= 1_000:
                return TaskComplexity.CRITICAL
        except ValueError:
            pass

    # Check if available tools include state-modifying blockchain actions
    if tools:
        tool_names = {t.get("name", "") for t in tools}
        if tool_names & _STATE_MODIFYING_TOOLS:
            # Tools are available but check if the user is actually invoking one
            for kw in _STATE_MODIFYING_TOOLS:
                if kw.replace("_", " ") in last_user_msg:
                    return TaskComplexity.CRITICAL

    # ── Complex: multi-step reasoning or code generation ───────────
    if any(kw in last_user_msg for kw in _COMPLEX_KEYWORDS):
        return TaskComplexity.COMPLEX

    # Long messages often indicate complex requests
    if len(last_user_msg.split()) > 80:
        return TaskComplexity.COMPLEX

    # ── Simple: greetings, status, quick lookups ───────────────────
    if any(kw in last_user_msg for kw in _SIMPLE_KEYWORDS):
        word_count = len(last_user_msg.split())
        if word_count <= 10:
            return TaskComplexity.SIMPLE

    # ── Default: moderate ──────────────────────────────────────────
    return TaskComplexity.MODERATE


def estimate_tokens(messages: list[Any]) -> int:
    """Rough token count estimate for the full conversation context.

    Uses the ~4 characters per token heuristic.  Not precise, but
    good enough for routing and budget decisions.
    """
    total_chars = 0
    for msg in messages:
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content", "")
        total_chars += len(str(content or ""))
    return max(1, total_chars // 4)


def hash_args(arguments: dict) -> str:
    """Produce a short hash of tool-call arguments for loop detection."""
    raw = str(sorted(arguments.items())).encode()
    return hashlib.md5(raw).hexdigest()[:12]
