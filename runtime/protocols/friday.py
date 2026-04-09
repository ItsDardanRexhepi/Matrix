"""
Friday Protocol — Proactive monitoring and suggestions.
Watches for opportunities, risks, and relevant events.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# ── Monitor categories ────────────────────────────────────────────────
MONITOR_CATEGORIES = (
    "price_movement",
    "governance_deadline",
    "insurance_trigger",
    "loan_health",
    "staking_rewards",
    "security_vulnerability",
)

# Notification urgency thresholds (seconds until deadline)
_URGENCY_THRESHOLDS = {
    "critical": 3600,       # < 1 hour
    "high": 86400,          # < 1 day
    "medium": 604800,       # < 1 week
    "low": float("inf"),
}

# Price movement thresholds (percentage)
_PRICE_MOVE_THRESHOLDS = {
    "alert": 5.0,
    "warning": 10.0,
    "critical": 20.0,
}


class FridayProtocol:
    """Proactive intelligence layer — continuously scans for events,
    opportunities, and risks that the user should know about."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._notification_log: list[dict[str, Any]] = []
        self._suppressed_categories: set[str] = set(
            self.config.get("suppressed_categories", [])
        )
        self._cooldowns: dict[str, float] = {}  # category -> earliest next notify
        self._default_cooldown = self.config.get("notification_cooldown_seconds", 300)
        logger.info("FridayProtocol initialised")

    # ── Public API ────────────────────────────────────────────────────

    async def check_opportunities(
        self, user_context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Scan *user_context* for relevant events across all monitor
        categories and return a list of opportunity dicts."""
        opportunities: list[dict[str, Any]] = []

        for category in MONITOR_CATEGORIES:
            if category in self._suppressed_categories:
                continue
            try:
                found = self._scan_category(category, user_context)
                opportunities.extend(found)
            except Exception:
                logger.exception("Error scanning category '%s'", category)

        # Sort by relevance score descending
        opportunities.sort(key=lambda o: o.get("relevance", 0), reverse=True)
        logger.info("Found %d opportunities", len(opportunities))
        return opportunities

    async def generate_suggestion(self, opportunity: dict[str, Any]) -> str:
        """Create an actionable, human-readable suggestion from an
        *opportunity* dict."""
        category = opportunity.get("category", "unknown")
        details = opportunity.get("details", {})
        urgency = opportunity.get("urgency", "low")

        generators = {
            "price_movement": self._suggest_price_action,
            "governance_deadline": self._suggest_governance_action,
            "insurance_trigger": self._suggest_insurance_action,
            "loan_health": self._suggest_loan_action,
            "staking_rewards": self._suggest_staking_action,
        }

        generator = generators.get(category, self._suggest_generic)
        suggestion = generator(details, urgency)
        return suggestion

    async def should_notify(self, event: dict[str, Any]) -> bool:
        """Decide whether *event* warrants a proactive notification.

        Considers: category suppression, cooldown windows, urgency,
        and user preference settings.
        """
        category = event.get("category", "unknown")
        urgency = event.get("urgency", "low")

        # Suppressed?
        if category in self._suppressed_categories:
            logger.debug("Category '%s' is suppressed — skipping", category)
            return False

        # Cooldown?
        now = time.time()
        cooldown_key = f"{category}:{event.get('id', 'default')}"
        if cooldown_key in self._cooldowns and now < self._cooldowns[cooldown_key]:
            logger.debug("Cooldown active for '%s' — skipping", cooldown_key)
            return False

        # Critical events always notify
        if urgency == "critical":
            self._record_notification(event, cooldown_key)
            return True

        # User preference: minimum urgency
        min_urgency = self.config.get("min_notification_urgency", "medium")
        urgency_order = ["low", "medium", "high", "critical"]
        if urgency_order.index(urgency) < urgency_order.index(min_urgency):
            return False

        # Duplicate suppression: same event id within cooldown window
        self._record_notification(event, cooldown_key)
        return True

    # ── Configuration helpers ─────────────────────────────────────────

    def suppress_category(self, category: str) -> None:
        """Stop notifications for *category*."""
        self._suppressed_categories.add(category)
        logger.info("Suppressed category '%s'", category)

    def unsuppress_category(self, category: str) -> None:
        """Resume notifications for *category*."""
        self._suppressed_categories.discard(category)
        logger.info("Unsuppressed category '%s'", category)

    # ── Private scanning ──────────────────────────────────────────────

    def _scan_category(
        self, category: str, ctx: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Dispatch to category-specific scanner."""
        scanners = {
            "price_movement": self._scan_prices,
            "governance_deadline": self._scan_governance,
            "insurance_trigger": self._scan_insurance,
            "loan_health": self._scan_loans,
            "staking_rewards": self._scan_staking,
        }
        scanner = scanners.get(category)
        if scanner is None:
            return []
        return scanner(ctx)

    def _scan_prices(self, ctx: dict[str, Any]) -> list[dict[str, Any]]:
        opps: list[dict[str, Any]] = []
        watchlist = ctx.get("price_watchlist", [])
        for item in watchlist:
            change_pct = abs(item.get("change_24h", 0))
            if change_pct >= _PRICE_MOVE_THRESHOLDS["alert"]:
                urgency = "low"
                if change_pct >= _PRICE_MOVE_THRESHOLDS["critical"]:
                    urgency = "critical"
                elif change_pct >= _PRICE_MOVE_THRESHOLDS["warning"]:
                    urgency = "high"
                else:
                    urgency = "medium"
                opps.append({
                    "category": "price_movement",
                    "urgency": urgency,
                    "relevance": min(change_pct / 20.0, 1.0),
                    "details": item,
                })
        return opps

    def _scan_governance(self, ctx: dict[str, Any]) -> list[dict[str, Any]]:
        opps: list[dict[str, Any]] = []
        proposals = ctx.get("active_proposals", [])
        now = time.time()
        for prop in proposals:
            deadline = prop.get("deadline", 0)
            remaining = deadline - now
            if remaining <= 0:
                continue
            urgency = "low"
            for level in ("critical", "high", "medium"):
                if remaining <= _URGENCY_THRESHOLDS[level]:
                    urgency = level
                    break
            opps.append({
                "category": "governance_deadline",
                "urgency": urgency,
                "relevance": max(0, 1.0 - remaining / 604800),
                "details": prop,
            })
        return opps

    def _scan_insurance(self, ctx: dict[str, Any]) -> list[dict[str, Any]]:
        opps: list[dict[str, Any]] = []
        policies = ctx.get("insurance_policies", [])
        for policy in policies:
            if policy.get("trigger_met"):
                opps.append({
                    "category": "insurance_trigger",
                    "urgency": "high",
                    "relevance": 0.9,
                    "details": policy,
                })
            elif policy.get("near_trigger"):
                opps.append({
                    "category": "insurance_trigger",
                    "urgency": "medium",
                    "relevance": 0.6,
                    "details": policy,
                })
        return opps

    def _scan_loans(self, ctx: dict[str, Any]) -> list[dict[str, Any]]:
        opps: list[dict[str, Any]] = []
        loans = ctx.get("active_loans", [])
        for loan in loans:
            health = loan.get("health_factor", 999)
            if health < 1.1:
                opps.append({
                    "category": "loan_health",
                    "urgency": "critical",
                    "relevance": 1.0,
                    "details": loan,
                })
            elif health < 1.5:
                opps.append({
                    "category": "loan_health",
                    "urgency": "high",
                    "relevance": 0.8,
                    "details": loan,
                })
            elif health < 2.0:
                opps.append({
                    "category": "loan_health",
                    "urgency": "medium",
                    "relevance": 0.5,
                    "details": loan,
                })
        return opps

    def _scan_staking(self, ctx: dict[str, Any]) -> list[dict[str, Any]]:
        opps: list[dict[str, Any]] = []
        positions = ctx.get("staking_positions", [])
        for pos in positions:
            unclaimed = pos.get("unclaimed_rewards", 0)
            threshold = self.config.get("staking_reward_notify_threshold", 10)
            if unclaimed >= threshold:
                opps.append({
                    "category": "staking_rewards",
                    "urgency": "low",
                    "relevance": min(unclaimed / 100.0, 1.0),
                    "details": pos,
                })
        return opps

    # ── Suggestion generators ─────────────────────────────────────────

    @staticmethod
    def _suggest_price_action(details: dict[str, Any], urgency: str) -> str:
        symbol = details.get("symbol", "token")
        change = details.get("change_24h", 0)
        direction = "up" if change > 0 else "down"
        return (
            f"{symbol} is {direction} {abs(change):.1f}% in 24h. "
            f"You may want to review your {symbol} positions."
        )

    @staticmethod
    def _suggest_governance_action(details: dict[str, Any], urgency: str) -> str:
        title = details.get("title", "A proposal")
        dao = details.get("dao", "DAO")
        return (
            f"'{title}' in {dao} needs your vote. "
            f"Urgency: {urgency}. Review and vote before the deadline."
        )

    @staticmethod
    def _suggest_insurance_action(details: dict[str, Any], urgency: str) -> str:
        policy_id = details.get("id", "unknown")
        if details.get("trigger_met"):
            return f"Insurance policy {policy_id} trigger condition met. You can file a claim now."
        return f"Insurance policy {policy_id} is approaching its trigger threshold. Monitor closely."

    @staticmethod
    def _suggest_loan_action(details: dict[str, Any], urgency: str) -> str:
        health = details.get("health_factor", 0)
        protocol = details.get("protocol", "lending protocol")
        if health < 1.1:
            return (
                f"URGENT: Your {protocol} loan health factor is {health:.2f}. "
                f"Liquidation is imminent. Add collateral or repay debt immediately."
            )
        return (
            f"Your {protocol} loan health factor is {health:.2f}. "
            f"Consider adding collateral to improve safety margin."
        )

    @staticmethod
    def _suggest_staking_action(details: dict[str, Any], urgency: str) -> str:
        unclaimed = details.get("unclaimed_rewards", 0)
        validator = details.get("validator", "your validator")
        return (
            f"You have {unclaimed:.2f} unclaimed staking rewards from {validator}. "
            f"Claim and restake to compound your returns."
        )

    @staticmethod
    def _suggest_generic(details: dict[str, Any], urgency: str) -> str:
        return f"Event detected ({urgency} urgency): {details.get('summary', 'Review your dashboard for details.')}"

    # ── Internal bookkeeping ──────────────────────────────────────────

    def _record_notification(self, event: dict[str, Any], cooldown_key: str) -> None:
        now = time.time()
        self._notification_log.append({
            "event": event,
            "timestamp": now,
        })
        self._cooldowns[cooldown_key] = now + self._default_cooldown
        # Keep log bounded
        max_log = self.config.get("max_notification_log", 200)
        if len(self._notification_log) > max_log:
            self._notification_log = self._notification_log[-max_log:]
