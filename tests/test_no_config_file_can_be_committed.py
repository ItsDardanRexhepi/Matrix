"""Every filename the platform writes a config to must be ignored by git.

THE DEFECT THIS EXISTS FOR, and it cost a real credential. The rename pass
rewrote .gitignore's `openmatrix.config.json` to `matrix.config.json` — the new
name, correctly — and left nothing ignoring the old one. But a config file on
disk is NOT renamed when the project is renamed. Every existing install still
had `openmatrix.config.json` sitting in its working tree, and the moment that
name stopped being ignored the next `git add -A` swept it into a commit, with a
live API key inside, to a PUBLIC repository.

Untracking it afterwards does not remove it from history, and force-pushing a
rewritten history does not remove it from GitHub either: the orphaned commit is
still served by its own SHA until GitHub garbage-collects. The key had to be
rotated. That is the whole cost of one line in .gitignore.

THE RULE THIS PINS: a rename that touches .gitignore ADDS the new name, it never
replaces the old one. What .gitignore protects is whatever is actually on disk,
and a rename does not reach that.

So this test does not check for a hardcoded list. It derives the filenames the
CODE can write a config to, and requires git to ignore every one of them.
"""
from __future__ import annotations

import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parent.parent

#: Names the project has ever written a config to. A name is only ever ADDED
#: here — an install created under an old name keeps that file forever.
HISTORICAL_CONFIG_NAMES = ("matrix.config.json", "openmatrix.config.json")


def _ignored(name: str) -> bool:
    r = subprocess.run(["git", "check-ignore", "-q", name], cwd=REPO)
    return r.returncode == 0


def test_every_config_filename_the_code_writes_is_ignored():
    """Derived from the source, so a third name added later is covered."""
    names = set(HISTORICAL_CONFIG_NAMES)
    for path in list(REPO.glob("*.py")) + list((REPO / "cli").glob("*.py")):
        try:
            names.update(re.findall(r'["\']([A-Za-z0-9_.-]+\.config\.json)["\']', path.read_text()))
        except OSError:
            continue
    names = {n for n in names if not n.endswith(".example")}
    unignored = sorted(n for n in names if not _ignored(n))
    assert not unignored, (
        f"these config filenames are NOT gitignored and a `git add -A` would "
        f"commit them, keys and all: {unignored}")


def test_the_previous_config_name_is_still_ignored():
    """Named explicitly, because this is the one that actually leaked. Removing
    it from .gitignore is how the credential reached a public commit."""
    assert _ignored("openmatrix.config.json"), (
        "openmatrix.config.json is no longer ignored. Every install created "
        "before the rename still has that file on disk with its keys in it.")


def test_no_config_file_is_tracked_right_now():
    tracked = subprocess.run(
        ["git", "ls-files"] + list(HISTORICAL_CONFIG_NAMES),
        cwd=REPO, capture_output=True, text=True).stdout.split()
    assert not tracked, f"a config file is TRACKED: {tracked}"


def test_the_example_config_carries_no_real_secret():
    """The template must stay a template: placeholders, never a working value."""
    example = REPO / "matrix.config.json.example"
    if not example.exists():
        return
    text = example.read_text()
    for pattern, what in ((r"omx_[a-f0-9]{32,}", "a gateway key"),
                          (r"xai-[A-Za-z0-9_-]{20,}", "an xAI key"),
                          (r"sk-[A-Za-z0-9]{32,}", "an OpenAI-style key"),
                          (r"ghp_[A-Za-z0-9]{36}", "a GitHub token")):
        assert not re.search(pattern, text), f"the example config contains {what}"
