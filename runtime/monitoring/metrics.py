"""In-process metrics collector for the 0pnMatrx gateway.

A deliberately small, dependency-free counter / gauge / histogram store.
The goal is operational visibility for the platform itself, not full
observability — point Prometheus or Grafana at ``/metrics`` if you want
real dashboards. Numbers reset on process restart.

Usage::

    metrics = MetricsCollector()
    metrics.incr("chat.requests")
    with metrics.timer("chat.latency"):
        result = await react_loop.run(...)
    metrics.observe("chat.tokens", result.usage.total_tokens)
    snapshot = metrics.snapshot()
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator


class _Histogram:
    """Cheap streaming histogram with min/max/avg/count and recent samples."""

    __slots__ = ("count", "total", "min", "max", "_recent")

    def __init__(self) -> None:
        self.count: int = 0
        self.total: float = 0.0
        self.min: float = float("inf")
        self.max: float = float("-inf")
        # Keep the last 1000 samples for percentile estimates.
        self._recent: list[float] = []

    def observe(self, value: float) -> None:
        self.count += 1
        self.total += value
        if value < self.min:
            self.min = value
        if value > self.max:
            self.max = value
        self._recent.append(value)
        if len(self._recent) > 1000:
            del self._recent[0:200]  # drop oldest 200 in one shot

    def snapshot(self) -> dict:
        if self.count == 0:
            return {"count": 0}
        avg = self.total / self.count
        sorted_vals = sorted(self._recent)
        n = len(sorted_vals)
        return {
            "count": self.count,
            "min": self.min,
            "max": self.max,
            "avg": round(avg, 6),
            "p50": sorted_vals[n // 2] if n else None,
            "p95": sorted_vals[min(n - 1, int(n * 0.95))] if n else None,
            "p99": sorted_vals[min(n - 1, int(n * 0.99))] if n else None,
        }


class MetricsCollector:
    """Thread-safe in-process metrics store.

    All numeric reads return a snapshot — never a live reference — so
    callers can inspect totals without worrying about concurrent
    mutation.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, _Histogram] = {}
        self._started_at = time.time()

    # ── Counters ───────────────────────────────────────────────────

    def incr(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def get_counter(self, name: str) -> int:
        with self._lock:
            return self._counters.get(name, 0)

    # ── Gauges ─────────────────────────────────────────────────────

    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def get_gauge(self, name: str) -> float | None:
        with self._lock:
            return self._gauges.get(name)

    # ── Histograms / timers ────────────────────────────────────────

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            hist = self._histograms.get(name)
            if hist is None:
                hist = _Histogram()
                self._histograms[name] = hist
            hist.observe(value)

    @contextmanager
    def timer(self, name: str) -> Iterator[None]:
        """Context manager that records elapsed seconds into a histogram."""
        start = time.perf_counter()
        try:
            yield
        finally:
            self.observe(name, time.perf_counter() - start)

    # ── Snapshot ───────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return a JSON-serialisable snapshot of all current metrics."""
        with self._lock:
            return {
                "uptime_seconds": round(time.time() - self._started_at, 3),
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    name: hist.snapshot()
                    for name, hist in self._histograms.items()
                },
            }

    def reset(self) -> None:
        """Wipe all metrics. Useful for tests."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._started_at = time.time()
