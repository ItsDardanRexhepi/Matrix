"""What the runtime writes into the working tree must not be committable.

The hivemind writes its event log, session state and message queues under
``<workspace>/hivemind/`` — and ``hivemind/`` is a tracked source package, and
the orchestrator's default workspace is ``"."``. A contributor who ran it from
the repo root and then ``git add -A``'d committed agent event records to the
PUBLIC repo. scripts/prepare_release.py already lists ``hivemind/`` as private,
so the release export excluded them; the git axis had no such defence.

Neither half of this test takes a list of artifact names on trust:

  * the artifact paths come from running the real writers in a scratch
    workspace and seeing what lands on disk;
  * the verdict is git's own ``check-ignore`` against this repository's
    ignore rules, with the developer's global excludes switched off.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GIT = shutil.which("git")


def _in_git_checkout() -> bool:
    if GIT is None:
        return False
    return subprocess.run(
        [GIT, "-C", str(ROOT), "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True,
    ).stdout.strip() == "true"


pytestmark = pytest.mark.skipif(not _in_git_checkout(), reason="needs a git checkout and git")

_GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _ignored(rel: str) -> bool:
    return subprocess.run(
        [GIT, "-C", str(ROOT), "check-ignore", "--no-index", "-q", rel],
        capture_output=True, env=_GIT_ENV,
    ).returncode == 0


def _tracked(rel: str) -> bool:
    return bool(subprocess.run(
        [GIT, "-C", str(ROOT), "ls-files", "--", rel],
        capture_output=True, text=True, env=_GIT_ENV,
    ).stdout.strip())


def _write_hivemind_artifacts(workspace: Path) -> list[str]:
    from hivemind.events import AgentEvent, EventBus, EventType
    from hivemind.lifecycle import LifecycleManager
    from hivemind.orchestrator import MessageBus

    async def drive():
        await EventBus(str(workspace)).emit(AgentEvent(
            type=EventType.SESSION_STARTED, source_agent="orchestrator", session_id="s1",
        ))
        await LifecycleManager(str(workspace)).start_session("trinity", session_id="s1")
        await MessageBus(str(workspace)).send("neo", {"task": "probe"})

    asyncio.run(drive())
    return sorted(
        str(p.relative_to(workspace)) for p in workspace.rglob("*") if p.is_file()
    )


def test_hivemind_runtime_artifacts_are_git_ignored(tmp_path):
    written = _write_hivemind_artifacts(tmp_path)
    assert written, "the hivemind writers produced no files — this test would prove nothing"
    committable = [rel for rel in written if not _ignored(rel)]
    assert not committable, (
        "running the hivemind with the repo root as its workspace writes files "
        f"`git add -A` would commit: {committable}"
    )


def test_hivemind_source_is_still_tracked():
    """Ignoring the artifacts must not ignore the package they sit in."""
    for rel in ("hivemind/__init__.py", "hivemind/events.py", "hivemind/orchestrator.py"):
        assert _tracked(rel) and not _ignored(rel), f"{rel} is ignored"


def test_release_private_paths_are_ignored_on_the_git_axis_too():
    """Every path the release export treats as private, and git does not track,
    is ignored by git.

    Tracked entries (``hivemind/`` is source) are the release scanner's own
    business and are skipped here; their runtime contents are covered above.
    """
    from scripts.prepare_release import PRIVATE_FILES

    exposed = []
    for entry in sorted(PRIVATE_FILES):
        probe = entry + "probe" if entry.endswith("/") else entry
        if _tracked(entry.rstrip("/")):
            continue
        if not _ignored(probe):
            exposed.append(entry)
    assert not exposed, (
        "scripts/prepare_release.py keeps these out of a release, but git "
        f"would commit them: {exposed}"
    )
