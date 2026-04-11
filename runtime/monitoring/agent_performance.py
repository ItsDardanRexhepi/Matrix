"""Agent performance monitoring for 0pnMatrx.

Tracks per-agent, per-turn metrics: response latency, tool call
success rate, model provider, task complexity, Morpheus triggers,
and conversation outcomes.  Provides aggregate stats and identifies
which model/configuration combinations produce the best results.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TurnMetrics:
    """Metrics for a single agent turn."""
    agent: str
    latency_ms: float
    tool_success_rate: float
    provider: str
    complexity: str
    morpheus_triggered: bool
    outcome: str
    timestamp: float = field(default_factory=time.time)


class AgentPerformanceMonitor:
    """Collects and aggregates agent performance metrics."""

    _instance: AgentPerformanceMonitor | None = None

    def __init__(self) -> None:
        self._turns: list[TurnMetrics] = []
        self._max_history = 10_000

    @classmethod
    def instance(cls) -> AgentPerformanceMonitor:
        """Return the singleton monitor instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def record_turn(
        self,
        agent: str,
        latency_ms: float,
        tool_success_rate: float,
        provider: str,
        complexity: str,
        morpheus_triggered: bool,
        outcome: str,
    ) -> None:
        """Record metrics for a single conversation turn."""
        metrics = TurnMetrics(
            agent=agent,
            latency_ms=latency_ms,
            tool_success_rate=tool_success_rate,
            provider=provider,
            complexity=complexity,
            morpheus_triggered=morpheus_triggered,
            outcome=outcome,
        )
        self._turns.append(metrics)

        # Trim oldest entries if over limit
        if len(self._turns) > self._max_history:
            self._turns = self._turns[-self._max_history:]

        logger.debug(
            "Turn recorded: agent=%s provider=%s complexity=%s latency=%.0fms outcome=%s",
            agent, provider, complexity, latency_ms, outcome,
        )

    async def get_agent_stats(self, agent: str, hours: int = 24) -> dict:
        """Return performance summary for a specific agent."""
        cutoff = time.time() - (hours * 3600)
        turns = [t for t in self._turns if t.agent == agent and t.timestamp >= cutoff]

        if not turns:
            return {"agent": agent, "turns": 0, "period_hours": hours}

        latencies = [t.latency_ms for t in turns]
        success_rates = [t.tool_success_rate for t in turns]
        providers: dict[str, int] = defaultdict(int)
        complexities: dict[str, int] = defaultdict(int)
        outcomes: dict[str, int] = defaultdict(int)
        morpheus_count = 0

        for t in turns:
            providers[t.provider] += 1
            complexities[t.complexity] += 1
            outcomes[t.outcome] += 1
            if t.morpheus_triggered:
                morpheus_count += 1

        return {
            "agent": agent,
            "turns": len(turns),
            "period_hours": hours,
            "latency": {
                "avg_ms": round(sum(latencies) / len(latencies), 1),
                "p50_ms": round(sorted(latencies)[len(latencies) // 2], 1),
                "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95)], 1),
                "max_ms": round(max(latencies), 1),
            },
            "tool_success_rate": round(sum(success_rates) / len(success_rates), 3),
            "providers": dict(providers),
            "complexities": dict(complexities),
            "outcomes": dict(outcomes),
            "morpheus_triggers": morpheus_count,
        }

    async def get_all_stats(self, hours: int = 24) -> dict:
        """Return performance summary for all agents."""
        agents = {t.agent for t in self._turns}
        result: dict[str, Any] = {}
        for agent in sorted(agents):
            result[agent] = await self.get_agent_stats(agent, hours)
        return result

    async def get_best_performing_config(self) -> dict:
        """Analyse which model/config combinations produce the best outcomes."""
        if not self._turns:
            return {"status": "insufficient_data", "turns_analysed": 0}

        # Group by provider and compute success metrics
        provider_stats: dict[str, dict] = defaultdict(
            lambda: {"turns": 0, "success": 0, "total_latency": 0.0}
        )
        for t in self._turns:
            ps = provider_stats[t.provider]
            ps["turns"] += 1
            if t.outcome == "success":
                ps["success"] += 1
            ps["total_latency"] += t.latency_ms

        results = {}
        for provider, ps in provider_stats.items():
            results[provider] = {
                "turns": ps["turns"],
                "success_rate": round(ps["success"] / ps["turns"], 3) if ps["turns"] else 0,
                "avg_latency_ms": round(ps["total_latency"] / ps["turns"], 1) if ps["turns"] else 0,
            }

        # Rank by success rate, then by latency
        ranked = sorted(
            results.items(),
            key=lambda x: (-x[1]["success_rate"], x[1]["avg_latency_ms"]),
        )

        return {
            "status": "ok",
            "turns_analysed": len(self._turns),
            "providers": results,
            "recommended": ranked[0][0] if ranked else None,
        }
