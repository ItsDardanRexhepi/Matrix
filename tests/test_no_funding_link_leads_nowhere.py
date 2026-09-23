"""No link in this repository asks for money on behalf of a channel that is not there.

Measured on 2026-09-22, against the public pages and the owner's own GitHub
identity:

* github.com/sponsors/ItsDardanRexhepi answered 302 to the profile: GitHub
  Sponsors is not enabled for the account (`hasSponsorsListing: false`).
* opencollective.com/the-matrix is an individual profile created 2020-02-10,
  six years before this repository, with nothing linking it to the project.
  It is not the project's.
* opencollective.com/matrix answered 404; the Open Collective API has no
  account with that slug.
* openmatrix-ai.com/sponsor answered 404, and openmatrix-ai.com has no MX
  record, so sponsor@openmatrix-ai.com receives nothing.

Each of those was linked from the README, SPONSORS.md, .github/SPONSORS.md,
.github/FUNDING.yml, opencollective.json and a gateway route (/sponsor). They
are gone. web/ is outside this check and is not changed here; its two
remaining links are in web/landing.html.

When a real channel exists, link it, and take its entry off this list in the
same change, with what was measured to show it exists.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Written as plain text and escaped below, so each reads as the address it is
# (the old-names guard protects the domain spelled literally, not a regex of it).
DEAD_LINKS = [
    "github.com/sponsors/ItsDardanRexhepi",
    "opencollective.com/the-matrix",
    "opencollective.com/matrix",
    "openmatrix-ai.com/sponsor",
    "sponsor@openmatrix-ai.com",
]
DEAD = [re.escape(link) + r"(?![\w-])" for link in DEAD_LINKS] + [
    r"^\s*open_collective:\s*matrix\s*$",
    r'"collective":\s*"matrix"',
]

_SKIP_DIRS = {".git", "web", "node_modules", "lib", ".venv", "venv", "__pycache__"}
_THIS = Path(__file__).resolve()


def _files():
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        if not p.is_file() or set(rel.parts[:-1]) & _SKIP_DIRS or p.resolve() == _THIS:
            continue
        if p.suffix in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pem", ".db", ".sqlite"}:
            continue
        yield p


def test_no_file_links_a_funding_channel_that_does_not_exist():
    pattern = re.compile("|".join(DEAD), re.M)
    hits = []
    for p in _files():
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in pattern.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            hits.append(f"{p.relative_to(ROOT)}:{line}: {m.group(0).strip()}")
    assert not hits, "funding links to channels that do not exist:\n  " + "\n  ".join(hits)


def test_the_gateway_has_no_sponsor_redirect():
    server = (ROOT / "gateway" / "server.py").read_text(encoding="utf-8")
    assert '"/sponsor"' not in server, (
        "gateway/server.py routes /sponsor again; it redirected to a GitHub "
        "Sponsors page that is not enabled"
    )
