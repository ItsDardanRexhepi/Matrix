"""Tests for runtime.monitoring.metrics.MetricsCollector."""

from runtime.monitoring.metrics import MetricsCollector


class TestCounters:
    def test_incr_defaults_to_one(self):
        m = MetricsCollector()
        m.incr("requests")
        m.incr("requests")
        assert m.get_counter("requests") == 2

    def test_incr_custom_value(self):
        m = MetricsCollector()
        m.incr("bytes", 512)
        assert m.get_counter("bytes") == 512


class TestGauges:
    def test_gauge_set_and_read(self):
        m = MetricsCollector()
        m.gauge("queue_depth", 7)
        assert m.get_gauge("queue_depth") == 7

    def test_gauge_overwrites(self):
        m = MetricsCollector()
        m.gauge("temp", 10)
        m.gauge("temp", 20)
        assert m.get_gauge("temp") == 20


class TestHistogram:
    def test_observe_populates_snapshot(self):
        m = MetricsCollector()
        for v in range(1, 101):
            m.observe("latency", v)
        snap = m.snapshot()["histograms"]["latency"]
        assert snap["count"] == 100
        assert snap["min"] == 1
        assert snap["max"] == 100
        assert snap["p50"] is not None
        assert snap["p95"] is not None
        assert snap["p99"] is not None

    def test_timer_records_elapsed(self):
        m = MetricsCollector()
        with m.timer("work"):
            pass
        snap = m.snapshot()["histograms"]["work"]
        assert snap["count"] == 1
        assert snap["min"] >= 0


class TestPrometheusFormat:
    def test_counter_emitted_as_total(self):
        m = MetricsCollector()
        m.incr("chat.requests", 5)
        out = m.format_prometheus()
        assert "# TYPE chat_requests_total counter" in out
        assert "chat_requests_total 5" in out

    def test_gauge_emitted(self):
        m = MetricsCollector()
        m.gauge("backlog", 42)
        out = m.format_prometheus()
        assert "# TYPE backlog gauge" in out
        assert "backlog 42" in out

    def test_histogram_emitted_as_summary(self):
        m = MetricsCollector()
        for v in range(1, 101):
            m.observe("chat.latency", float(v))
        out = m.format_prometheus()
        assert "# TYPE chat_latency summary" in out
        assert 'chat_latency{quantile="0.5"}' in out
        assert 'chat_latency{quantile="0.95"}' in out
        assert 'chat_latency{quantile="0.99"}' in out
        assert "chat_latency_count 100" in out
        assert "chat_latency_min" in out
        assert "chat_latency_max" in out

    def test_name_sanitisation(self):
        m = MetricsCollector()
        m.incr("weird-metric.name/with-chars", 1)
        out = m.format_prometheus()
        assert "weird_metric_name_with_chars_total 1" in out

    def test_uptime_always_present(self):
        m = MetricsCollector()
        out = m.format_prometheus()
        assert "# TYPE opnmatrx_uptime_seconds gauge" in out
        assert "opnmatrx_uptime_seconds " in out

    def test_empty_histogram_is_skipped(self):
        m = MetricsCollector()
        m.incr("requests")
        out = m.format_prometheus()
        # Only the counter + uptime, no histogram lines.
        assert "summary" not in out

    def test_output_ends_with_newline(self):
        m = MetricsCollector()
        out = m.format_prometheus()
        assert out.endswith("\n")


class TestReset:
    def test_reset_clears_everything(self):
        m = MetricsCollector()
        m.incr("a")
        m.gauge("b", 1)
        m.observe("c", 1)
        m.reset()
        snap = m.snapshot()
        assert snap["counters"] == {}
        assert snap["gauges"] == {}
        assert snap["histograms"] == {}
