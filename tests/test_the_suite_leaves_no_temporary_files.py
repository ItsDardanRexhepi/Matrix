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
