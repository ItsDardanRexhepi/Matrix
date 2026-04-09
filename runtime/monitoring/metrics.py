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

    # ── Prometheus text format ─────────────────────────────────────

    def format_prometheus(self) -> str:
        """Serialise the current snapshot to the Prometheus text format.

        Produces a string compatible with Prometheus scrape targets (no
        dependency on the ``prometheus_client`` library). Metric names
        are sanitised: dots and dashes become underscores so ``chat.
        requests`` -> ``chat_requests``. Histograms expose
        ``_count``, ``_sum``, ``_min``, ``_max``, ``_avg``, and
        approximate quantiles ``{quantile="0.5|0.95|0.99"}``.
        """
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            histograms = {name: hist.snapshot() for name, hist in self._histograms.items()}
            uptime = round(time.time() - self._started_at, 3)

        lines: list[str] = []

        def prom_name(name: str) -> str:
            # Prometheus allows [a-zA-Z_:][a-zA-Z0-9_:]*. Replace the
            # common separators our codebase uses.
            cleaned = []
            for ch in name:
                if ch.isalnum() or ch in "_:":
                    cleaned.append(ch)
                else:
                    cleaned.append("_")
            return "".join(cleaned)

        # Uptime gauge (Prometheus convention: process_* not quite
        # right since we reset the clock on process start — we publish
        # our own name to avoid confusion.)
        lines.append("# HELP opnmatrx_uptime_seconds Gateway uptime in seconds.")
        lines.append("# TYPE opnmatrx_uptime_seconds gauge")
        lines.append(f"opnmatrx_uptime_seconds {uptime}")

        # Counters
        for name, value in sorted(counters.items()):
            metric = prom_name(name) + "_total"
            lines.append(f"# HELP {metric} Counter: {name}")
            lines.append(f"# TYPE {metric} counter")
            lines.append(f"{metric} {value}")

        # Gauges
        for name, value in sorted(gauges.items()):
            metric = prom_name(name)
            lines.append(f"# HELP {metric} Gauge: {name}")
            lines.append(f"# TYPE {metric} gauge")
            lines.append(f"{metric} {value}")

        # Histograms as summaries (we don't expose buckets, only
        # streaming quantiles).
        for name, snap in sorted(histograms.items()):
            metric = prom_name(name)
            if snap.get("count", 0) == 0:
                continue
            lines.append(f"# HELP {metric} Summary: {name}")
            lines.append(f"# TYPE {metric} summary")
            for q in ("p50", "p95", "p99"):
                if snap.get(q) is not None:
                    qlabel = {"p50": "0.5", "p95": "0.95", "p99": "0.99"}[q]
                    lines.append(f'{metric}{{quantile="{qlabel}"}} {snap[q]}')
            lines.append(f"{metric}_count {snap['count']}")
            lines.append(f"{metric}_sum {round(snap.get('avg', 0) * snap['count'], 6)}")
            if snap.get("min") not in (None, float("inf")):
                lines.append(f"{metric}_min {snap['min']}")
            if snap.get("max") not in (None, float("-inf")):
                lines.append(f"{metric}_max {snap['max']}")

        lines.append("")  # trailing newline
        return "\n".join(lines)
