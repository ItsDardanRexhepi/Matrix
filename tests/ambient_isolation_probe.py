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
        "env_mode": os.environ.get("OPNMATRX_ENV"),
        "api_key_set": os.environ.get("OPENMATRIX_API_KEY") is not None,
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
    env_mode = os.environ.get("OPNMATRX_ENV")
    api_key = os.environ.get("OPENMATRIX_API_KEY")
    test_mint = os.environ.get("OPENMATRIX_ALLOW_TEST_MINT")
    pepper_is_ambient = os.environ.get("OPNMATRX_OTP_PEPPER") == "ambient-pepper"
    backend = seam.SECURITY_BACKEND

    assert env_mode is None, "ambient OPNMATRX_ENV reached a test"
    assert api_key is None, "ambient OPENMATRIX_API_KEY reached a test"
    assert test_mint is None, "ambient OPENMATRIX_ALLOW_TEST_MINT reached a test"
    assert not pepper_is_ambient, "ambient OPNMATRX_OTP_PEPPER reached a test"
    assert backend == "noop", f"ambient backend {backend!r} reached a test"

    # And the consequence, not just the variables: a gateway built the way the
    # route tests build one comes up non-production, unauthenticated, noop.
    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    from gateway.server import GatewayServer

    server = GatewayServer(SWEEP_CONFIG)
    assert server._security_backend == "noop"
    assert server.auth_enabled is False
