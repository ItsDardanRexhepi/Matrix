"""THE SUITE CLEANS UP AFTER ITSELF.

Dozens of tests create scratch directories with tempfile.mkdtemp(prefix="the-matrix-…")
and never remove them. Each run of the suite left hundreds behind in the system temp
folder; measured on one development machine, 91,000 of them held about 14 GB and filled
the disk while several runs went on in parallel.

The fix is one rule for the whole suite rather than a change at each call site:
tests/conftest.py points Python's temporary directory at a folder private to the pytest
process and removes it when the session ends. Every mkdtemp made by a test, or by the code
under test, lands there, and parallel runs cannot delete one another's files.

The control runs a test known to create such a directory in a separate pytest process,
pointed at a fresh temp folder, and checks what that folder holds afterwards.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
_LEAKY = "tests/test_conversation_cache_is_bounded.py"


def test_a_run_leaves_nothing_behind_in_the_temp_folder(tmp_path):
    probe = tmp_path / "system-temp"
    probe.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("MATRIX_")}
    env["TMPDIR"] = str(probe)
    env["PYTHONPATH"] = str(ROOT)
    run = subprocess.run(
        [sys.executable, "-m", "pytest", _LEAKY, "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=600,
    )
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    left = sorted(p.name for p in probe.iterdir())
    assert left == [], f"the run left these in the temp folder: {left[:20]}"


def test_the_session_temp_folder_is_private_to_this_run():
    here = pathlib.Path(tempfile.gettempdir())
    assert here.name.startswith("the-matrix-suite-"), here
    made = pathlib.Path(tempfile.mkdtemp(prefix="the-matrix-probe-"))
    assert made.parent == here, (made, here)


def _dead_pid() -> int:
    """A process id that has certainly exited: run a child and reap it."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_a_killed_run_s_folder_is_removed_by_the_next_run(tmp_path):
    """A run that is killed never reaches session end, so its private folder is
    left behind. The next run removes folders whose process has exited and keeps
    those whose process is alive."""
    system_temp = tmp_path / "system-temp"
    system_temp.mkdir()
    orphan = system_temp / f"the-matrix-suite-{_dead_pid()}-abcd1234"
    (orphan / "left-behind").mkdir(parents=True)
    alive = system_temp / f"the-matrix-suite-{os.getpid()}-efgh5678"
    alive.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("MATRIX_")}
    env["TMPDIR"] = str(system_temp)
    env["PYTHONPATH"] = str(ROOT)
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_the_suite_leaves_no_temporary_files.py::test_the_session_temp_folder_is_private_to_this_run",
         "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    assert not orphan.exists(), "a dead run's folder was left behind"
    assert alive.exists(), "a live run's folder was removed"


def _sweep(parent):
    import importlib.util
    spec = importlib.util.spec_from_file_location("suite_conftest", ROOT / "tests" / "conftest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._remove_folders_of_exited_runs(str(parent))


def test_a_folder_name_the_sweep_cannot_read_is_skipped_not_fatal(tmp_path):
    """A name whose process id cannot be parsed or is out of range must not
    stop the run, and must not be deleted."""
    odd = ["the-matrix-suite-99999999999999999999-x", "the-matrix-suite-\u00b2-x",
           "the-matrix-suite-\u0663-x", f"the-matrix-suite-{_dead_pid()}"]
    for name in odd:
        (tmp_path / name).mkdir()
    _sweep(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(odd)


def test_a_dead_folder_holding_a_live_run_s_folder_is_kept(tmp_path):
    """A child pytest inherits TMPDIR, so its folder sits inside its parent's.
    If the parent is killed while the child still runs, the parent's folder
    must survive until the child has exited."""
    parent = tmp_path / f"the-matrix-suite-{_dead_pid()}-parent"
    child = parent / f"the-matrix-suite-{os.getpid()}-child"
    child.mkdir(parents=True)
    _sweep(tmp_path)
    assert child.exists(), "a live run's folder was deleted with its dead parent's"
