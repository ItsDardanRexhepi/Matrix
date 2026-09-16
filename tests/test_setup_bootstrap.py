"""The Quick Start must work on a fresh Mac — driven, not assumed.

Reproduction (a clean clone, macOS, the Terminal's own interpreter):

    git clone https://github.com/ItsDardanRexhepi/TheMatrix.git
    cd TheMatrix
    python setup.py            # zsh: command not found: python   (macOS ships no `python`)
    python3 setup.py           # step 2 fails: "externally-managed-environment" —
                               # Homebrew's python3 refuses `pip install` (PEP 668)
    pip install -e .           # launches the wizard inside pip: banner, then EOFError,
                               # because setuptools runs setup.py as __main__

And after a setup that did get through, the closing banner said
`matrix gateway start` — a command setup never installed.

The fix: setup.py creates its own .venv and re-launches inside it, hands
setuptools invocations to setuptools, installs the package (so `matrix`
exists), and the docs name `python3`. These tests pin each of those. The
bootstrap is exercised through its seams (`_exec`, `_run`, `_env`) so the
suite never creates a venv or replaces its own process.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_wizard():
    # `import setup` would find the setup/ PACKAGE; the wizard is the file.
    spec = importlib.util.spec_from_file_location("matrix_setup_wizard", ROOT / "setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def wizard():
    return load_wizard()


@pytest.fixture
def outside_venv(monkeypatch):
    """Make the running interpreter look like a global one."""
    monkeypatch.setattr(sys, "prefix", "/same")
    monkeypatch.setattr(sys, "base_prefix", "/same")
    monkeypatch.delattr(sys, "real_prefix", raising=False)


def _exec_double(calls):
    def fake_exec(path, argv):
        calls.append((path, list(argv)))
        raise SystemExit("exec")   # the real os.execv never returns
    return fake_exec


# ── the documented command ───────────────────────────────────────────────────

def test_readme_quick_start_names_an_interpreter_macos_has():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    quick_start = text.split("## Quick Start", 1)[1].split("```", 2)[1]
    assert "python3 setup.py" in quick_start
    assert "\npython setup.py" not in quick_start, "macOS has no `python`; the README must not tell users to run it"


def test_wizard_docstring_names_python3(wizard):
    assert "python3 setup.py" in wizard.__doc__
    assert "\n    python setup.py" not in wizard.__doc__


def test_declared_python_floor_matches_the_code(wizard):
    """The code uses `X | None` at import time (3.10+); pyproject said 3.9."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.10"' in pyproject
    assert "Python :: 3.9" not in pyproject
    assert wizard.PYTHON_FLOOR == (3, 10)


# ── the bootstrap ────────────────────────────────────────────────────────────

def test_bootstrap_is_a_noop_inside_a_venv(wizard, monkeypatch):
    monkeypatch.setattr(sys, "prefix", "/venv")
    monkeypatch.setattr(sys, "base_prefix", "/base")
    calls: list = []
    assert wizard.bootstrap_venv(_exec=_exec_double(calls), _env={}) is True
    assert calls == []


def test_bootstrap_opt_out_for_containers(wizard, outside_venv):
    calls: list = []
    assert wizard.bootstrap_venv(_exec=_exec_double(calls), _env={"MATRIX_SETUP_NO_VENV": "1"}) is True
    assert calls == []


def test_bootstrap_relaunches_under_an_existing_venv(wizard, outside_venv, tmp_path):
    py = wizard.venv_python(tmp_path)
    py.parent.mkdir(parents=True)
    py.write_text("#!/bin/sh\n")
    calls: list = []
    env: dict = {}
    with pytest.raises(SystemExit):
        wizard.bootstrap_venv(tmp_path, _exec=_exec_double(calls), _env=env)
    (path, argv), = calls
    assert path == str(py)
    assert argv[0] == str(py) and argv[1].endswith("setup.py")
    assert env["MATRIX_SETUP_BOOTSTRAPPED"] == "1", "the loop guard must be set before the re-launch"


def test_bootstrap_creates_the_venv_when_missing(wizard, outside_venv, tmp_path):
    made: list = []

    def fake_run(argv, **kwargs):
        made.append(list(argv))
        py = wizard.venv_python(tmp_path)
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_text("")
        return subprocess.CompletedProcess(argv, 0, "", "")

    calls: list = []
    with pytest.raises(SystemExit):
        wizard.bootstrap_venv(tmp_path, _exec=_exec_double(calls), _run=fake_run, _env={})
    assert made[0][:3] == [sys.executable, "-m", "venv"]
    assert made[0][3] == str(tmp_path / wizard.VENV_DIR)
    assert calls and calls[0][0] == str(wizard.venv_python(tmp_path))


def test_bootstrap_does_not_loop_when_the_relaunch_did_not_land_in_a_venv(wizard, outside_venv, tmp_path):
    calls: list = []
    with pytest.raises(SystemExit) as exc:
        wizard.bootstrap_venv(tmp_path, _exec=_exec_double(calls), _env={"MATRIX_SETUP_BOOTSTRAPPED": "1"})
    assert exc.value.code == 1
    assert calls == []


def test_bootstrap_refuses_to_build_a_venv_from_an_interpreter_below_the_floor(wizard, outside_venv, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "version_info", (3, 9, 6, "final", 0))
    made: list = []
    calls: list = []
    with pytest.raises(SystemExit) as exc:
        wizard.bootstrap_venv(tmp_path, _exec=_exec_double(calls), _run=lambda *a, **k: made.append(a), _env={})
    assert exc.value.code == 1
    assert made == [] and calls == []


# ── setuptools must never reach the questions ────────────────────────────────

def test_setuptools_invocations_are_recognised(wizard):
    assert wizard.invoked_by_setuptools(["setup.py", "egg_info"])
    assert wizard.invoked_by_setuptools(["setup.py", "editable_wheel", "--dist-dir", "/x"])
    assert wizard.invoked_by_setuptools(["setup.py", "bdist_wheel"])
    assert not wizard.invoked_by_setuptools(["setup.py"])
    assert not wizard.invoked_by_setuptools(["setup.py", "--verbose"])


def test_a_setuptools_style_run_does_not_launch_the_wizard():
    """Drive the real file the way setuptools does, with stdin closed.

    Before the fix this printed the banner and died with EOFError at the
    first question; pip reported "Getting requirements to build editable did
    not run successfully".
    """
    pytest.importorskip("setuptools")
    result = subprocess.run(
        [sys.executable, "setup.py", "--name"],
        cwd=ROOT, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=180,
    )
    assert "Welcome to the Matrix" not in result.stdout
    assert result.returncode == 0, result.stderr[-800:]
    assert result.stdout.strip().splitlines()[-1] == "the-matrix"


def test_install_step_installs_the_package_the_banner_advertises(wizard):
    """`matrix gateway start` is printed at the end; it exists only if the package is installed."""
    import inspect
    src = inspect.getsource(wizard.install_dependencies)
    assert '"-e", "."' in src, "setup must `pip install -e .` so the `matrix` entry point exists"
    banner_src = inspect.getsource(wizard.main)
    assert "activate" in banner_src, "the closing banner must tell the operator to activate .venv"
