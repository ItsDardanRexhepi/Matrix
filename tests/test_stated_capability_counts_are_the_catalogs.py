"""Every count of the platform's capabilities, categories, backing services,
registry services and platform actions that the public text states is the
count the code has.

The README, the docs, the Trinity system prompt, the SDK, the landing page and
three courses said "221 capabilities across 21 categories, backed by 44
services". runtime/capabilities/catalog.py — the inventory those sentences
cite, and what `GET /api/v1/capabilities` serves — holds 195 capabilities,
served by 43 distinct services. It declares 21 categories, and one of them
(Security & Wallets) holds no capability, so the capabilities span 20. The
number stayed after the fabricated capabilities were removed from the catalog.

The counts are derived here from the code, never typed in:

  * every "<N> capabilities", "<N> Web3 capabilities", "<N>-capability" or
    "<N> Capabilities", and the categories and services stated in the same
    SENTENCE, must equal the catalog's: the categories that hold a capability
    and the services that back one. A sentence is read across line breaks: a
    count split over two lines is still a count ("the canonical inventory of
    221\\ncapabilities across 21 categories, served by 44 underlying services"
    in the API reference was missed when this read single lines);
  * a sentence with no capability count that states the whole service set
    ("<N> blockchain services", "all <N> services", "any of <N> services",
    "<N> services in runtime/blockchain/services") must state the size of the
    service registry (runtime/blockchain/services/registry.py);
  * "<N> platform actions" is the size of ACTION_MAP, the actions the
    `platform_action` tool dispatches;
  * "<N>+" is a bound, not a count, and is not accepted for any of these;
  * the landing page's stats bar shows only counts measured here.

The changelog records history on purpose and legal copy is changed only by
counsel; neither is read.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_NOT_READ = {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}
# A subset count ("59 capabilities are flagged unavailable", "62 capabilities
# flagged unavailable") is not a count of the catalog.
_CAPABILITY_COUNT = re.compile(
    r"\b(\d{2,4})(\+?)(?:-capability\b|\s+(?:discrete\s+)?(?:Web3\s+|blockchain\s+)?"
    r"capabilities\b(?!\s+(?:are|flagged|marked)\b))",
    re.I)
_SERVICE_COUNT = re.compile(r"\b(\d{2,4})(\+?)\s+(?:underlying\s+|backing\s+)?services\b", re.I)
_CATEGORY_COUNT = re.compile(r"\b(\d{1,3})(\+?)\s+(?:discoverable\s+)?categor(?:y|ies)\b", re.I)
# The whole service set, stated without a capability count beside it.
_REGISTRY_COUNT = re.compile(
    r"\b(?:all\s+(?:the\s+)?|any\s+of\s+(?:the\s+)?)(\d{2,4})(\+?)\s+(?:blockchain\s+)?services\b"
    r"|\b(\d{2,4})(\+?)\s+blockchain\s+services\b"
    r"|\b(\d{2,4})(\+?)\s+services\s+in\s+`?runtime/blockchain/services",
    re.I)
# "(44 services across 21 categories)": the catalog's services and categories,
# stated without the capability count beside them.
_SERVICES_ACROSS = re.compile(
    r"\b(\d{2,4})(\+?)\s+services\s+across\s+(\d{1,3})(\+?)\s+categor", re.I)
_ACTION_COUNT = re.compile(r"\b(\d{2,4})(\+?)\s+platform\s+actions\b", re.I)

# In prose, a blank line, a list item, a heading, a table row or a block tag
# ends a block. In code, "# " starts a comment line, not a heading, so only a
# blank (or bare-marker) line does, and comment lines are joined into their
# sentences. Comment markers at the start of a line are not words.
_BLOCK_BREAK = re.compile(r"\n[ \t]*\n|\n(?=[ \t]*(?:[-*|>]|#{1,6}\s|\d+\.\s|</?(?:li|p|div|h\d|tr|td)\b))")
_CODE_BLOCK_BREAK = re.compile(r"\n[ \t]*(?:#|//|\*)?[ \t]*\n")
_LINE_MARKER = re.compile(r"^[ \t]*(?:#(?!#)|//|\*(?!\*)|>)?[ \t]*", re.M)


def _measured() -> dict[str, int]:
    from runtime.blockchain.services.registry import _SERVICE_MAP
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    from runtime.capabilities.catalog import CAPABILITIES, CATEGORIES
    held = {c["category"] for c in CAPABILITIES}
    return {
        "capabilities": len(CAPABILITIES),
        "categories": sum(1 for c in CATEGORIES if c["id"] in held),
        "services": len({c["service"] for c in CAPABILITIES}),
        "registry services": len(_SERVICE_MAP),
        "platform actions": len(ACTION_MAP),
        "dispatched services": len({service for service, _method in ACTION_MAP.values()}),
    }


def _sentences(text: str, code: bool = False) -> list[tuple[int, str]]:
    """(first line number, sentence) for every sentence, read across lines."""
    out = []
    pos = 0
    for block in (_CODE_BLOCK_BREAK if code else _BLOCK_BREAK).split(text):
        start = text.find(block, pos)
        lineno = text.count("\n", 0, max(start, 0)) + 1
        pos = max(start, pos) + len(block)
        flat = re.sub(r"\s+", " ", _LINE_MARKER.sub("", block))
        flat = re.sub(r"<[^>]+>", " ", flat)
        for sentence in re.split(r"(?<=[.!?])\s+", flat):
            if sentence.strip():
                out.append((lineno, sentence))
    return out


def _numbers(pattern: re.Pattern, text: str) -> list[tuple[int, str]]:
    out = []
    for m in pattern.finditer(text):
        groups = [g for g in m.groups()]
        pairs = [(groups[i], groups[i + 1]) for i in range(0, len(groups), 2)]
        n, plus = next((a, b) for a, b in pairs if a is not None)
        out.append((int(n), plus or ""))
    return out


def _stated(sentence: str) -> list[tuple[str, int, str]]:
    """(kind, number, "+" or "") for each count a sentence states. Categories
    and services are read as the catalog's only in a sentence that states a
    capability count: "10 categories" of something else is another number."""
    out = [("capabilities", n, p) for n, p in _numbers(_CAPABILITY_COUNT, sentence)]
    if out:
        out += [("services", n, p) for n, p in _numbers(_SERVICE_COUNT, sentence)]
        out += [("categories", n, p) for n, p in _numbers(_CATEGORY_COUNT, sentence)]
    else:
        for m in _SERVICES_ACROSS.finditer(sentence):
            out += [("services", int(m.group(1)), m.group(2)),
                    ("categories", int(m.group(3)), m.group(4))]
        out += [("registry services", n, p) for n, p in _numbers(_REGISTRY_COUNT, sentence)]
    out += [("platform actions", n, p) for n, p in _numbers(_ACTION_COUNT, sentence)]
    return out


_REACHES = re.compile(r"\breaches\s+(\d{2,4})\b", re.I)


def _problems(rel: str, text: str, want: dict[str, int]) -> list[str]:
    problems = []
    for lineno, sentence in _sentences(text, code=rel.endswith((".py", ".yaml"))):
        # The registry's services are not all reached through ServiceDispatcher
        # or its `platform_action` tool (they dispatch ACTION_MAP), so a
        # sentence that puts the two together says how many are reached.
        if (re.search(r"ServiceDispatcher|platform_action", sentence)
                and _numbers(_REGISTRY_COUNT, sentence)
                and not _CAPABILITY_COUNT.search(sentence)):
            reached = [int(n) for n in _REACHES.findall(sentence)]
            if reached != [want["dispatched services"]]:
                problems.append(f"{rel}:{lineno}: the registry's services are said to be "
                                f"reached through the dispatcher, which reaches "
                                f"{want['dispatched services']} of them")
        for kind, n, plus in _stated(sentence):
            if plus:
                problems.append(f"{rel}:{lineno}: {n}+ {kind} is a bound, not the count "
                                f"({want[kind]})")
            elif n != want[kind]:
                problems.append(f"{rel}:{lineno}: {n} {kind} (the code has {want[kind]})")
    return problems


def test_the_count_scan_is_not_vacuous():
    stated = [(k, n) for _l, s in _sentences(
        "All 221 Web3 capabilities across 21 categories, backed by 44 services; "
        "the 221-capability catalog; 44 underlying services; 12 checks.")
        for k, n, _p in _stated(s)]
    assert ("capabilities", 221) in stated and ("services", 44) in stated
    assert ("categories", 21) in stated
    assert stated.count(("capabilities", 221)) == 2 and stated.count(("services", 44)) == 2
    assert not [k for _l, s in _sentences("10 categories of something; 12 checks")
                for k, *_ in _stated(s)]
    assert not _stated("59 capabilities are flagged unavailable")
    assert not _stated("measured, 62 capabilities flagged unavailable and 62 installed")
    want = _measured()
    assert want["capabilities"] > 100 and want["categories"] > 10 and want["services"] > 10
    assert want["registry services"] >= want["services"] and want["platform actions"] > 100


def test_a_count_split_across_lines_or_stated_as_a_bound_is_read():
    want = {"capabilities": 195, "categories": 20, "services": 43,
            "registry services": 45, "platform actions": 253, "dispatched services": 44}
    split = ("backed by\n`runtime/capabilities/catalog.py` — the canonical inventory of 221\n"
             "capabilities across 21 categories, served by 44 underlying services.\n")
    assert len(_problems("api-reference.md", split, want)) == 3
    assert _problems("README.md", "surface — 50+ blockchain services spanning DeFi", want)
    assert _problems("README.md", "  50+ Blockchain Services\n  200+ Platform Actions", want)
    assert len(_problems("x.yaml", "  # Blockchain services (44 services across 21 "
                         "categories). Each follows the same", want)) == 2
    assert _problems("x.py", '"""any of 44 services"""', want)
    assert not _problems("x.py", "# the 45 services in runtime/blockchain/services/** have",
                         want)
    assert not _problems("x.py", "# 42 of 44 services have the same pattern", want)
    assert _problems("x.py", "# So `platform_action`, the one\n# handler through which the "
                     "agent reaches all 45 services, relayed it.", want)
    assert _problems("README.md", "The complete Web3 surface — 45 blockchain services "
                     "spanning DeFi — is wired through `ServiceDispatcher` and tested.", want)
    assert not _problems("README.md", "45 blockchain services live in one registry, and "
                         "`ServiceDispatcher` reaches 44 of them.", want)
    assert not _problems("README.md", "195 capabilities across 20 categories (the catalog "
                         "declares 21; one holds none), backed by 43 services.", want)


def test_every_stated_count_is_the_codes():
    want = _measured()
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html", "*.py", "*.yaml"],
                                  cwd=ROOT, text=True)
    problems = []
    for rel in out.splitlines():
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        problems += _problems(rel, (ROOT / rel).read_text(encoding="utf-8"), want)
    assert not problems, "\n".join(problems)


_STAT = re.compile(r'<div class="stat-num">([^<]*)</div>\s*<div class="stat-label">([^<]*)</div>')
_STAT_MEASURES = {"web3 capabilities": "capabilities", "categories": "categories",
                  "backing services": "services"}


def test_the_landing_stats_are_measured_counts():
    """The stats bar showed "89 Available Actions" and "329 Tests Passing".
    Neither was measured: the catalog has 133 capabilities flagged available
    and ACTION_MAP 253 actions, and the suite collects thousands of tests and
    changes with every commit. A stat must be one of the counts measured here."""
    want = _measured()
    stats = _STAT.findall((ROOT / "web" / "landing.html").read_text(encoding="utf-8"))
    assert stats, "web/landing.html has no stats bar"
    problems = []
    for number, label in stats:
        kind = _STAT_MEASURES.get(label.strip().lower())
        if kind is None:
            problems.append(f"{number} {label!r}: not a count this test measures")
        elif number.strip() != str(want[kind]):
            problems.append(f"{number} {label!r}: the code has {want[kind]}")
    assert not problems, "\n".join(problems)
