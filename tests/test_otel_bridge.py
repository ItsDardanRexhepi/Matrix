"""Tests for runtime.monitoring.otel.OTelMetricsBridge.

The bridge is an optional, soft-failing dependency. We confirm:

- Disabled config → ``start()`` returns False, no thread spawned.
- Enabled but no endpoint → False, warning logged.
- Enabled + endpoint but SDK missing → False, no crash.
- Header parsing handles missing / malformed inputs.
- ``shutdown()`` on an un-started bridge is a no-op.
"""

from __future__ import annotations

import pytest

from runtime.monitoring.metrics import MetricsCollector
from runtime.monitoring.otel import OTelMetricsBridge, _parse_headers


@pytest.fixture
def metrics():
    return MetricsCollector()


class TestParseHeaders:
    def test_empty(self):
        assert _parse_headers("") == {}

    def test_single(self):
        assert _parse_headers("k=v") == {"k": "v"}

    def test_multi(self):
        assert _parse_headers("a=1,b=2,c=3") == {"a": "1", "b": "2", "c": "3"}

    def test_whitespace_tolerant(self):
        assert _parse_headers(" a = 1 , b = 2 ") == {"a": "1", "b": "2"}

    def test_malformed_skipped(self):
        assert _parse_headers("valid=1,nobody,also=ok") == {
            "valid": "1",
            "also": "ok",
        }


class TestOTelBridgeLifecycle:
    def test_disabled_config_returns_false(self, metrics):
        bridge = OTelMetricsBridge(metrics, {})
        assert bridge.start() is False
        assert bridge._thread is None

    def test_explicitly_disabled_returns_false(self, metrics):
        cfg = {"monitoring": {"otel": {"enabled": False}}}
        bridge = OTelMetricsBridge(metrics, cfg)
        assert bridge.start() is False

    def test_enabled_without_endpoint_returns_false(self, metrics):
        cfg = {"monitoring": {"otel": {"enabled": True}}}
        bridge = OTelMetricsBridge(metrics, cfg)
        assert bridge.start() is False

    def test_non_dict_config_survives(self, metrics):
        bridge = OTelMetricsBridge(metrics, "not a dict")  # type: ignore[arg-type]
        assert bridge.start() is False

    def test_non_dict_monitoring_survives(self, metrics):
        bridge = OTelMetricsBridge(metrics, {"monitoring": "nope"})
        assert bridge.start() is False

    def test_shutdown_without_start_is_noop(self, metrics):
        bridge = OTelMetricsBridge(metrics, {})
        bridge.shutdown()  # should not raise

    def test_env_var_endpoint_override(self, metrics, monkeypatch):
        monkeypatch.setenv(
            "OPNMATRX_OTEL_ENDPOINT", "https://otel.example/v1/metrics"
        )
        # No opentelemetry packages installed by default → still returns False,
        # but reaches the import-guarded code path without raising.
        cfg = {"monitoring": {"otel": {"enabled": True}}}
        bridge = OTelMetricsBridge(metrics, cfg)
        # Expected False because opentelemetry is not a dev dep.
        result = bridge.start()
        assert result is False
