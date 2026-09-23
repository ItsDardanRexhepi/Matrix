"""Every count of the platform's capabilities, categories and backing services
that the public text states is the count the catalog has.

The README, the docs, the Trinity system prompt, the SDK, the landing page and
three courses said "221 capabilities across 21 categories, backed by 44
services". runtime/capabilities/catalog.py — the inventory those sentences
cite, and what `GET /api/v1/capabilities` serves — holds 195 capabilities in 21
categories, served by 43 distinct services. The number stayed after the
fabricated capabilities were removed from the catalog.

The counts are derived here from the catalog, never typed in: every
"<N> capabilities", "<N> Web3 capabilities", "<N>-capability" or
"<N> Capabilities" in the tracked text, and the categories and services stated
on the same line, must equal the measured number. The changelog records
history on purpose and legal copy is changed only by counsel; neither is read.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_NOT_READ = {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}
# A subset count ("59 capabilities are flagged unavailable") is not a count of
# the catalog.
_CAPABILITY_COUNT = re.compile(
    r"\b(\d{2,4})(?:-capability\b|\s+(?:discrete\s+)?(?:Web3\s+|blockchain\s+)?"
    r"capabilities\b(?!\s+are\b))",
    re.I)
_SERVICE_COUNT = re.compile(r"\b(\d{2,4})\s+(?:underlying\s+|backing\s+)?services\b", re.I)
_CATEGORY_COUNT = re.compile(r"\b(\d{1,3})\s+(?:discoverable\s+)?categor(?:y|ies)\b", re.I)


def _measured() -> tuple[int, int, int]:
    from runtime.capabilities.catalog import CAPABILITIES, CATEGORIES
    return (len(CAPABILITIES), len(CATEGORIES),
            len({c["service"] for c in CAPABILITIES}))


def _stated(text: str) -> list[tuple[str, int]]:
    """The catalog counts a line states. Categories and services are read only
    on a line that states a capability count: "10 categories" of something
    else, or the 45 services of the whole registry, are other numbers."""
    out = [("capabilities", int(m.group(1))) for m in _CAPABILITY_COUNT.finditer(text)]
    if out:
        out += [("services", int(m.group(1))) for m in _SERVICE_COUNT.finditer(text)]
        out += [("categories", int(m.group(1))) for m in _CATEGORY_COUNT.finditer(text)]
    return out


def test_the_count_scan_is_not_vacuous():
    stated = _stated("All 221 Web3 capabilities across 21 categories, backed by 44 services; "
                     "the 221-capability catalog; 44 underlying services; 12 checks.")
    assert ("capabilities", 221) in stated and ("services", 44) in stated
    assert ("categories", 21) in stated
    assert stated.count(("capabilities", 221)) == 2 and stated.count(("services", 44)) == 2
    assert not _stated("the 45 services in runtime/blockchain/services/; 10 categories")
    assert not _stated("59 capabilities are flagged unavailable")
    caps, cats, services = _measured()
    assert caps > 100 and cats > 10 and services > 10


def test_every_stated_count_is_the_catalogs():
    caps, cats, services = _measured()
    want = {"capabilities": caps, "categories": cats, "services": services}
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html", "*.py", "*.yaml"],
                                  cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        for lineno, line in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1):
            for kind, n in _stated(line):
                if n != want[kind]:
                    offenders.append(f"{rel}:{lineno}: {n} {kind} (the catalog has {want[kind]})")
    assert not offenders, "\n".join(offenders)
