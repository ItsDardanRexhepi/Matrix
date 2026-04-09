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


def initialize_sentry(config: dict) -> bool:
    """Initialise Sentry if a DSN is configured.

    Returns ``True`` if Sentry was initialised, ``False`` otherwise. Never
    raises — Sentry being unavailable should never break startup.
    """
    monitoring = config.get("monitoring", {}) if isinstance(config, dict) else {}
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
    traces_rate = float(monitoring.get("traces_sample_rate", 0.1))

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
