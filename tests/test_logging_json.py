"""Tests for runtime.logging.json_formatter.

Covers the three things the gateway depends on:

1. ``JsonFormatter.format`` produces a single JSON object per record,
   with the documented fields plus any ``extra=`` attributes the caller
   attached.
2. ``set_request_id`` / ``get_request_id`` are async-safe via
   ``contextvars`` and propagate through the formatter.
3. ``configure_logging`` installs the handler, clears previous ones,
   and applies the request ID filter so plain formatters can reference
   ``%(request_id)s`` without KeyError.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging

import pytest

from runtime.logging import (
    JsonFormatter,
    RequestIdFilter,
    configure_logging,
    generate_request_id,
    get_request_id,
    reset_request_id,
    set_request_id,
)
from runtime.logging.json_formatter import _REQUEST_ID


def _make_record(
    *,
    name: str = "test",
    level: int = logging.INFO,
    msg: str = "hello",
    extra: dict | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    if extra:
        for key, value in extra.items():
            setattr(record, key, value)
    return record


class TestGenerateRequestId:
    def test_returns_nonempty_string(self):
        rid = generate_request_id()
        assert isinstance(rid, str)
        assert len(rid) >= 16

    def test_ids_are_unique(self):
        ids = {generate_request_id() for _ in range(100)}
        assert len(ids) == 100


class TestRequestIdContextVar:
    def test_default_is_empty(self):
        # Reset to default in case another test leaked.
        token = _REQUEST_ID.set("")
        try:
            assert get_request_id() == ""
        finally:
            _REQUEST_ID.reset(token)

    def test_set_and_get(self):
        token = set_request_id("req-123")
        try:
            assert get_request_id() == "req-123"
        finally:
            reset_request_id(token)

    def test_reset_restores_previous(self):
        outer = set_request_id("outer")
        try:
            inner = set_request_id("inner")
            assert get_request_id() == "inner"
            reset_request_id(inner)
            assert get_request_id() == "outer"
        finally:
            reset_request_id(outer)

    def test_set_with_none_generates_fresh_id(self):
        token = set_request_id(None)
        try:
            assert get_request_id() != ""
        finally:
            reset_request_id(token)

    @pytest.mark.asyncio
    async def test_survives_task_boundary(self):
        token = set_request_id("task-id")
        try:
            async def inner() -> str:
                return get_request_id()
            assert await inner() == "task-id"
        finally:
            reset_request_id(token)

    @pytest.mark.asyncio
    async def test_concurrent_tasks_isolated(self):
        """Two tasks with different IDs do not see each other's value."""
        results: dict[str, str] = {}

        async def worker(tag: str) -> None:
            token = set_request_id(tag)
            try:
                await asyncio.sleep(0.01)
                results[tag] = get_request_id()
            finally:
                reset_request_id(token)

        await asyncio.gather(worker("alpha"), worker("beta"), worker("gamma"))
        assert results == {"alpha": "alpha", "beta": "beta", "gamma": "gamma"}


class TestJsonFormatter:
    def test_basic_record(self):
        fmt = JsonFormatter()
        record = _make_record(msg="hello world")
        line = fmt.format(record)
        parsed = json.loads(line)
        assert parsed["message"] == "hello world"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test"
        assert parsed["service"] == "opnmatrx-gateway"
        assert "timestamp" in parsed

    def test_custom_service_name(self):
        fmt = JsonFormatter(service="custom-svc")
        line = fmt.format(_make_record())
        parsed = json.loads(line)
        assert parsed["service"] == "custom-svc"

    def test_extra_fields_copied(self):
        fmt = JsonFormatter()
        record = _make_record(
            extra={
                "http_method": "POST",
                "http_status": 200,
                "duration_ms": 42.5,
            }
        )
        line = fmt.format(record)
        parsed = json.loads(line)
        assert parsed["http_method"] == "POST"
        assert parsed["http_status"] == 200
        assert parsed["duration_ms"] == 42.5

    def test_request_id_injected_from_context(self):
        fmt = JsonFormatter()
        token = set_request_id("fmt-test-id")
        try:
            line = fmt.format(_make_record())
            parsed = json.loads(line)
            assert parsed["request_id"] == "fmt-test-id"
        finally:
            reset_request_id(token)

    def test_no_request_id_when_unset(self):
        fmt = JsonFormatter()
        # Ensure nothing is set.
        token = _REQUEST_ID.set("")
        try:
            line = fmt.format(_make_record())
            parsed = json.loads(line)
            assert "request_id" not in parsed
        finally:
            _REQUEST_ID.reset(token)

    def test_exception_is_included(self):
        fmt = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys as _s
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname=__file__, lineno=1,
                msg="oops", args=(), exc_info=_s.exc_info(),
            )
        line = fmt.format(record)
        parsed = json.loads(line)
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]
        assert "boom" in parsed["exception"]

    def test_non_json_serializable_extra_becomes_repr(self):
        fmt = JsonFormatter()

        class Weird:
            def __repr__(self) -> str:
                return "<weird>"

        record = _make_record(extra={"thing": Weird()})
        line = fmt.format(record)
        parsed = json.loads(line)
        assert parsed["thing"] == "<weird>"

    def test_output_is_single_line(self):
        fmt = JsonFormatter()
        record = _make_record(msg="multi\nline\nmessage")
        line = fmt.format(record)
        # Record message is preserved intact inside JSON but the
        # formatter output itself must be one line (newline-delimited
        # JSON aggregators depend on this).
        assert "\n" not in line


class TestRequestIdFilter:
    def test_filter_injects_attribute(self):
        filt = RequestIdFilter()
        record = _make_record()
        token = set_request_id("filter-test")
        try:
            assert filt.filter(record) is True
            assert record.request_id == "filter-test"
        finally:
            reset_request_id(token)


class TestConfigureLogging:
    def test_json_output_is_parseable(self, capsys):
        configure_logging(level=logging.INFO, json_format=True)
        logger = logging.getLogger("test.configure")
        token = set_request_id("cfg-id")
        try:
            logger.info("test-message", extra={"kind": "smoke"})
        finally:
            reset_request_id(token)
        captured = capsys.readouterr().out.strip()
        # A single JSON object on stdout.
        payload = json.loads(captured)
        assert payload["message"] == "test-message"
        assert payload["request_id"] == "cfg-id"
        assert payload["kind"] == "smoke"
        # Restore default config so other tests aren't affected.
        configure_logging(level=logging.WARNING, json_format=False)

    def test_text_format_includes_request_id(self, capsys):
        configure_logging(level=logging.INFO, json_format=False)
        logger = logging.getLogger("test.text")
        token = set_request_id("text-id")
        try:
            logger.info("hello text")
        finally:
            reset_request_id(token)
        captured = capsys.readouterr().out
        assert "hello text" in captured
        assert "req=text-id" in captured
        configure_logging(level=logging.WARNING, json_format=False)

    def test_idempotent_reconfigure(self, capsys):
        configure_logging(level=logging.INFO, json_format=True)
        configure_logging(level=logging.INFO, json_format=True)
        # Only one handler installed even after double-configure.
        handlers = logging.getLogger().handlers
        assert len(handlers) == 1
        configure_logging(level=logging.WARNING, json_format=False)
