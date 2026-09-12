"""The suite's verdict must come from the code, not from the developer's shell.

Four ambient switches decide how a GatewayServer (and the services behind it)
behaves, and only test_config_validation and test_readiness owned any of them:

  OPNMATRX_ENV=production      — every GatewayServer construction becomes a
                                 production boot (noop backend and no API key
                                 are refusals). Measured before this fixture:
                                 65 failed + 552 errors across the 21 modules
                                 that build a server.
  OPENMATRIX_API_KEY           — `api_key = gw.get("api_key") or os.environ[...]`
                                 turns the credential wall on for every config
                                 that leaves the key empty. Measured: 12 failed.
  runtime.security.SECURITY_BACKEND
                               — decided at import by whether the private
                                 package happens to be importable. Tests named
                                 for the noop path ran under the live one.
  OPNMATRX_OTP_PEPPER          — with the private package importable, its
                                 production OTP guard refuses without one, so the
                                 production-readiness tests were red there and
                                 green here. Measured: 6 failed.

tests/conftest.py now resets them at SESSION scope and again per test: every
OPNMATRX_* / OPENMATRIX_* variable cleared (by prefix, so a switch added later is
covered), a fixed test pepper, the backend label pinned to "noop". Session scope
is load-bearing — test_route_sweep's module-scoped `sweep_results` builds the
gateway before any function-scoped fixture runs, and a function-only version
left all 547 sweep cases erroring under OPNMATRX_ENV=production.

A test that wants a non-default value sets it itself, as test_readiness and
test_security_backend_honesty already do.

Two more sources, found after the first version shipped: the .env FILE
(load_config's _load_dotenv wrote ./.env into the variables just cleared — a
.env holding OPNMATRX_ENV=production gave test_apns_env_override followed by
test_route_sweep 547 errors), and a DIRECT os.environ write during a test, which
the monkeypatch-based per-test reset recorded and restored into os.environ
between tests, where the next module-scoped fixture was built. The probe now runs
from a directory with a hostile .env, calls the real loader, writes the
environment directly, and has a later module-scoped fixture check for the leak.

The control runs tests/ambient_isolation_probe.py in a subprocess with every one
of those switches set hostile — the backend flipped by a plugin that stands in
for an importable private package — and requires both probe tests (function
scope and module scope, the .env loader, and a module fixture built after a
direct write) to pass. Without the conftest fixture the probe fails,
so deleting or narrowing the fixture fails this test.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

_PLUGIN = '''
def pytest_configure(config):
    # Stand-in for "morpheus_security is importable in this checkout".
    import runtime.security as seam
    seam.SECURITY_BACKEND = "morpheus_security"
'''


def test_a_hostile_environment_does_not_reach_a_test(tmp_path):
    (tmp_path / "ambient_backend_plugin.py").write_text(_PLUGIN)
    # The .env file is an ambient source too: load_config reads ./.env. The
    # probe runs from a directory whose .env would turn production and the
    # credential wall on.
    (tmp_path / ".env").write_text(
        "OPNMATRX_ENV=production\nOPENMATRIX_API_KEY=dotenv-developer-key\n")

    env = dict(os.environ)
    env.update({
        "OPNMATRX_ENV": "production",
        "OPENMATRIX_API_KEY": "ambient-developer-key",
        "OPENMATRIX_ALLOW_TEST_MINT": "1",
        "OPNMATRX_OTP_PEPPER": "ambient-pepper",
        "PYTHONPATH": os.pathsep.join([str(tmp_path), str(ROOT), env.get("PYTHONPATH", "")]),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(ROOT / "tests" / "ambient_isolation_probe.py"),
         "-q", "-p", "no:cacheprovider", "-p", "ambient_backend_plugin",
         "--rootdir", str(ROOT)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300,
    )
    tail = (proc.stdout + proc.stderr)[-3000:]  # the probe never prints os.environ
    assert proc.returncode == 0, f"the ambient environment decided a test's result:\n{tail}"
    assert "5 passed" in proc.stdout, tail
