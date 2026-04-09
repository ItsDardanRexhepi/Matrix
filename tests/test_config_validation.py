"""Tests for runtime.config.validation.

Covers the two public entry points used by ``gateway.server.load_config``:

1. :func:`enforce_env_only_secrets` — env vars win, plaintext secrets in
   the JSON file are stripped in strict mode, required-in-prod entries
   raise when absent.
2. :func:`validate_config` — walks a config dict and returns a report
   with every problem listed.

No network I/O, no filesystem side-effects.
"""

from __future__ import annotations

import os

import pytest

from runtime.config.validation import (
    ConfigValidationError,
    ValidationReport,
    _is_placeholder,
    enforce_env_only_secrets,
    is_production_mode,
    validate_config,
)


@pytest.fixture
def minimal_config():
    """A config that passes validation in lenient (dev) mode."""
    return {
        "platform": "0pnMatrx",
        "gateway": {
            "host": "127.0.0.1",
            "port": 18790,
            "cors_origins": ["*"],
        },
        "model": {
            "provider": "ollama",
            "providers": {
                "ollama": {"base_url": "http://localhost:11434"},
            },
        },
        "database": {"path": "data/openmatrix.db"},
        "blockchain": {
            "rpc_url": "YOUR_BASE_RPC_URL",
            "paymaster_private_key": "YOUR_KEY",
        },
    }


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Every test runs with a clean slate for OPNMATRX_ENV and secret env vars."""
    for var in (
        "OPNMATRX_ENV",
        "OPENMATRIX_PAYMASTER_KEY",
        "OPENMATRIX_DEMO_WALLET_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "NVIDIA_API_KEY",
        "GOOGLE_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "SENTRY_DSN",
        "OPENMATRIX_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


class TestIsProductionMode:
    def test_unset_is_not_production(self):
        assert is_production_mode() is False

    def test_development_is_not_production(self, monkeypatch):
        monkeypatch.setenv("OPNMATRX_ENV", "development")
        assert is_production_mode() is False

    def test_production_lowercase(self, monkeypatch):
        monkeypatch.setenv("OPNMATRX_ENV", "production")
        assert is_production_mode() is True

    def test_production_uppercase(self, monkeypatch):
        monkeypatch.setenv("OPNMATRX_ENV", "PRODUCTION")
        assert is_production_mode() is True

    def test_production_with_whitespace(self, monkeypatch):
        monkeypatch.setenv("OPNMATRX_ENV", "  production  ")
        assert is_production_mode() is True


class TestPlaceholderDetection:
    def test_none_is_placeholder(self):
        assert _is_placeholder(None) is True

    def test_empty_string_is_placeholder(self):
        assert _is_placeholder("") is True

    def test_zero_address_is_placeholder(self):
        assert _is_placeholder("0x0000000000000000000000000000000000000000") is True

    def test_your_prefix(self):
        assert _is_placeholder("YOUR_API_KEY") is True

    def test_change_me_prefix(self):
        assert _is_placeholder("CHANGE_ME_PLEASE") is True

    def test_replace_prefix(self):
        assert _is_placeholder("REPLACE_WITH_REAL") is True

    def test_real_value_is_not_placeholder(self):
        assert _is_placeholder("sk-proj-1234567890abcdef") is False

    def test_integer_is_not_placeholder(self):
        assert _is_placeholder(18790) is False


class TestEnforceEnvOnlySecrets:
    def test_env_var_wins_over_config_value(self, monkeypatch, minimal_config):
        minimal_config["blockchain"]["paymaster_private_key"] = "from-config"
        monkeypatch.setenv("OPENMATRIX_PAYMASTER_KEY", "from-env")
        result = enforce_env_only_secrets(minimal_config, strict=False)
        assert result["blockchain"]["paymaster_private_key"] == "from-env"

    def test_lenient_mode_strips_placeholder(self, minimal_config):
        result = enforce_env_only_secrets(minimal_config, strict=False)
        # placeholder 'YOUR_KEY' removed, not present
        assert "paymaster_private_key" not in result["blockchain"]

    def test_lenient_mode_preserves_non_placeholder(self, minimal_config):
        minimal_config["blockchain"]["paymaster_private_key"] = "0xdeadbeef"
        result = enforce_env_only_secrets(minimal_config, strict=False)
        assert result["blockchain"]["paymaster_private_key"] == "0xdeadbeef"

    def test_strict_mode_strips_plaintext_secret(self, minimal_config):
        minimal_config["blockchain"]["demo_wallet_private_key"] = "0xleaked"
        # Required paymaster key provided via env so strict mode doesn't abort.
        os.environ["OPENMATRIX_PAYMASTER_KEY"] = "0xreal"
        try:
            result = enforce_env_only_secrets(minimal_config, strict=True)
            # Plaintext demo wallet stripped because env var wasn't set.
            assert "demo_wallet_private_key" not in result["blockchain"]
        finally:
            del os.environ["OPENMATRIX_PAYMASTER_KEY"]

    def test_strict_mode_raises_when_required_secret_missing(self, minimal_config):
        with pytest.raises(ConfigValidationError) as exc_info:
            enforce_env_only_secrets(minimal_config, strict=True)
        assert "OPENMATRIX_PAYMASTER_KEY" in str(exc_info.value)

    def test_strict_mode_accepts_required_from_env(self, monkeypatch, minimal_config):
        monkeypatch.setenv("OPENMATRIX_PAYMASTER_KEY", "0xrealkey")
        result = enforce_env_only_secrets(minimal_config, strict=True)
        assert result["blockchain"]["paymaster_private_key"] == "0xrealkey"

    def test_non_required_secret_missing_is_fine(self, minimal_config):
        # OPENAI_API_KEY not set, not required — no raise, just gone.
        result = enforce_env_only_secrets(minimal_config, strict=False)
        assert "api_key" not in result["model"]["providers"].get("openai", {})


class TestValidateConfig:
    def test_minimal_config_is_ok(self, minimal_config):
        report = validate_config(minimal_config, strict=False)
        assert not report.has_errors

    def test_missing_platform_is_error(self, minimal_config):
        del minimal_config["platform"]
        report = validate_config(minimal_config, strict=False)
        assert report.has_errors
        assert any(i.path == "platform" for i in report.errors)

    def test_placeholder_required_field_is_error(self, minimal_config):
        minimal_config["database"]["path"] = "YOUR_DB_PATH"
        report = validate_config(minimal_config, strict=False)
        assert any(i.path == "database.path" for i in report.errors)

    def test_invalid_port_number_is_error(self, minimal_config):
        minimal_config["gateway"]["port"] = 99999
        report = validate_config(minimal_config, strict=False)
        assert any(i.path == "gateway.port" for i in report.errors)

    def test_non_integer_port_is_error(self, minimal_config):
        minimal_config["gateway"]["port"] = "not-a-port"
        report = validate_config(minimal_config, strict=False)
        assert any(i.path == "gateway.port" for i in report.errors)

    def test_negative_rate_limit_is_error(self, minimal_config):
        minimal_config["gateway"]["rate_limit_rpm"] = -10
        report = validate_config(minimal_config, strict=False)
        assert any(i.path == "gateway.rate_limit_rpm" for i in report.errors)

    def test_cors_origins_must_be_list(self, minimal_config):
        minimal_config["gateway"]["cors_origins"] = "*"
        report = validate_config(minimal_config, strict=False)
        assert any(i.path == "gateway.cors_origins" for i in report.errors)

    def test_strict_mode_requires_api_key(self, minimal_config):
        report = validate_config(minimal_config, strict=True)
        assert any(i.path == "gateway.api_key" for i in report.errors)

    def test_strict_mode_accepts_api_key(self, minimal_config):
        minimal_config["gateway"]["api_key"] = "real-secret"
        minimal_config["gateway"]["tls_terminated_externally"] = True
        report = validate_config(minimal_config, strict=True)
        assert not any(i.path == "gateway.api_key" for i in report.errors)

    def test_strict_mode_warns_on_missing_tls_ack(self, minimal_config):
        minimal_config["gateway"]["api_key"] = "real-secret"
        report = validate_config(minimal_config, strict=True)
        assert any(
            i.path == "gateway.tls_terminated_externally" for i in report.warnings
        )

    def test_no_usable_provider_is_warning(self, minimal_config):
        minimal_config["model"]["providers"] = {
            "openai": {"api_key": "YOUR_KEY"},
        }
        report = validate_config(minimal_config, strict=False)
        assert any(i.path == "model.providers" for i in report.warnings)

    def test_ollama_provider_with_base_url_is_usable(self, minimal_config):
        minimal_config["model"]["providers"] = {
            "ollama": {"base_url": "http://localhost:11434"},
        }
        report = validate_config(minimal_config, strict=False)
        assert not any(i.path == "model.providers" for i in report.warnings)

    def test_placeholder_sweep_surfaces_unfilled_fields(self, minimal_config):
        minimal_config["gateway"]["custom_field"] = "YOUR_CUSTOM_VALUE"
        report = validate_config(minimal_config, strict=False)
        assert any("gateway.custom_field" in i.path for i in report.warnings)


class TestValidationReport:
    def test_format_with_errors(self):
        report = ValidationReport()
        report.add_error("gateway.port", "missing")
        report.add_warning("blockchain.rpc_url", "placeholder")
        output = report.format()
        assert "1 configuration error" in output
        assert "1 configuration warning" in output
        assert "gateway.port" in output
        assert "blockchain.rpc_url" in output

    def test_format_empty_report(self):
        report = ValidationReport()
        assert report.format() == "Config OK"

    def test_has_errors_is_false_for_warnings_only(self):
        report = ValidationReport()
        report.add_warning("foo", "bar")
        assert report.has_errors is False
