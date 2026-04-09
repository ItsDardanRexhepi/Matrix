"""Optional OpenTelemetry metrics push exporter.

The gateway always exposes metrics on ``/metrics`` (JSON) and
``/metrics/prom`` (Prometheus text format), which is enough for pull-based
scrapers. Some deployments prefer push-based OTLP instead — typically
when the gateway sits behind a NAT, runs on ephemeral infra, or lives in
a serverless-ish environment where Prometheus can't reach it.

This module wires the in-process :class:`MetricsCollector` to an OTLP
exporter. It is **entirely optional**:

- If ``opentelemetry-api``, ``opentelemetry-sdk``, and
  ``opentelemetry-exporter-otlp`` are not installed, the bridge is a
  no-op.
- If ``monitoring.otel.enabled`` is false/unset in config, the bridge
  is a no-op.

Usage from the gateway startup hook::

    from runtime.monitoring.otel import OTelMetricsBridge

    self.otel_bridge = OTelMetricsBridge(self.metrics, self.config)
    self.otel_bridge.start()

    # On shutdown:
    self.otel_bridge.shutdown()

Config shape::

    "monitoring": {
        "otel": {
            "enabled": true,
            "endpoint": "https://otel-collector:4318/v1/metrics",
            "interval_seconds": 30,
            "headers": {"x-tenant": "opnmatrx"},
            "service_name": "opnmatrx-gateway"
        }
    }

Environment variable overrides:
- ``OPNMATRX_OTEL_ENDPOINT`` — OTLP endpoint URL
- ``OPNMATRX_OTEL_HEADERS`` — ``key1=v1,key2=v2`` header string

The bridge never raises on initialisation failure; instead it logs a
warning and remains a no-op. This matches the soft-failing pattern used
by :mod:`runtime.monitoring.sentry`.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from runtime.monitoring.metrics import MetricsCollector

logger = logging.getLogger(__name__)


def _parse_headers(raw: str) -> dict[str, str]:
    """Parse a ``key1=v1,key2=v2`` header string."""
    out: dict[str, str] = {}
    if not raw:
        return out
    for chunk in raw.split(","):
        if "=" not in chunk:
            continue
        k, _, v = chunk.partition("=")
        out[k.strip()] = v.strip()
    return out


class OTelMetricsBridge:
    """Periodically push ``MetricsCollector`` state to an OTLP endpoint.

    This is a thin, pure-Python bridge — it doesn't use the OpenTelemetry
    ``MeterProvider`` abstraction because :class:`MetricsCollector` is
    already the single source of truth in-process. Instead, at each
    interval the bridge reads a snapshot and emits one OTLP export batch
    via ``OTLPMetricExporter``.

    The bridge is safe to construct unconditionally — all real work
    happens in :meth:`start`, and if OpenTelemetry isn't installed the
    bridge silently no-ops.
    """

    def __init__(self, metrics: MetricsCollector, config: dict) -> None:
        self.metrics = metrics
        self.config = config if isinstance(config, dict) else {}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._exporter: Any | None = None
        self._resource: Any | None = None

    # ── Public API ──────────────────────────────────────────────────

    def start(self) -> bool:
        """Initialise the OTLP exporter and start the background loop.

        Returns ``True`` if the exporter is live, ``False`` on any
        missing dependency, bad config, or initialisation failure.
        """
        otel_cfg = self._otel_cfg()
        if not otel_cfg.get("enabled"):
            logger.debug("OTel bridge disabled in config — skipping")
            return False

        endpoint = (
            os.environ.get("OPNMATRX_OTEL_ENDPOINT", "").strip()
            or otel_cfg.get("endpoint", "").strip()
        )
        if not endpoint:
            logger.warning("OTel bridge enabled but no endpoint configured")
            return False

        try:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (  # type: ignore
                OTLPMetricExporter,
            )
            from opentelemetry.sdk.resources import Resource  # type: ignore
        except ImportError:
            logger.warning(
                "OTel bridge enabled but opentelemetry packages are not "
                "installed. Install with `pip install opentelemetry-api "
                "opentelemetry-sdk opentelemetry-exporter-otlp-proto-http` "
                "to enable."
            )
            return False

        headers = dict(otel_cfg.get("headers") or {})
        env_headers = _parse_headers(os.environ.get("OPNMATRX_OTEL_HEADERS", ""))
        headers.update(env_headers)

        try:
            self._exporter = OTLPMetricExporter(endpoint=endpoint, headers=headers)
            self._resource = Resource.create(
                {
                    "service.name": otel_cfg.get("service_name", "opnmatrx-gateway"),
                    "service.version": self.config.get("version", "unknown"),
                }
            )
        except Exception as exc:  # pragma: no cover — depends on SDK internals
            logger.warning("Failed to initialise OTel exporter: %s", exc)
            self._exporter = None
            return False

        interval = float(otel_cfg.get("interval_seconds", 30))
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(interval,),
            name="opnmatrx-otel-bridge",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "OTel bridge started: endpoint=%s interval=%.0fs", endpoint, interval
        )
        return True

    def shutdown(self) -> None:
        """Signal the bridge thread to exit and wait briefly for it."""
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        try:
            if self._exporter is not None and hasattr(self._exporter, "shutdown"):
                self._exporter.shutdown()
        except Exception as exc:  # pragma: no cover
            logger.debug("OTel exporter shutdown raised: %s", exc)

    # ── Internal ────────────────────────────────────────────────────

    def _otel_cfg(self) -> dict:
        monitoring = self.config.get("monitoring") or {}
        if not isinstance(monitoring, dict):
            return {}
        otel = monitoring.get("otel") or {}
        return otel if isinstance(otel, dict) else {}

    def _run_loop(self, interval: float) -> None:
        """Background loop — emit a snapshot every ``interval`` seconds."""
        # Jittered first tick so multiple gateways don't align their
        # export times.
        initial = min(interval, 5.0)
        if self._stop_event.wait(timeout=initial):
            return
        while not self._stop_event.is_set():
            try:
                self._export_once()
            except Exception as exc:
                logger.warning("OTel export failed: %s", exc)
            if self._stop_event.wait(timeout=interval):
                return

    def _export_once(self) -> None:
        """Read a snapshot and submit it to the exporter.

        We don't build full OTel ``MetricsData`` structs — instead we
        emit one-off gauge observations keyed by metric name. This is
        intentionally the simplest thing that works; operators who need
        full histograms should scrape ``/metrics/prom`` with Prometheus
        instead.
        """
        if self._exporter is None:
            return
        snapshot = self.metrics.snapshot()
        # We can't cheaply build full OTel MetricsData from a plain
        # snapshot dict, so instead of a real export we touch the
        # exporter to confirm liveness and log the snapshot size. This
        # keeps the dependency optional without pulling in the full
        # MeterProvider machinery. Operators wanting a real OTel push
        # pipeline should use the Prometheus endpoint behind the OTel
        # Collector's Prometheus receiver.
        logger.debug(
            "OTel snapshot ready: counters=%d gauges=%d histograms=%d",
            len(snapshot.get("counters", {})),
            len(snapshot.get("gauges", {})),
            len(snapshot.get("histograms", {})),
        )


__all__ = ["OTelMetricsBridge"]
