"""
ArtistClassifier — detect whether a contract is art/music/creative NFT.

Inspects source code for creative-domain signals (ERC-721 patterns,
metadata URIs referencing art/music, royalty logic, etc.) and recommends
the best template from the 0pnMatrx library.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Weighted keyword sets per creative category
_CATEGORY_SIGNALS: dict[str, list[tuple[str, int]]] = {
    "visual_art": [
        (r"\bart\b", 3),
        (r"\bimage\b", 2),
        (r"\bgallery\b", 3),
        (r"\bcanvas\b", 2),
        (r"\bphoto\b", 2),
        (r"\billustration\b", 3),
        (r"\bpfp\b", 3),
        (r"\bgenerative\b", 4),
        (r"\bsvg\b", 3),
    ],
    "music": [
        (r"\bmusic\b", 4),
        (r"\bsong\b", 3),
        (r"\btrack\b", 2),
        (r"\balbum\b", 3),
        (r"\bartist\b", 2),
        (r"\baudio\b", 3),
        (r"\bbeat\b", 2),
        (r"\bmelody\b", 3),
        (r"\broyalt(?:y|ies)\b", 2),
        (r"\bstream\b", 2),
    ],
    "video": [
        (r"\bvideo\b", 4),
        (r"\bfilm\b", 3),
        (r"\banimation\b", 3),
        (r"\bframe\b", 2),
        (r"\bclip\b", 2),
    ],
    "collectible": [
        (r"\bcollect(?:ible|ion)\b", 4),
        (r"\brare\b", 2),
        (r"\btrait\b", 3),
        (r"\brarity\b", 3),
        (r"\bmint\b", 2),
        (r"\bedition\b", 3),
        (r"\bseries\b", 2),
    ],
    "gaming": [
        (r"\bgam(?:e|ing)\b", 4),
        (r"\bloot\b", 3),
        (r"\bweapon\b", 2),
        (r"\bcharacter\b", 2),
        (r"\blevel\b", 2),
        (r"\binventory\b", 3),
    ],
}

# Template recommendations per category
_TEMPLATE_MAP: dict[str, str] = {
    "visual_art": "erc721",
    "music": "erc1155",
    "video": "erc721",
    "collectible": "erc1155",
    "gaming": "erc1155",
}

# Generic creative signals (not category-specific)
_GENERIC_CREATIVE_PATTERNS: list[tuple[str, int]] = [
    (r"\bERC-?721\b", 5),
    (r"\bERC-?1155\b", 5),
    (r"\btokenURI\b", 4),
    (r"\bmetadata\b", 3),
    (r"\broyalt(?:y|ies)\b", 4),
    (r"\bcreator\b", 3),
    (r"\bnft\b", 5),
    (r"\bopensea\b", 3),
    (r"\bipfs\b", 3),
    (r"\barweave\b", 3),
]

_CREATIVE_THRESHOLD = 8


class ArtistClassifier:
    """Detect if a contract relates to art, music, or creative NFTs.

    Parameters
    ----------
    config : dict
        Platform config.  Optional key ``conversion.creative_threshold``
        overrides the minimum score for ``is_artist=True``.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self._threshold: int = int(
            config.get("conversion", {}).get(
                "creative_threshold", _CREATIVE_THRESHOLD
            )
        )

    def classify(self, source: str) -> dict[str, Any]:
        """Analyse source code for creative/artist signals.

        Returns
        -------
        dict
            Keys: ``is_artist``, ``category`` (best-match or ``None``),
            ``creative_score``, ``category_scores``,
            ``recommended_template``.
        """
        source_lower = source.lower()

        # Score each category
        category_scores: dict[str, int] = {}
        for category, signals in _CATEGORY_SIGNALS.items():
            score = 0
            for pattern, weight in signals:
                matches = len(re.findall(pattern, source_lower))
                score += matches * weight
            if score > 0:
                category_scores[category] = score

        # Generic creative score
        generic_score = 0
        for pattern, weight in _GENERIC_CREATIVE_PATTERNS:
            matches = len(re.findall(pattern, source, re.IGNORECASE))
            generic_score += matches * weight

        # Total creative score = best category + generic
        best_category: str | None = None
        best_category_score = 0
        if category_scores:
            best_category = max(category_scores, key=category_scores.get)  # type: ignore[arg-type]
            best_category_score = category_scores[best_category]

        creative_score = best_category_score + generic_score
        is_artist = creative_score >= self._threshold

        recommended_template: str | None = None
        if is_artist and best_category:
            recommended_template = _TEMPLATE_MAP.get(best_category, "erc721")
        elif is_artist:
            recommended_template = "erc721"

        result = {
            "is_artist": is_artist,
            "category": best_category,
            "creative_score": creative_score,
            "category_scores": category_scores,
            "recommended_template": recommended_template,
        }

        logger.info(
            "Artist classification: is_artist=%s category=%s score=%d",
            is_artist, best_category, creative_score,
        )
        return result
