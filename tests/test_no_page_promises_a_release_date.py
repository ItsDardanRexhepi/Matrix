"""No public page promises a release on a date.

web/landing.html's footer read "iOS App (Coming May 2026)", a date already
past. Nothing in this repository can measure when an app ships, so no page
states a date for one: it names what exists.

What this cannot see: a date written in another form.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_NOT_READ = {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}
_A_RELEASE_DATE = re.compile(
    r"\b(?:coming|launching|available|arrives?|ships?)\s+(?:in\s+|on\s+|from\s+)?"
    r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}|q[1-4]\s+\d{4})\b",
    re.I)


def test_the_scan_catches_the_old_footer():
    assert _A_RELEASE_DATE.search('<a href="#" title="Coming May 2026">iOS App (Coming May 2026)</a>')
    assert _A_RELEASE_DATE.search("Launching Q3 2027")
    assert not _A_RELEASE_DATE.search("iOS app: MTRX. Copyright 2026.")


def test_no_public_page_states_a_release_date():
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        text = (ROOT / rel).read_text(encoding="utf-8")
        offenders += [f"{rel}: {m.group(0)}" for m in _A_RELEASE_DATE.finditer(text)]
    assert not offenders, "\n".join(offenders)
