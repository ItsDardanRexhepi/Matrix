"""Probe for test_ambient_security_isolation.py — NOT collected on its own.

The filename deliberately does not match ``test_*.py``. It is run only by that
module, in a subprocess whose environment has been made hostile, so what it
observes is what tests/conftest.py leaves a test with. Being under tests/ is the
point: the real conftest applies to it exactly as it applies to every test.
"""
from __future__ import annotations

import os
import sys

import pytest


@pytest.fixture(scope="module")
def seen_at_module_setup():
    """A module-scoped fixture is built BEFORE any function-scoped autouse
    fixture runs. test_route_sweep's `sweep_results` is one: it constructs the
    gateway the whole 547-case sweep judges, so isolation that only reaches
    function scope never reached it."""
    import runtime.security as seam
    return {
        "env_mode": os.environ.get("MATRIX_ENV"),
        "api_key_set": os.environ.get("MATRIX_API_KEY") is not None,
        "backend": seam.SECURITY_BACKEND,
    }


def test_probe_module_scoped_fixtures_see_the_default_too(seen_at_module_setup):
    assert seen_at_module_setup == {
        "env_mode": None, "api_key_set": False, "backend": "noop",
    }, "a module-scoped fixture was built under the ambient environment"


def test_probe_sees_the_documented_default_not_the_ambient_one():
    import runtime.security as seam

    # Read into locals first: an assertion on os.environ itself would print the
    # whole environment of whoever runs the suite into the failure report.
    env_mode = os.environ.get("MATRIX_ENV")
    api_key = os.environ.get("MATRIX_API_KEY")
    test_mint = os.environ.get("MATRIX_ALLOW_TEST_MINT")
    pepper_is_ambient = os.environ.get("MATRIX_OTP_PEPPER") == "ambient-pepper"
    backend = seam.SECURITY_BACKEND

    assert env_mode is None, "ambient MATRIX_ENV reached a test"
    assert api_key is None, "ambient MATRIX_API_KEY reached a test"
    assert test_mint is None, "ambient MATRIX_ALLOW_TEST_MINT reached a test"
    assert not pepper_is_ambient, "ambient MATRIX_OTP_PEPPER reached a test"
    assert backend == "noop", f"ambient backend {backend!r} reached a test"

    # And the consequence, not just the variables: a gateway built the way the
    # route tests build one comes up non-production, unauthenticated, noop.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from test_route_sweep import SWEEP_CONFIG

    from gateway.server import GatewayServer

    server = GatewayServer(SWEEP_CONFIG)
    assert server._security_backend == "noop"
    assert server.auth_enabled is False


# ── Two ambient inputs the shell-variable reset did not cover ────────────────
#
# 1. The .env FILE. load_config -> gateway.server._load_dotenv loads ./.env with
#    override=False, and the fixture has just cleared the variables, so it wrote
#    whatever the developer's .env holds. The control runs this probe from a
#    directory whose .env is hostile.
# 2. A DIRECT os.environ write during a test. monkeypatch.delenv on a variable
#    that is not set records nothing, so the written value stayed; worse, the
#    next test's per-test reset recorded it and its teardown put it back — in
#    os.environ between tests, where the next module-scoped fixture is built.


def test_probe_the_dotenv_file_is_not_an_ambient_source():
    from gateway import server

    assert os.path.isfile(".env"), "precondition: the control put a hostile .env here"
    server._load_dotenv()  # exactly what load_config calls
    env_mode = os.environ.get("MATRIX_ENV")
    api_key = os.environ.get("MATRIX_API_KEY")
    assert env_mode is None, ".env's MATRIX_ENV reached a test"
    assert api_key is None, ".env's MATRIX_API_KEY reached a test"


def test_probe_code_under_test_writes_the_environment_directly():
    """Not through monkeypatch — the way a loader or a service does it."""
    os.environ["MATRIX_ENV"] = "production"
    os.environ["MATRIX_SWITCH_ADDED_DURING_A_TEST"] = "1"


@pytest.fixture(scope="module")
def built_after_a_direct_write():
    """First requested by the NEXT test, so it is built between the writing
    test's teardown and any function-scoped fixture of the next one — the
    window test_route_sweep's `sweep_results` is built in."""
    return {
        "env_mode": os.environ.get("MATRIX_ENV"),
        "added": os.environ.get("MATRIX_SWITCH_ADDED_DURING_A_TEST"),
    }


def test_probe_a_direct_write_does_not_reach_a_later_module_fixture(built_after_a_direct_write):
    assert built_after_a_direct_write == {"env_mode": None, "added": None}, (
        "a value written during one test was in os.environ when a later "
        "module-scoped fixture was built")
    assert os.environ.get("MATRIX_ENV") is None
    assert os.environ.get("MATRIX_SWITCH_ADDED_DURING_A_TEST") is None
