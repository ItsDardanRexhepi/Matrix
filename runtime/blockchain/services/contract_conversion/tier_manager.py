"""
TierManager — classify contract complexity and calculate conversion fees.

Tiered pricing model:
  - Simple  (<100 lines):  0.01 ETH
  - Medium  (100-500 lines): 0.05 ETH
  - Complex (500+ lines):  0.1  ETH
  - Custom:                negotiated (returns sentinel)
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Tier definitions: (name, max_lines_exclusive, fee_eth)
_TIERS: list[tuple[str, int | None, float]] = [
    ("simple", 100, 0.01),
    ("medium", 500, 0.05),
    ("complex", None, 0.1),
]

# Patterns that increase complexity score beyond raw line count
_COMPLEXITY_PATTERNS: list[tuple[str, int, str]] = [
    (r"\bassembly\b", 20, "inline_assembly"),
    (r"\bdelegatecall\b", 15, "delegatecall"),
    (r"\bselfdestruct\b", 10, "selfdestruct"),
    (r"\bcreate2\b", 15, "create2"),
    (r"\bproxy\b", 10, "proxy_pattern"),
    (r"\breentrancy\b", 10, "reentrancy_guard"),
    (r"\bmapping\s*\(.*mapping\b", 10, "nested_mapping"),
    (r"\binherit\b|\bis\b\s+\w+", 5, "inheritance"),
    (r"\bmodifier\b", 3, "modifier"),
    (r"\bevent\b", 1, "event"),
    (r"\breceive\s*\(\s*\)", 5, "receive_fallback"),
    (r"\bfallback\s*\(\s*\)", 5, "fallback_function"),
    (r"\btry\b.*\bcatch\b", 8, "try_catch"),
    (r"\binterface\b", 5, "interface_usage"),
    (r"\blibrary\b", 5, "library_usage"),
]

# Custom tier trigger: if complexity score exceeds this, tier is custom
_CUSTOM_THRESHOLD = 200


class TierManager:
    """Classify contract complexity and compute conversion fees.

    Parameters
    ----------
    config : dict
        Platform config.  Reads ``conversion.tier_overrides`` for custom
        fee overrides per tier name, and ``conversion.custom_threshold``
        to adjust the custom-tier boundary.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        conv_cfg = config.get("conversion", {})
        self._tier_overrides: dict[str, float] = conv_cfg.get("tier_overrides", {})
        self._custom_threshold: int = int(
            conv_cfg.get("custom_threshold", _CUSTOM_THRESHOLD)
        )

    def classify(self, source: str) -> dict[str, Any]:
        """Classify a source contract and return tier info.

        Returns
        -------
        dict
            Keys: ``tier``, ``line_count``, ``complexity_score``,
            ``fee_eth``, ``complexity_factors``.
        """
        lines = [ln for ln in source.splitlines() if ln.strip()]
        line_count = len(lines)

        # Compute complexity score from pattern matching
        complexity_score = line_count
        complexity_factors: list[str] = []

        for pattern, weight, factor_name in _COMPLEXITY_PATTERNS:
            matches = len(re.findall(pattern, source, re.IGNORECASE))
            if matches > 0:
                complexity_score += matches * weight
                complexity_factors.append(f"{factor_name}({matches})")

        # Determine tier
        if complexity_score >= self._custom_threshold:
            tier = "custom"
            fee_eth = -1.0  # sentinel: must be negotiated
        else:
            tier = "complex"
            fee_eth = _TIERS[-1][2]
            for tier_name, max_lines, tier_fee in _TIERS:
                if max_lines is not None and line_count < max_lines:
                    tier = tier_name
                    fee_eth = tier_fee
                    break

        # Apply config overrides
        if tier in self._tier_overrides:
            fee_eth = self._tier_overrides[tier]

        result = {
            "tier": tier,
            "line_count": line_count,
            "complexity_score": complexity_score,
            "fee_eth": fee_eth,
            "complexity_factors": complexity_factors,
        }

        logger.info(
            "Classified contract: tier=%s lines=%d score=%d fee=%.4f ETH",
            tier, line_count, complexity_score, fee_eth,
        )
        return result
