"""Shared fixtures for 0pnMatrx test suite."""

import os

import pytest

# Environment prefixes whose variables switch security posture: production mode,
# the gateway credential wall, the test-mint switch, the seam's state/attest/OTP
# settings. Cleared by PREFIX rather than by name so a switch added later is
# isolated without anyone remembering to list it here.
_AMBIENT_SWITCH_PREFIXES = ("OPNMATRX_", "OPENMATRIX_")

# A fixed, test-only pepper. With the private security package importable its
# production OTP guard refuses to construct without one, which made every
# production-readiness test red in that checkout and green in this one. The
# tests that exercise the missing-pepper refusal inject that fault explicitly.
_TEST_OTP_PEPPER = "test-suite-otp-pepper-not-a-secret"


def _reset_ambient_security_switches(mp):
    for name in list(os.environ):
        if name.startswith(_AMBIENT_SWITCH_PREFIXES):
            mp.delenv(name, raising=False)
    mp.setenv("OPNMATRX_OTP_PEPPER", _TEST_OTP_PEPPER)
    # Decided at import by package importability; pinned to the open-checkout
    # value. This pins the LABEL the gateway decides on (production refusal,
    # /ready) — it does not swap the seam's implementation classes.
    mp.setattr("runtime.security.SECURITY_BACKEND", "noop", raising=False)


@pytest.fixture(autouse=True, scope="session")
def _ambient_security_switches_session():
    """Every test starts from the documented default, not the developer's shell.

    Without this, whether a GatewayServer booted as production, whether its
    credential wall was up, and which security backend it reported were decided
    by whatever the person running the suite had exported — and by whether the
    private package happened to be importable. Measured across the 21 modules
    that build a server: OPNMATRX_ENV=production -> 65 failed + 552 errors;
    OPENMATRIX_API_KEY set -> 12 failed; private package importable -> 6 failed.

    SESSION scope, because a module-scoped fixture is built before any
    function-scoped one runs: test_route_sweep's `sweep_results` constructs the
    gateway all 547 sweep cases judge, and a function-scoped reset never reached
    it (measured: those 547 errors survived a function-only version of this).

    A test that wants a non-default value sets it itself, with monkeypatch
    (test_readiness._with_live_security, test_security_backend_honesty).
    tests/test_ambient_security_isolation.py is the control.
    """
    with pytest.MonkeyPatch.context() as mp:
        _reset_ambient_security_switches(mp)
        yield


@pytest.fixture(autouse=True)
def _ambient_security_switches(_ambient_security_switches_session, monkeypatch):
    """Re-asserted per test: code under test can write os.environ directly
    (load_config's dotenv loader does), and that must not leak into the next."""
    _reset_ambient_security_switches(monkeypatch)
    yield


@pytest.fixture
def mock_config(tmp_path):
    """Return a minimal valid config dict with temp directories."""
    return {
        "platform": "0pnMatrx",
        "memory_dir": str(tmp_path / "memory"),
        "workspace": str(tmp_path),
        "timezone": "UTC",
        "max_steps": 5,
        "model": {
            "provider": "ollama",
            "providers": {},
        },
        "agents": {
            "neo": {"enabled": True},
            "trinity": {"enabled": True},
            "morpheus": {"enabled": True},
        },
        "gateway": {
            "host": "0.0.0.0",
            "port": 18790,
            "api_key": "test-api-key-12345",
            "rate_limit_rpm": 60,
            "rate_limit_burst": 10,
        },
        "blockchain": {
            "rpc_url": "http://localhost:8545",
            "chain_id": 84532,
        },
        "security": {
            "block_on_critical": True,
            "block_on_high": False,
        },
    }


@pytest.fixture
def temp_workspace(tmp_path):
    """Provide a temporary workspace directory with standard subdirs."""
    for subdir in ["memory", "hivemind/queues", "hivemind/sessions", "hivemind/events"]:
        (tmp_path / subdir).mkdir(parents=True, exist_ok=True)
    return tmp_path
