"""Shared fixtures for The Matrix test suite."""

import os
import shutil
import tempfile

import pytest

# THE SUITE CLEANS UP ITS OWN TEMPORARY FILES. Dozens of tests create scratch
# directories with tempfile.mkdtemp and never remove them, so every run left
# hundreds in the system temp folder, and parallel runs filled a disk. For the
# life of the pytest process, Python's temporary directory is a folder private
# to that process, removed when the session ends: every mkdtemp made by a test
# or by the code under test lands there, child processes inherit it through
# TMPDIR, and one run cannot delete another's files. A run that is killed never
# reaches session end, so its folder carries its process id, and each new run
# removes the folders of processes that have exited — never a live one's.
_SESSION_TEMP = {"dir": None, "tempdir": None, "env": None}
_SUITE_PREFIX = "the-matrix-suite-"


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _remove_folders_of_exited_runs(parent: str) -> None:
    try:
        names = os.listdir(parent)
    except OSError:
        return
    for name in names:
        if not name.startswith(_SUITE_PREFIX):
            continue
        pid_text = name[len(_SUITE_PREFIX):].split("-", 1)[0]
        if not pid_text.isdigit() or _process_is_alive(int(pid_text)):
            continue
        shutil.rmtree(os.path.join(parent, name), ignore_errors=True)


def pytest_configure(config):
    _remove_folders_of_exited_runs(tempfile.gettempdir())
    base = tempfile.mkdtemp(prefix=f"{_SUITE_PREFIX}{os.getpid()}-")
    _SESSION_TEMP.update(dir=base, tempdir=tempfile.tempdir, env=os.environ.get("TMPDIR"))
    tempfile.tempdir = base
    os.environ["TMPDIR"] = base


def pytest_unconfigure(config):
    base = _SESSION_TEMP["dir"]
    if not base:
        return
    tempfile.tempdir = _SESSION_TEMP["tempdir"]
    if _SESSION_TEMP["env"] is None:
        os.environ.pop("TMPDIR", None)
    else:
        os.environ["TMPDIR"] = _SESSION_TEMP["env"]
    shutil.rmtree(base, ignore_errors=True)

# Environment prefixes whose variables switch security posture: production mode,
# the gateway credential wall, the test-mint switch, the seam's state/attest/OTP
# settings. Cleared by PREFIX rather than by name so a switch added later is
# isolated without anyone remembering to list it here.
_AMBIENT_SWITCH_PREFIXES = ("MATRIX_", "MATRIX_")

# A fixed, test-only pepper. With the private security package importable its
# production OTP guard refuses to construct without one, which made every
# production-readiness test red in that checkout and green in this one. The
# tests that exercise the missing-pepper refusal inject that fault explicitly.
_TEST_OTP_PEPPER = "test-suite-otp-pepper-not-a-secret"


def _clear_ambient_security_switches():
    """Put os.environ's switch variables back to the documented default: every
    MATRIX_* / MATRIX_* variable removed, then the test pepper. Written to
    os.environ directly, NOT through monkeypatch: a monkeypatch reset records
    whatever it removes and puts it back at teardown, so a value code under test
    wrote directly was restored into os.environ between tests."""
    for name in [n for n in os.environ if n.startswith(_AMBIENT_SWITCH_PREFIXES)]:
        del os.environ[name]
    os.environ["MATRIX_OTP_PEPPER"] = _TEST_OTP_PEPPER


def _pin_backend_label():
    # Decided at import by package importability; pinned to the open-checkout
    # value. This pins the LABEL the gateway decides on (production refusal,
    # /ready) — it does not swap the seam's implementation classes.
    import runtime.security as seam
    seam.SECURITY_BACKEND = "noop"


def _no_dotenv(*args, **kwargs):
    """Stands in for python-dotenv's load_dotenv for the whole session."""
    return False


@pytest.fixture(autouse=True, scope="session")
def _ambient_security_switches_session():
    """Every test starts from the documented default, not the developer's shell.

    Without this, whether a GatewayServer booted as production, whether its
    credential wall was up, and which security backend it reported were decided
    by whatever the person running the suite had exported — and by whether the
    private package happened to be importable. Measured across the 21 modules
    that build a server: MATRIX_ENV=production -> 65 failed + 552 errors;
    MATRIX_API_KEY set -> 12 failed; private package importable -> 6 failed.

    Three ambient SOURCES, all isolated here:
      * the shell's variables — cleared by prefix;
      * the .env FILE — load_config calls gateway.server._load_dotenv, which
        loads ./.env with override=False into variables this fixture just
        cleared, so a developer's `.env` holding MATRIX_ENV=production decided
        the suite (measured: test_apns_env_override then test_route_sweep ->
        547 errors). python-dotenv's load_dotenv is a no-op for the session,
        patched on the package so any loader that imports it at call time is
        covered, not only this one;
      * package importability — the backend label is pinned.

    SESSION scope, because a module-scoped fixture is built before any
    function-scoped one runs: test_route_sweep's `sweep_results` constructs the
    gateway all 547 sweep cases judge, and a function-scoped reset never reached
    it (measured: those 547 errors survived a function-only version of this).

    A test that wants a non-default value sets it itself, with monkeypatch
    (test_readiness._with_live_security, test_security_backend_honesty).
    tests/test_ambient_security_isolation.py is the control.
    """
    saved = {n: v for n, v in os.environ.items() if n.startswith(_AMBIENT_SWITCH_PREFIXES)}
    with pytest.MonkeyPatch.context() as mp:
        for target in ("dotenv.load_dotenv", "dotenv.main.load_dotenv"):
            try:
                mp.setattr(target, _no_dotenv)
            except (ImportError, AttributeError):
                pass  # python-dotenv absent: nothing can load a .env
        mp.setattr("runtime.security.SECURITY_BACKEND", "noop", raising=False)
        _clear_ambient_security_switches()
        try:
            yield
        finally:
            _clear_ambient_security_switches()
            del os.environ["MATRIX_OTP_PEPPER"]
            os.environ.update(saved)


@pytest.fixture(autouse=True)
def _ambient_security_switches(_ambient_security_switches_session):
    """Re-asserted around EVERY test, at setup and at teardown.

    Teardown is the half that matters for leaks: code under test can write
    os.environ directly (a loader, a service), and a variable it ADDS was never
    recorded by anyone. Clearing at teardown means nothing written during a test
    is in os.environ when the next module-scoped fixture is built. This fixture
    deliberately does not request `monkeypatch`: autouse fixtures are set up
    before a test's own fixtures and torn down after them, so this teardown runs
    after the test's monkeypatch has undone its own changes.
    """
    _clear_ambient_security_switches()
    _pin_backend_label()
    yield
    _clear_ambient_security_switches()
    _pin_backend_label()


@pytest.fixture
def mock_config(tmp_path):
    """Return a minimal valid config dict with temp directories."""
    return {
        "platform": "The Matrix",
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
