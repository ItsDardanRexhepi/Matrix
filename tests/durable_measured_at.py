"""Where a durable execution gate artefact was measured, said so it can be checked.

The artefacts under tests/baseline/ that engines Phase 2 writes (G6
durable_g6_latency.json, G7 durable_g7_crash_matrix.json, G8
durable_g8_replay.json, and the mode-off golden durable_off_envelopes.json,
measured at main) each record ``measured``: the commit the figures were taken
at, by its subject, and whether that tree had uncommitted changes. A subject
is carried across a rewrite of the history where an id is not.

What an artefact records is only worth what that record is worth. G6, G7 and
G8 were once committed saying they were measured on top of a commit this
history does not hold, with uncommitted changes: figures from a tree no one
can check out again. ``check`` refuses both, wherever the history is here to
read: the commit must be one of HEAD's, and its tree must have been clean.

Nothing here imports the platform, so the modules that are also run at main
to measure it can call this lazily, from the side that runs in this tree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(tree: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True,
                          check=True, timeout=60).stdout.strip()


def measured_at(tree: Path = ROOT) -> dict:
    """``{"on_top_of": <HEAD's subject>, "with_uncommitted_changes": <bool>}``
    for *tree*, or "unknown" and None where git cannot say."""
    try:
        subject = _git(tree, "log", "-1", "--format=%s", "HEAD")
        dirty = bool(_git(tree, "status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.SubprocessError):
        subject, dirty = "", None
    return {"on_top_of": subject or "unknown", "with_uncommitted_changes": dirty}


def history_subjects(tree: Path = ROOT) -> set[str] | None:
    """Every commit subject in HEAD's history, or None where it is not here
    to read (no git, or a shallow checkout)."""
    try:
        if _git(tree, "rev-parse", "--is-shallow-repository") != "false":
            return None
        return {line.strip() for line in _git(tree, "log", "--format=%s", "HEAD").splitlines()}
    except (OSError, subprocess.SubprocessError):
        return None


def check(where: object, what: str) -> None:
    """*where* is a ``measured`` record naming a commit of this history, by
    subject, whose tree was clean when it was measured."""
    assert isinstance(where, dict) and set(where) == {"on_top_of", "with_uncommitted_changes"}, (
        f"{what} does not say where it was measured: {where}")
    assert where["with_uncommitted_changes"] is False, (
        f"{what} was measured on a tree with uncommitted changes, which no one can check out "
        f"again: {where}")
    subjects = history_subjects()
    if subjects is not None:
        assert " ".join(str(where["on_top_of"]).split()) in subjects, (
            f"{what} names a commit this history does not hold, or names it by id rather "
            f"than by subject: {where['on_top_of']!r}")
