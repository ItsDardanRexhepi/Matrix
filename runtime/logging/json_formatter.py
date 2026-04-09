"""JSON-formatted logging with per-request correlation IDs.

Every log record emitted through the configured root logger is written
as a single line of JSON containing:

- ``timestamp`` — ISO 8601 UTC
- ``level`` — log level name (``INFO``, ``WARNING``, ...)
- ``logger`` — dotted logger name
- ``message`` — the rendered log message
- ``request_id`` — the contextvar-scoped correlation ID, if set
- ``exception`` — stringified traceback, if the record carries one
- any extra keyword arguments passed via ``logger.info("...", extra={...})``

The request ID is propagated via :mod:`contextvars` so it survives
``asyncio`` task boundaries without threading it through every call
site. Middleware calls :func:`set_request_id` at the top of each HTTP
request and :func:`reset_request_id` at the end.
"""

from __future__ import annotations

import contextvars
import datetime
import json
import logging
import secrets
import sys
from typing import Any


_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "opnmatrx_request_id", default=""
)


def generate_request_id() -> str:
    """Return a fresh, URL-safe request ID (~22 characters)."""
    return secrets.token_urlsafe(16)


def set_request_id(request_id: str | None = None) -> contextvars.Token[str]:
    """Bind *request_id* (or a freshly generated one) to the current context.

    Returns the :class:`contextvars.Token` so the caller can later
    reset the contextvar with :func:`reset_request_id`.
    """
    if not request_id:
        request_id = generate_request_id()
    return _REQUEST_ID.set(request_id)


def get_request_id() -> str:
    """Return the request ID bound to the current context, or ``""``."""
    return _REQUEST_ID.get()


def reset_request_id(token: contextvars.Token[str]) -> None:
    """Undo a previous :func:`set_request_id` call."""
    _REQUEST_ID.reset(token)


# Attributes that :class:`logging.LogRecord` sets by default — anything
# NOT in this set is treated as an ``extra=`` kwarg from the caller and
# is copied into the JSON payload.
_DEFAULT_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        # our own filter adds these:
        "request_id",
    }
)


class RequestIdFilter(logging.Filter):
    """Inject the context-bound request ID onto every ``LogRecord``.

    Installing this filter means plain string formatters can reference
    ``%(request_id)s`` without blowing up on records that happen to be
    emitted outside of a request scope.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        record.request_id = get_request_id()
        return True


class JsonFormatter(logging.Formatter):
    """Emit each log record as a newline-delimited JSON object."""

    def __init__(self, *, service: str = "opnmatrx-gateway") -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.datetime.fromtimestamp(
                record.created, tz=datetime.timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": self.service,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", "") or get_request_id()
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Copy any ``extra=`` fields the caller attached.
        for key, value in record.__dict__.items():
            if key in _DEFAULT_RECORD_ATTRS:
                continue
            if key.startswith("_"):
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                payload[key] = repr(value)
            else:
                payload[key] = value
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def configure_logging(
    *,
    level: int | str = logging.INFO,
    json_format: bool = True,
    service: str = "opnmatrx-gateway",
) -> None:
    """Configure the root logger for structured or text output.

    Call once at process startup. Safe to call more than once — the
    existing handlers are replaced rather than accumulated.
    """
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    if json_format:
        handler.setFormatter(JsonFormatter(service=service))
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt=(
                    "%(asctime)s [%(name)s] %(levelname)s "
                    "req=%(request_id)s: %(message)s"
                )
            )
        )
    root.addHandler(handler)

    # Quiet down the noisier third-party loggers so the gateway logs
    # stay readable. Callers can still opt in by explicitly raising the
    # level on these loggers after configure_logging().
    for noisy in ("aiohttp.access", "aiohttp.server", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
