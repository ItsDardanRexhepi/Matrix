"""A setuptools build that carries global options is handed to setuptools.

THE DEFECT (pre-existing on The Matrix ``main``). ``setup.py`` recognised a
build by ``argv[1]`` alone, and setuptools puts global options before the
command: ``pip install -e . -C--quiet`` runs ``setup.py -q egg_info``, and so
do ``python setup.py -q sdist`` and a build with ``--global-option=-q``. Each
started the interactive wizard inside the build. The entry now reads the
first argument that is not an option, so the command is found wherever the
options put it; a wizard run with options of its own (``--verbose``) is still
the wizard.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def entry():
    spec = importlib.util.spec_from_file_location("matrix_setup_entry_options", ROOT / "setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("argv", [
    ["setup.py", "-q", "egg_info"],
    ["setup.py", "--quiet", "sdist"],
    ["setup.py", "-v", "-q", "bdist_wheel", "--dist-dir", "/x"],
    ["setup.py", "--no-user-cfg", "editable_wheel"],
])
def test_a_build_behind_global_options_is_recognised(entry, argv):
    """[control] Each of these launched the wizard."""
    assert entry.invoked_by_setuptools(argv)


@pytest.mark.parametrize("argv", [
    ["setup.py"], ["setup.py", "--verbose"], ["setup.py", "-q"],
    ["setup.py", "egg_info"], ["setup.py", "--name"], ["setup.py", "--version"],
])
def test_the_other_runs_read_as_before(entry, argv):
    """[guard] A bare run and a run with only options are the wizard; a bare
    command and the metadata queries are setuptools."""
    expected = len(argv) > 1 and argv[1] in entry.SETUPTOOLS_COMMANDS
    assert entry.invoked_by_setuptools(argv) is expected
