"""Tests for runtime.monitoring.sentry.initialize_sentry.

Sentry is an optional dependency — the goal here is to confirm the
function is *honest*:

- It returns ``False`` and does not raise when no DSN is configured.
- It returns ``False`` and does not raise when ``sentry_sdk`` is not
  installed (simulated by monkey-patching ``sys.modules``).
- It returns ``True`` when a DSN is present and ``sentry_sdk.init``
  succeeds, passing the config values through intact.
- It returns ``False`` when ``sentry_sdk.init`` raises.
- Environment variable fallback (``SENTRY_DSN``) works when config is
  empty.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from runtime.monitoring.sentry import initialize_sentry


@pytest.fixture(autouse=True)
def clean_sentry_env(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("RELEASE", raising=False)
    # Remove any cached sentry_sdk module state so each test starts clean.
    yield


class TestInitializeSentry:
    def test_no_dsn_returns_false(self):
        assert initialize_sentry({}) is False

    def test_placeholder_dsn_returns_false(self):
        cfg = {"monitoring": {"sentry_dsn": "YOUR_SENTRY_DSN"}}
        assert initialize_sentry(cfg) is False

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("SENTRY_DSN", "https://real@sentry.io/1")
        fake_sdk = types.ModuleType("sentry_sdk")
        fake_sdk.init = MagicMock()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)
        assert initialize_sentry({}) is True
        fake_sdk.init.assert_called_once()  # type: ignore[attr-defined]
        kwargs = fake_sdk.init.call_args.kwargs  # type: ignore[attr-defined]
        assert kwargs["dsn"] == "https://real@sentry.io/1"

    def test_config_dsn_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("SENTRY_DSN", "https://envvar@sentry.io/1")
        fake_sdk = types.ModuleType("sentry_sdk")
        fake_sdk.init = MagicMock()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)
        cfg = {"monitoring": {"sentry_dsn": "https://config@sentry.io/1"}}
        assert initialize_sentry(cfg) is True
        kwargs = fake_sdk.init.call_args.kwargs  # type: ignore[attr-defined]
        assert kwargs["dsn"] == "https://config@sentry.io/1"

    def test_missing_sdk_returns_false(self, monkeypatch):
        # Force-fail the import by inserting a sentinel that raises on access.
        original = sys.modules.pop("sentry_sdk", None)
        monkeypatch.setitem(sys.modules, "sentry_sdk", None)
        try:
            cfg = {"monitoring": {"sentry_dsn": "https://real@sentry.io/1"}}
            assert initialize_sentry(cfg) is False
        finally:
            if original is not None:
                sys.modules["sentry_sdk"] = original
            else:
                sys.modules.pop("sentry_sdk", None)

    def test_passes_environment_and_release(self, monkeypatch):
        fake_sdk = types.ModuleType("sentry_sdk")
        fake_sdk.init = MagicMock()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)
        cfg = {
            "monitoring": {
                "sentry_dsn": "https://real@sentry.io/1",
                "environment": "production",
                "release": "0.5.0",
                "traces_sample_rate": 0.25,
            }
        }
        assert initialize_sentry(cfg) is True
        kwargs = fake_sdk.init.call_args.kwargs  # type: ignore[attr-defined]
        assert kwargs["environment"] == "production"
        assert kwargs["release"] == "0.5.0"
        assert kwargs["traces_sample_rate"] == 0.25
        assert kwargs["send_default_pii"] is False

    def test_init_exception_returns_false(self, monkeypatch):
        fake_sdk = types.ModuleType("sentry_sdk")
        fake_sdk.init = MagicMock(  # type: ignore[attr-defined]
            side_effect=RuntimeError("bad dsn")
        )
        monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)
        cfg = {"monitoring": {"sentry_dsn": "https://real@sentry.io/1"}}
        # Must not raise despite sentry_sdk.init blowing up.
        assert initialize_sentry(cfg) is False

    def test_non_dict_config(self):
        # Defensive: a stray non-dict shouldn't crash.
        assert initialize_sentry(None) is False  # type: ignore[arg-type]
