"""What contracts/deploy.py writes into the tree is not committable.

A run of the deploy script writes `contracts/<Name>.abi.json` for each
contract it deploys and `contracts/deployment.json`, the record of one
operator's deployment (network, chain id, addresses). Neither was ignored,
so a `git add -A` after a deploy staged both. The paths are read from the
script's own writes, and the verdict is git's `check-ignore` against this
repository's rules with global excludes switched off.
"""

from __future__ import annotations

import os
import re
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


def _written_by_deploy_script() -> list[str]:
    source = (ROOT / "contracts" / "deploy.py").read_text(encoding="utf-8")
    paths = re.findall(r'Path\(f?"(contracts/[^"]+)"\)', source)
    found = sorted({p.replace("{name}", "SampleContract") for p in paths})
    assert found, "contracts/deploy.py no longer writes into contracts/ — update this test"
    return found


def test_deploy_outputs_are_git_ignored():
    written = _written_by_deploy_script()
    not_ignored = [
        rel for rel in written
        if subprocess.run(
            [GIT, "-C", str(ROOT), "check-ignore", "--no-index", "-q", rel],
            capture_output=True, env=_GIT_ENV,
        ).returncode != 0
    ]
    assert not not_ignored, (
        f"contracts/deploy.py writes {not_ignored}, which git would let a "
        "`git add -A` stage"
    )
