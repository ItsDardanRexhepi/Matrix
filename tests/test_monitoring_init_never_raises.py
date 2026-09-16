"""Both monitoring bridges promise never to raise. A config file can make them.

`initialize_sentry` says "Never raises — Sentry being unavailable should never
break startup", and the OTel module says "The bridge never raises on
initialisation failure; instead it logs a warning and remains a no-op". Both
sentences are about the same risk: telemetry is an optional extra, and an
operator who misconfigures it should get no telemetry, not a gateway that
refuses to come up.

Both were false, and in the same shape — the guards were inside a `try`, the
config reads were outside it:

  * `config.get("monitoring", {})` returns `None`, not `{}`, when the key is
    present with a null value, so the next `.get` is an AttributeError;
  * `float(cfg.get("traces_sample_rate", 0.1))` and
    `float(otel_cfg.get("interval_seconds", 30))` raise ValueError on any
    non-numeric value;
  * `otel_cfg.get("endpoint", "").strip()` raises AttributeError on a null
    endpoint, because the default only applies to a MISSING key;
  * `dict(otel_cfg.get("headers") or {})` raises on a non-mapping.

`gateway/server.py` calls `initialize_sentry(self.config)` unwrapped, so a
sentry raise aborts gateway construction — exactly what the docstring says
cannot happen. These are the values that got there.
"""

from __future__ import annotations

import sys
import types

import pytest

from runtime.monitoring.metrics import MetricsCollector
from runtime.monitoring.otel import OTelMetricsBridge
from runtime.monitoring.sentry import initialize_sentry


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("SENTRY_DSN", "ENVIRONMENT", "RELEASE",
                "MATRIX_OTEL_ENDPOINT", "MATRIX_OTEL_HEADERS"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def _fake_otel_sdk(monkeypatch):
    """Stand in for the opentelemetry packages, which are not dev deps.

    §CT — without this, `start()` returns False because the IMPORT failed, and
    a test asserting "did not raise" would pass without ever reaching the
    config reads it is about. The stub puts the interval and header reads back
    on the executed path.
    """
    exporter_mod = types.ModuleType(
        "opentelemetry.exporter.otlp.proto.http.metric_exporter")
    exporter_mod.OTLPMetricExporter = (  # type: ignore[attr-defined]
        lambda endpoint, headers: object())
    resources_mod = types.ModuleType("opentelemetry.sdk.resources")
    resources_mod.Resource = type(  # type: ignore[attr-defined]
        "Resource", (), {"create": staticmethod(lambda attrs: attrs)})
    for name in ("opentelemetry", "opentelemetry.exporter",
                 "opentelemetry.exporter.otlp", "opentelemetry.exporter.otlp.proto",
                 "opentelemetry.exporter.otlp.proto.http", "opentelemetry.sdk"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(
        sys.modules, "opentelemetry.exporter.otlp.proto.http.metric_exporter",
        exporter_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.resources", resources_mod)


@pytest.fixture
def _no_sentry_sdk(monkeypatch):
    """Make `import sentry_sdk` succeed with an init that records its kwargs.

    The config reads that raise happen BEFORE the import is used, so the
    failure has to be reachable whether or not the real SDK is installed.
    """
    mod = types.ModuleType("sentry_sdk")
    calls = []
    mod.init = lambda **kw: calls.append(kw)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentry_sdk", mod)
    return calls


# ── sentry ──────────────────────────────────────────────────────────────────

def test_sentry_survives_a_null_monitoring_block():
    # `"monitoring": null` is a one-character edit in a config file.
    assert initialize_sentry({"monitoring": None}) is False


def test_sentry_survives_a_non_mapping_monitoring_block():
    assert initialize_sentry({"monitoring": ["sentry_dsn"]}) is False


@pytest.mark.parametrize("rate", ["fast", None, [], {"a": 1}])
def test_sentry_survives_a_non_numeric_traces_rate(_no_sentry_sdk, rate):
    cfg = {"monitoring": {"sentry_dsn": "https://k@example.test/1",
                          "traces_sample_rate": rate}}
    # It may decline (False) or fall back to the default and initialise — what
    # it may NOT do is raise into the gateway's constructor.
    assert initialize_sentry(cfg) in (True, False)


def test_sentry_a_valid_rate_is_still_passed_through(_no_sentry_sdk):
    # The guard must not become "ignore the operator's setting".
    cfg = {"monitoring": {"sentry_dsn": "https://k@example.test/1",
                          "traces_sample_rate": 0.42}}
    assert initialize_sentry(cfg) is True
    assert _no_sentry_sdk[-1]["traces_sample_rate"] == pytest.approx(0.42)


# ── otel ────────────────────────────────────────────────────────────────────

def _bridge(cfg):
    return OTelMetricsBridge(config=cfg, metrics=MetricsCollector())


def test_otel_survives_a_null_endpoint():
    # The `""` default applies only to a MISSING key, never to a null value.
    assert _bridge({"monitoring": {"otel": {"enabled": True,
                                            "endpoint": None}}}).start() is False


def test_otel_survives_a_non_string_endpoint():
    assert _bridge({"monitoring": {"otel": {"enabled": True,
                                            "endpoint": 8080}}}).start() is False


@pytest.mark.parametrize("interval", ["thirty", None, [], {"s": 1}])
def test_otel_survives_a_non_numeric_interval(interval, _fake_otel_sdk):
    bridge = _bridge({"monitoring": {"otel": {
        "enabled": True, "endpoint": "https://collector.test/v1/metrics",
        "interval_seconds": interval}}})
    try:
        assert bridge.start() in (True, False)
    finally:
        bridge.shutdown()


@pytest.mark.parametrize("headers", ["x-tenant=matrix", 7, [1, 2, 3]])
def test_otel_survives_non_mapping_headers(headers, _fake_otel_sdk):
    bridge = _bridge({"monitoring": {"otel": {
        "enabled": True, "endpoint": "https://collector.test/v1/metrics",
        "headers": headers}}})
    try:
        assert bridge.start() in (True, False)
    finally:
        bridge.shutdown()


def test_otel_survives_a_null_monitoring_block():
    assert _bridge({"monitoring": None}).start() is False


def test_otel_a_valid_interval_still_starts_the_loop(_fake_otel_sdk):
    # The guard must not become "never start". With a usable SDK and a usable
    # interval the bridge must still come up, or the checks above would pass
    # against a bridge that simply stopped working.
    bridge = _bridge({"monitoring": {"otel": {
        "enabled": True, "endpoint": "https://collector.test/v1/metrics",
        "interval_seconds": 5, "headers": {"x-tenant": "matrix"}}}})
    try:
        assert bridge.start() is True
    finally:
        bridge.shutdown()
