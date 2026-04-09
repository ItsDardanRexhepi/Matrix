from __future__ import annotations

"""
Omniversal Protocol — continuous capability expansion with no domain ceiling.
Manages domain gap mapping, expansion loop, and omniversal alignment scoring.
"""

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

DOMAIN_CATEGORIES: list[str] = [
    "blockchain", "defi", "nft", "identity", "governance", "insurance",
    "gaming", "social", "payments", "securities", "supply_chain",
    "iot", "ai", "legal", "healthcare", "security",
]

MILESTONE_THRESHOLDS: list[float] = [
    500.0, 2_000.0, 5_000.0, 10_000.0, 50_000.0, 100_000.0,
]

# Suggested expansions keyed by milestone index (0-based)
_MILESTONE_EXPANSIONS: dict[int, list[str]] = {
    0: ["defi", "payments"],
    1: ["nft", "gaming", "social"],
    2: ["identity", "governance", "insurance"],
    3: ["securities", "supply_chain", "legal"],
    4: ["iot", "ai", "healthcare"],
    5: ["blockchain", "defi", "nft", "identity", "governance",
        "insurance", "gaming", "social", "payments", "securities",
        "supply_chain", "iot", "ai", "legal", "healthcare"],
}


class OmniversalProtocol:
    """Boundaryless intelligence expansion — tracks which domains the
    system is active in, identifies gaps, scores alignment of new actions
    with the expansion mandate, and logs progress against revenue
    milestones."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

        # ── Internal state ────────────────────────────────────────────
        # domain_map: domain -> {"active": bool, "activated_at": float | None, "details": dict}
        self._domain_map: dict[str, dict[str, Any]] = {
            domain: {"active": False, "activated_at": None, "details": {}}
            for domain in DOMAIN_CATEGORIES
        }

        self._expansion_log: list[dict[str, Any]] = []
        self._milestones_reached: list[dict[str, Any]] = []
        self._max_log_entries = int(self.config.get("max_log_entries", 5000))

        logger.info("OmniversalProtocol initialised with %d domain categories",
                     len(DOMAIN_CATEGORIES))

    # ── Public API ────────────────────────────────────────────────────

    async def score_omniversal_alignment(self, action: dict[str, Any]) -> dict[str, Any]:
        """Score how much *action* expands domain reach (0-3).

        Scoring rubric:
            0 — no expansion value (already fully active domain, no new reach)
            1 — marginal expansion (deepens an existing active domain)
            2 — moderate expansion (activates a new domain or bridges two)
            3 — high expansion (opens an entirely new domain cluster)

        Returns:
            score: int (0-3)
            reasoning: str
            target_domains: list[str]
            current_coverage: float
        """
        target_domains: list[str] = action.get("domains", [])
        action_type = action.get("type", "unknown")

        if not target_domains:
            # Attempt to infer domain from action type / description
            description = str(action.get("description", action_type)).lower()
            target_domains = [d for d in DOMAIN_CATEGORIES if d in description]

        active_count = sum(1 for d in self._domain_map.values() if d["active"])
        coverage = self.get_progress_score()

        new_domains = [d for d in target_domains
                       if d in self._domain_map and not self._domain_map[d]["active"]]
        existing_domains = [d for d in target_domains
                           if d in self._domain_map and self._domain_map[d]["active"]]

        # Score
        if len(new_domains) >= 2:
            score = 3
            reasoning = (f"Opens {len(new_domains)} new domains: {', '.join(new_domains)}. "
                         "High expansion value.")
        elif len(new_domains) == 1:
            score = 2
            reasoning = (f"Activates new domain '{new_domains[0]}'. "
                         "Moderate expansion value.")
        elif existing_domains:
            score = 1
            reasoning = (f"Deepens existing domain(s): {', '.join(existing_domains)}. "
                         "Marginal expansion value.")
        else:
            score = 0
            reasoning = "No identifiable domain expansion from this action."

        result = {
            "score": score,
            "reasoning": reasoning,
            "target_domains": target_domains,
            "new_domains": new_domains,
            "current_coverage": round(coverage, 4),
        }
        logger.debug("Omniversal alignment score=%d for action '%s'", score, action_type)
        return result

    async def get_domain_gap_map(self) -> dict[str, Any]:
        """Return a map of active domains vs gaps.

        Returns:
            active: list[str]
            gaps: list[str]
            coverage: float
            total_domains: int
            domain_details: dict[str, dict]
        """
        active = [d for d, info in self._domain_map.items() if info["active"]]
        gaps = [d for d, info in self._domain_map.items() if not info["active"]]

        return {
            "active": sorted(active),
            "gaps": sorted(gaps),
            "coverage": round(self.get_progress_score(), 4),
            "total_domains": len(self._domain_map),
            "domain_details": {
                d: {
                    "active": info["active"],
                    "activated_at": info["activated_at"],
                    "details": info["details"],
                }
                for d, info in self._domain_map.items()
            },
        }

    async def check_expansion_milestones(
        self, revenue: float
    ) -> list[dict[str, Any]]:
        """Check which revenue milestones have been reached and return
        recommended domain expansions for newly reached milestones.

        Args:
            revenue: Current cumulative revenue in USD.

        Returns:
            List of milestone dicts with:
                threshold, reached, recommended_expansions, already_active
        """
        results: list[dict[str, Any]] = []
        reached_thresholds = {m["threshold"] for m in self._milestones_reached}

        for idx, threshold in enumerate(MILESTONE_THRESHOLDS):
            if revenue < threshold:
                continue
            if threshold in reached_thresholds:
                continue  # already recorded

            recommended = _MILESTONE_EXPANSIONS.get(idx, [])
            already_active = [d for d in recommended
                              if d in self._domain_map and self._domain_map[d]["active"]]
            new_recommended = [d for d in recommended if d not in already_active]

            milestone = {
                "milestone_id": str(uuid.uuid4()),
                "threshold": threshold,
                "reached": True,
                "reached_at": time.time(),
                "recommended_expansions": new_recommended,
                "already_active": already_active,
            }
            self._milestones_reached.append(milestone)
            results.append(milestone)

            logger.info("Revenue milestone $%.0f reached — recommending: %s",
                        threshold, ", ".join(new_recommended) or "none new")

        return results

    async def log_domain_expansion(
        self, domain: str, details: dict[str, Any]
    ) -> None:
        """Record a domain activation / expansion event.

        If the domain is in the known category list it is marked active.
        """
        entry = {
            "id": str(uuid.uuid4()),
            "domain": domain,
            "details": details,
            "timestamp": time.time(),
        }
        self._expansion_log.append(entry)

        # Bound log size
        if len(self._expansion_log) > self._max_log_entries:
            self._expansion_log = self._expansion_log[-self._max_log_entries:]

        # Activate domain
        if domain in self._domain_map:
            if not self._domain_map[domain]["active"]:
                self._domain_map[domain]["active"] = True
                self._domain_map[domain]["activated_at"] = time.time()
                logger.info("Domain '%s' activated", domain)
            self._domain_map[domain]["details"].update(details)
        else:
            # Unknown domain — add dynamically
            self._domain_map[domain] = {
                "active": True,
                "activated_at": time.time(),
                "details": details,
            }
            logger.info("New domain '%s' added and activated", domain)

    def get_progress_score(self) -> float:
        """Return active_domains / total_mapped_domains (0.0 – 1.0)."""
        total = len(self._domain_map)
        if total == 0:
            return 0.0
        active = sum(1 for d in self._domain_map.values() if d["active"])
        return active / total
