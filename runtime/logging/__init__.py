"""Structured logging utilities for 0pnMatrx.

Exposes a single public entry point, :func:`configure_logging`, which
installs a JSON or text formatter on the root logger, plus
:func:`set_request_id` / :func:`get_request_id` for propagating a
per-request trace ID through ``contextvars`` so log records from a
single HTTP request (or ReAct iteration, or tool call) all carry the
same identifier.

The JSON format is deliberately minimal and stable — any aggregator
that can parse newline-delimited JSON (Loki, CloudWatch, Datadog,
Google Cloud Logging, etc.) will be happy with it.
"""

from __future__ import annotations

from .json_formatter import (
    JsonFormatter,
    RequestIdFilter,
    configure_logging,
    generate_request_id,
    get_request_id,
    reset_request_id,
    set_request_id,
)

__all__ = [
    "JsonFormatter",
    "RequestIdFilter",
    "configure_logging",
    "generate_request_id",
    "get_request_id",
    "reset_request_id",
    "set_request_id",
]
