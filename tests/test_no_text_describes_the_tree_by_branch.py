"""No text in the tree describes the code by the branch it was read on.

tests/test_platform_attestations_are_metered.py said "Measured on main:" and
"On main it signed as the exempt `eas.attest`" about the code before the
attestations it tests were metered. Once that change is merged, main is the
metered tree, and the sentence describes it wrongly. A statement about how the
code used to behave has to say when, in terms that stay true after a merge
("before attestations were metered", or a commit id), not by branch name.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_BY_BRANCH = re.compile(r"\b(?:measured|signed|ran|answered|was|were)?\s*(?:on|at) main\b"
                        r"|\bmain has\b", re.I)
_SELF = "tests/test_no_text_describes_the_tree_by_branch.py"


def test_the_branch_wording_scan_catches_the_old_docstrings():
    assert _BY_BRANCH.search("`eas.attest`, `eas.attest_time_critical` and `eas.revoke`. Measured on main:")
    assert _BY_BRANCH.search("must not sign or send. On main it signed as the exempt `eas.attest`")
    assert not _BY_BRANCH.search("Before attestations were metered it signed as the exempt one; "
                                 "the main loop, the domain name and maintenance are not branches.")


def test_no_tracked_text_describes_the_code_by_branch_name():
    out = subprocess.check_output(["git", "ls-files", "*.py", "*.md", "*.html"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel in ("CHANGELOG.md", _SELF) or not (ROOT / rel).is_file():
            continue
        for lineno, line in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1):
            if _BY_BRANCH.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()[:120]}")
    assert not offenders, "\n".join(offenders)
