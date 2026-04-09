"""
Vision Protocol — Emergence detection and pattern recognition.
Identifies trends, anomalies, and correlations across user activity.
"""

import logging
import statistics
from typing import Any

logger = logging.getLogger(__name__)

PATTERN_TYPES = ("spending", "interaction", "governance", "social", "market", "security")


class VisionProtocol:
    """Analyses user activity history to surface patterns, flag anomalies,
    and correlate events that may not be obvious in isolation."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._known_patterns: list[dict[str, Any]] = []
        logger.info("VisionProtocol initialised")

    # ── Public API ────────────────────────────────────────────────────

    async def detect_patterns(
        self, activity_history: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Scan *activity_history* for recurring patterns.

        Returns a list of pattern dicts, each with:
            pattern_type, description, confidence, occurrences, metadata
        """
        if not activity_history:
            return []

        patterns: list[dict[str, Any]] = []

        for ptype in PATTERN_TYPES:
            try:
                found = self._detect_by_type(ptype, activity_history)
                patterns.extend(found)
            except Exception:
                logger.exception("Error detecting '%s' patterns", ptype)

        # Deduplicate against known patterns
        novel = self._filter_novel(patterns)
        self._known_patterns.extend(novel)

        # Cap stored patterns
        max_stored = self.config.get("max_stored_patterns", 200)
        if len(self._known_patterns) > max_stored:
            self._known_patterns = self._known_patterns[-max_stored:]

        logger.info(
            "Detected %d patterns (%d novel) from %d activities",
            len(patterns), len(novel), len(activity_history),
        )
        return patterns

    async def identify_anomalies(
        self, transaction: dict[str, Any], history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Determine whether *transaction* is anomalous given *history*.

        Returns:
            is_anomaly: bool
            anomaly_score: float 0-1
            reasons: list of strings
            recommendation: str
        """
        reasons: list[str] = []
        score = 0.0

        # Value anomaly
        value_score, value_reasons = self._check_value_anomaly(transaction, history)
        score = max(score, value_score)
        reasons.extend(value_reasons)

        # Recipient anomaly
        recip_score, recip_reasons = self._check_recipient_anomaly(transaction, history)
        score = max(score, recip_score)
        reasons.extend(recip_reasons)

        # Timing anomaly
        time_score, time_reasons = self._check_timing_anomaly(transaction, history)
        score = max(score, time_score)
        reasons.extend(time_reasons)

        # Type frequency anomaly
        type_score, type_reasons = self._check_type_anomaly(transaction, history)
        score = max(score, type_score)
        reasons.extend(type_reasons)

        is_anomaly = score >= self.config.get("anomaly_threshold", 0.6)

        recommendation = "Proceed normally."
        if is_anomaly:
            if score >= 0.9:
                recommendation = "This transaction is highly unusual. Verify all details carefully before proceeding."
            elif score >= 0.7:
                recommendation = "This transaction deviates from your typical activity. Double-check the details."
            else:
                recommendation = "Minor deviation from typical patterns detected. Review if needed."

        result = {
            "is_anomaly": is_anomaly,
            "anomaly_score": round(score, 3),
            "reasons": reasons,
            "recommendation": recommendation,
        }
        if is_anomaly:
            logger.warning("Anomaly detected (score=%.2f): %s", score, reasons)
        return result

    async def correlate_events(
        self, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Find correlations between *events*.

        Returns a list of correlation dicts with:
            events: list of correlated event ids
            correlation_type: str
            strength: float 0-1
            description: str
        """
        if len(events) < 2:
            return []

        correlations: list[dict[str, Any]] = []

        # Temporal clustering
        correlations.extend(self._find_temporal_clusters(events))

        # Category co-occurrence
        correlations.extend(self._find_category_cooccurrence(events))

        # Value correlation
        correlations.extend(self._find_value_correlations(events))

        # Sort by strength
        correlations.sort(key=lambda c: c.get("strength", 0), reverse=True)

        logger.info("Found %d correlations across %d events", len(correlations), len(events))
        return correlations

    # ── Pattern detection by type ─────────────────────────────────────

    def _detect_by_type(
        self, ptype: str, history: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        detectors = {
            "spending": self._detect_spending_patterns,
            "interaction": self._detect_interaction_patterns,
            "governance": self._detect_governance_patterns,
            "social": self._detect_social_patterns,
            "market": self._detect_market_patterns,
        }
        detector = detectors.get(ptype)
        if detector is None:
            return []
        return detector(history)

    def _detect_spending_patterns(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        patterns: list[dict[str, Any]] = []
        txns = [h for h in history if h.get("type") in ("transfer", "swap", "spend")]
        if not txns:
            return patterns

        values = [t.get("value", 0) for t in txns if isinstance(t.get("value"), (int, float))]
        if len(values) >= 3:
            avg = statistics.mean(values)
            patterns.append({
                "pattern_type": "spending",
                "description": f"Average transaction value: ${avg:.2f}",
                "confidence": min(len(values) / 20.0, 1.0),
                "occurrences": len(values),
                "metadata": {"average_value": avg, "count": len(values)},
            })

        # Recurring amounts
        amount_counts: dict[float, int] = {}
        for v in values:
            rounded = round(v, 2)
            amount_counts[rounded] = amount_counts.get(rounded, 0) + 1
        for amount, count in amount_counts.items():
            if count >= 3:
                patterns.append({
                    "pattern_type": "spending",
                    "description": f"Recurring transaction amount: ${amount:.2f} ({count} times)",
                    "confidence": min(count / 10.0, 1.0),
                    "occurrences": count,
                    "metadata": {"amount": amount},
                })

        return patterns

    def _detect_interaction_patterns(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        patterns: list[dict[str, Any]] = []
        contract_counts: dict[str, int] = {}
        for h in history:
            target = h.get("contract") or h.get("to") or h.get("target")
            if target:
                contract_counts[target] = contract_counts.get(target, 0) + 1

        for addr, count in contract_counts.items():
            if count >= 3:
                patterns.append({
                    "pattern_type": "interaction",
                    "description": f"Frequent interaction with {addr[:10]}... ({count} times)",
                    "confidence": min(count / 15.0, 1.0),
                    "occurrences": count,
                    "metadata": {"address": addr},
                })
        return patterns

    def _detect_governance_patterns(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        patterns: list[dict[str, Any]] = []
        votes = [h for h in history if h.get("type") in ("vote", "governance")]
        if len(votes) >= 2:
            daos: dict[str, int] = {}
            for v in votes:
                dao = v.get("dao", "unknown")
                daos[dao] = daos.get(dao, 0) + 1
            for dao, count in daos.items():
                patterns.append({
                    "pattern_type": "governance",
                    "description": f"Active governance participant in {dao} ({count} votes)",
                    "confidence": min(count / 10.0, 1.0),
                    "occurrences": count,
                    "metadata": {"dao": dao},
                })
        return patterns

    def _detect_social_patterns(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        patterns: list[dict[str, Any]] = []
        social = [h for h in history if h.get("type") in ("social", "message", "follow")]
        if len(social) >= 3:
            patterns.append({
                "pattern_type": "social",
                "description": f"Active social engagement ({len(social)} interactions)",
                "confidence": min(len(social) / 20.0, 1.0),
                "occurrences": len(social),
                "metadata": {},
            })
        return patterns

    def _detect_market_patterns(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        patterns: list[dict[str, Any]] = []
        trades = [h for h in history if h.get("type") in ("swap", "trade", "buy", "sell")]
        if len(trades) >= 3:
            buy_count = sum(1 for t in trades if t.get("type") in ("buy", "swap"))
            sell_count = sum(1 for t in trades if t.get("type") == "sell")
            if buy_count > sell_count * 2:
                patterns.append({
                    "pattern_type": "market",
                    "description": "Predominantly accumulating (buying > selling)",
                    "confidence": 0.7,
                    "occurrences": len(trades),
                    "metadata": {"buy_count": buy_count, "sell_count": sell_count},
                })
            elif sell_count > buy_count * 2:
                patterns.append({
                    "pattern_type": "market",
                    "description": "Predominantly distributing (selling > buying)",
                    "confidence": 0.7,
                    "occurrences": len(trades),
                    "metadata": {"buy_count": buy_count, "sell_count": sell_count},
                })
        return patterns

    # ── Anomaly checks ────────────────────────────────────────────────

    def _check_value_anomaly(
        self, txn: dict[str, Any], history: list[dict[str, Any]]
    ) -> tuple[float, list[str]]:
        value = txn.get("value")
        if not isinstance(value, (int, float)):
            return 0.0, []

        hist_values = [
            h.get("value") for h in history
            if isinstance(h.get("value"), (int, float))
        ]
        if len(hist_values) < 3:
            return 0.0, []

        mean = statistics.mean(hist_values)
        stdev = statistics.stdev(hist_values) if len(hist_values) > 1 else mean * 0.5
        if stdev == 0:
            stdev = mean * 0.1 or 1.0

        z_score = abs(value - mean) / stdev
        score = min(z_score / 4.0, 1.0)  # normalise: z=4 -> score=1
        reasons: list[str] = []
        if score >= 0.5:
            reasons.append(
                f"Transaction value ${value:,.2f} deviates significantly from average ${mean:,.2f} (z={z_score:.1f})"
            )
        return score, reasons

    def _check_recipient_anomaly(
        self, txn: dict[str, Any], history: list[dict[str, Any]]
    ) -> tuple[float, list[str]]:
        recipient = txn.get("to") or txn.get("recipient")
        if not recipient:
            return 0.0, []

        known_recipients = {
            h.get("to") or h.get("recipient")
            for h in history
            if h.get("to") or h.get("recipient")
        }
        if recipient not in known_recipients:
            return 0.7, [f"Recipient {recipient[:16]}... has never been seen before."]
        return 0.0, []

    def _check_timing_anomaly(
        self, txn: dict[str, Any], history: list[dict[str, Any]]
    ) -> tuple[float, list[str]]:
        hour = txn.get("hour")
        if hour is None:
            return 0.0, []

        hist_hours = [h.get("hour") for h in history if h.get("hour") is not None]
        if len(hist_hours) < 5:
            return 0.0, []

        avg_hour = statistics.mean(hist_hours)
        stdev_hour = statistics.stdev(hist_hours) if len(hist_hours) > 1 else 4.0
        if stdev_hour == 0:
            stdev_hour = 2.0

        diff = min(abs(hour - avg_hour), 24 - abs(hour - avg_hour))
        z = diff / stdev_hour
        score = min(z / 3.0, 1.0)
        reasons: list[str] = []
        if score >= 0.5:
            reasons.append(f"Transaction at hour {hour} is unusual (typical: ~{avg_hour:.0f}h).")
        return score, reasons

    def _check_type_anomaly(
        self, txn: dict[str, Any], history: list[dict[str, Any]]
    ) -> tuple[float, list[str]]:
        txn_type = txn.get("type")
        if not txn_type:
            return 0.0, []

        type_counts: dict[str, int] = {}
        for h in history:
            t = h.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        if txn_type not in type_counts and len(type_counts) > 0:
            return 0.6, [f"Transaction type '{txn_type}' has never been performed before."]
        return 0.0, []

    # ── Correlation helpers ───────────────────────────────────────────

    def _find_temporal_clusters(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        correlations: list[dict[str, Any]] = []
        sorted_events = sorted(events, key=lambda e: e.get("timestamp", 0))
        window = self.config.get("temporal_cluster_window_seconds", 300)

        cluster: list[dict[str, Any]] = []
        for event in sorted_events:
            ts = event.get("timestamp", 0)
            if not cluster or ts - cluster[0].get("timestamp", 0) <= window:
                cluster.append(event)
            else:
                if len(cluster) >= 2:
                    correlations.append({
                        "events": [e.get("id", str(i)) for i, e in enumerate(cluster)],
                        "correlation_type": "temporal_cluster",
                        "strength": min(len(cluster) / 5.0, 1.0),
                        "description": f"{len(cluster)} events within {window}s window",
                    })
                cluster = [event]
        # Flush last cluster
        if len(cluster) >= 2:
            correlations.append({
                "events": [e.get("id", str(i)) for i, e in enumerate(cluster)],
                "correlation_type": "temporal_cluster",
                "strength": min(len(cluster) / 5.0, 1.0),
                "description": f"{len(cluster)} events within {window}s window",
            })
        return correlations

    def _find_category_cooccurrence(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        correlations: list[dict[str, Any]] = []
        from itertools import combinations

        cat_events: dict[str, list[str]] = {}
        for i, e in enumerate(events):
            cat = e.get("category", e.get("type", "unknown"))
            cat_events.setdefault(cat, []).append(e.get("id", str(i)))

        cats = list(cat_events.keys())
        for c1, c2 in combinations(cats, 2):
            overlap = min(len(cat_events[c1]), len(cat_events[c2]))
            if overlap >= 2:
                correlations.append({
                    "events": cat_events[c1][:3] + cat_events[c2][:3],
                    "correlation_type": "category_cooccurrence",
                    "strength": min(overlap / 5.0, 1.0),
                    "description": f"'{c1}' and '{c2}' frequently co-occur ({overlap} overlaps)",
                })
        return correlations

    def _find_value_correlations(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        correlations: list[dict[str, Any]] = []
        valued = [
            (e.get("id", str(i)), e.get("value", 0))
            for i, e in enumerate(events)
            if isinstance(e.get("value"), (int, float))
        ]
        if len(valued) < 3:
            return correlations

        values = [v for _, v in valued]
        mean = statistics.mean(values)
        if mean == 0:
            return correlations

        # Group by similar magnitude
        buckets: dict[int, list[str]] = {}
        for eid, v in valued:
            magnitude = int(v // (mean * 0.5)) if mean else 0
            buckets.setdefault(magnitude, []).append(eid)

        for _mag, ids in buckets.items():
            if len(ids) >= 2:
                correlations.append({
                    "events": ids[:5],
                    "correlation_type": "value_similarity",
                    "strength": min(len(ids) / 5.0, 1.0),
                    "description": f"{len(ids)} events with similar transaction values",
                })
        return correlations

    # ── Utility ───────────────────────────────────────────────────────

    def _filter_novel(self, patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return only patterns not already in _known_patterns."""
        known_descs = {p["description"] for p in self._known_patterns}
        return [p for p in patterns if p.get("description") not in known_descs]
