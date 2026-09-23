"""The platform is The Matrix. The names it replaced must not come back.

0pnMatrx / OpenMatrix / opnmatrx became The Matrix, and matrix_server became the
Oracle Server. A rename is only finished if it stays finished, so this walks the
whole repository and fails on any reappearance.

Three categories are deliberately EXEMPT, because they are bound to things
outside this repository and renaming them would break the real world rather than
tidy it:

  * App Store bundle and product identifiers (opnmatrx.mtrx...). A product id
    cannot be changed once registered in App Store Connect; renaming one
    detaches existing subscribers from the entitlement they paid for.
  * The domain openmatrix-ai.com. A name is only a URL if it is owned.
  * Absolute filesystem paths that still resolve.

Those exemptions live in the name guard, a separate tool. When
MATRIX_NAME_GUARD points at it, this test runs it over the whole repository;
where it is not available the test is skipped rather than guessed at.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
_GUARD_PATH = os.environ.get("MATRIX_NAME_GUARD", "")
GUARD = pathlib.Path(_GUARD_PATH) if _GUARD_PATH else None


@pytest.mark.skipif(GUARD is None or not GUARD.exists(), reason="MATRIX_NAME_GUARD does not point at the name guard here")
def test_no_file_in_this_repository_carries_an_old_name():
    result = subprocess.run(
        [sys.executable, str(GUARD), str(REPO)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "the old names have reappeared:\n" + result.stdout + result.stderr)


def test_the_readme_introduces_the_platform_by_its_name():
    readme = (REPO / "README.md").read_text()
    assert readme.lstrip().startswith("# The Matrix"), readme[:80]
    for dead in ("0pnMatrx", "OpenMatrix"):
        assert dead not in readme, f"the README still says {dead}"


def test_the_quick_start_clones_and_enters_the_same_directory():
    """A rename that edits prose but leaves `cd <old name>` in the quick start
    hands a new user a command that cannot work."""
    readme = (REPO / "README.md").read_text()
    assert "cd TheMatrix" in readme
    assert "cd The Matrix" not in readme, "that is not a valid shell command"
