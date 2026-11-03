"""Sentry error reporting — optional, soft-failing.

If ``monitoring.sentry_dsn`` is set in config (or the ``SENTRY_DSN``
environment variable), unhandled exceptions on the gateway are reported
to Sentry. The ``sentry_sdk`` package is an optional dependency: if it
isn't installed we no-op rather than crashing.

This module exposes a single function, :func:`initialize_sentry`, which
should be called once at gateway startup.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _as_float(value: object, default: float, what: str) -> float:
    """A number the operator wrote, or the default and a warning saying so.

    ``float("fast")`` is a ValueError and ``float(None)`` is a TypeError, and
    either one used to leave this module before the ``try`` that is supposed to
    contain it. A telemetry setting is not worth a failed boot, but silently
    substituting a different value is its own lie, so the substitution is
    logged.
    """
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        logger.warning(
            "monitoring.%s is not a number (%r) — using %s", what, value, default)
        return default
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        logger.warning(
            "monitoring.%s is not finite (%r) — using %s", what, value, default)
        return default
    return parsed


def initialize_sentry(config: dict) -> bool:
    """Initialise Sentry if a DSN is configured.

    Returns ``True`` if Sentry was initialised, ``False`` otherwise. Never
    raises — Sentry being unavailable should never break startup.

    "Never raises" is a claim about the WHOLE function, and it used to cover
    only the part inside the ``try``. Everything that reads config sat above
    it: ``config.get("monitoring", {})`` answers ``None`` rather than ``{}``
    when the key is present with a null value, so the next ``.get`` was an
    AttributeError, and ``float(monitoring.get("traces_sample_rate", 0.1))``
    was a ValueError for any non-numeric setting. ``gateway/server.py`` calls
    this unwrapped, so either one aborted gateway construction — a misspelled
    telemetry option taking the platform down, which is the exact outcome the
    sentence promises cannot happen. The reads are now defensive, and the
    function ends in a total guard so the promise covers reads nobody has
    enumerated yet.
    """
    try:
        return _initialize_sentry(config)
    except Exception as exc:  # the promise, made total
        logger.warning("Sentry initialisation raised and was contained: %s", exc)
        return False


def _initialize_sentry(config: dict) -> bool:
    monitoring = config.get("monitoring") if isinstance(config, dict) else None
    if not isinstance(monitoring, dict):
        monitoring = {}
    dsn = monitoring.get("sentry_dsn") or os.environ.get("SENTRY_DSN", "")
    if not dsn or dsn.startswith("YOUR_"):
        logger.debug("Sentry DSN not configured — skipping Sentry init")
        return False

    try:
        import sentry_sdk  # type: ignore
    except ImportError:
        logger.warning(
            "sentry_sdk not installed — install with `pip install sentry-sdk` "
            "to enable error reporting"
        )
        return False

    environment = monitoring.get("environment", os.environ.get("ENVIRONMENT", "production"))
    release = monitoring.get("release", os.environ.get("RELEASE", "unknown"))
    traces_rate = _as_float(
        monitoring.get("traces_sample_rate", 0.1), 0.1, "traces_sample_rate")

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            traces_sample_rate=traces_rate,
            send_default_pii=False,
        )
        logger.info(
            "Sentry initialised (environment=%s release=%s traces_rate=%.2f)",
            environment, release, traces_rate,
        )
        return True
    except Exception as exc:
        logger.warning("Sentry initialisation failed: %s", exc)
        return False
