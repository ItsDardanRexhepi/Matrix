"""`MATRIX_ENV=prod` is production, the same as `MATRIX_ENV=production`.

THE DEFECT, MEASURED. `is_production_mode` (runtime/config/validation.py) is the
platform's one reading of the switch, and it accepted only "production". "prod"
is the other common spelling of the same intent, and a deployment that wrote it
got the development path with nothing said. Measured on the tree before this
change with `MATRIX_ENV=prod`:

- `validate_config` reported 0 errors for a config with no API key;
- `enforce_env_only_secrets` left a plaintext Twitter key in the config;
- the gateway started with no API key, so its auth wall was off and every
  caller was treated as the operator — which is also who may name the user an
  action is for.

The platform now reads both spellings, in any case and with surrounding space,
and nothing else: a value that only contains one of them is not production.
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, "tests")

from gateway.server import GatewayServer  # noqa: E402
from runtime.config.validation import (  # noqa: E402
    enforce_env_only_secrets,
    is_production_mode,
    validate_config,
)
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

TWITTER = "twitter-key-written-into-the-file"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("MATRIX_ENV", "MATRIX_API_KEY", "TWITTER_API_KEY", "MATRIX_PAYMASTER_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize("value,production", [
    ("production", True), ("PRODUCTION", True), ("  production  ", True),
    ("prod", True), ("PROD", True), (" Prod\n", True),
    ("", False), ("development", False), ("dev", False), ("testnet", False),
    ("staging", False), ("preprod", False), ("prod1", False), ("production-ish", False),
])
def test_both_spellings_and_nothing_else_are_production(value, production, monkeypatch):
    monkeypatch.setenv("MATRIX_ENV", value)
    assert is_production_mode() is production


def _minimal() -> dict:
    return {
        "platform": "The Matrix",
        "gateway": {"host": "127.0.0.1", "port": 8080},
        "model": {"provider": "ollama", "providers": {"ollama": {"base_url": "http://x"}}},
        "database": {"path": "data/x.db"},
        "social": {"twitter": {"api_key": TWITTER}},
    }


def test_prod_validates_as_production(monkeypatch):
    """DEFECT-PROVER. Before: 0 errors with no API key under MATRIX_ENV=prod."""
    monkeypatch.setenv("MATRIX_ENV", "prod")
    report = validate_config(_minimal())
    assert any(i.path == "gateway.api_key" for i in report.errors), report.format()


def test_prod_strips_a_plaintext_secret(monkeypatch):
    """DEFECT-PROVER. Before: the Twitter key stayed in the config."""
    monkeypatch.setenv("MATRIX_ENV", "prod")
    monkeypatch.setenv("MATRIX_PAYMASTER_KEY", "0x" + "2b" * 32)
    config = enforce_env_only_secrets(_minimal())
    assert TWITTER not in repr(config)


def _with_live_security(monkeypatch):
    # As tests/test_readiness.py does: without the security core importable the
    # no-op backend's own production refusal would fire first, and this test
    # would pass for that reason rather than the one it names.
    monkeypatch.setattr("runtime.security.SECURITY_BACKEND", "morpheus_security",
                        raising=False)


def test_prod_refuses_to_start_with_authentication_off(monkeypatch):
    """DEFECT-PROVER. Before: the gateway built with auth off under MATRIX_ENV=prod."""
    monkeypatch.setenv("MATRIX_ENV", "prod")
    _with_live_security(monkeypatch)
    config = {**SWEEP_CONFIG, "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": ""}}
    with pytest.raises(RuntimeError, match="no gateway API key is configured"):
        GatewayServer(config)


def test_a_development_spelling_still_runs_open(monkeypatch):
    """Guard: the change reads one more spelling as production and no fewer as
    development."""
    monkeypatch.setenv("MATRIX_ENV", "development")
    config = {**SWEEP_CONFIG, "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": ""}}
    assert GatewayServer(config).auth_enabled is False
