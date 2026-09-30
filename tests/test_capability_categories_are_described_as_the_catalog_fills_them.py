"""What the text says about the capability categories is how the catalog fills them.

The README said "195 capabilities across 21 categories". runtime/capabilities/
catalog.py declares 21 categories, and one of them, Security & Wallets, holds no
capability: MPC signing, social recovery and session keys, the capabilities a
reader would look for there, are catalogued under Privacy & ZK. The count is
held to the categories that hold a capability elsewhere
(tests/test_stated_capability_counts_are_the_catalogs.py); this reads the rest
of the shape, derived from the catalog, never typed in:

  * a sentence that says a named category holds nothing names a category that
    holds nothing;
  * a sentence that states how many categories are declared states the
    catalog's number and names every category that holds nothing, so the
    declared count is never read as a count of populated categories;
  * a category list that names MPC signing, social recovery or session keys in
    a category's parentheses names the category the catalog puts them in.

The changelog records history on purpose and legal copy is changed only by
counsel; neither is read.

What this cannot see: a category described as empty, or MPC placed in a
category, in words other than the ones below.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_NOT_READ = {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}
_EMPTY = re.compile(r"holds? (?:none|no capabilit)|\bhas 0\b|\bempty\b|no capabilities in it")
_DECLARED = re.compile(
    r"\b(\d{1,3}|twenty-one|twenty|twenty-two)\b(?: are)? declared\b"
    r"|\b(\d{1,3}|twenty-one|twenty|twenty-two) declared categor"
    r"|\b(\d{1,3}) buckets\b"
    r"|\bdeclares (?:a )?(twenty-first|twenty-second|\d{1,3}(?:st|nd|rd|th)) categor"
    r"|\bdeclares (\d{1,3}|twenty-one|twenty|twenty-two) categor")
_WORDS = {"twenty": 20, "twenty-one": 21, "twenty-two": 22,
          "twenty-first": 21, "twenty-second": 22}
# The catalog ids of the capabilities a reader would look for under security.
_WALLET_SECURITY = {"mpc_sign": r"\bmpc\b", "recover_wallet": r"social recovery",
                    "create_session_key": r"session keys?"}


def _catalog() -> dict:
    from runtime.capabilities.catalog import CAPABILITIES, CATEGORIES

    held = {c["category"] for c in CAPABILITIES}
    names = {c["id"]: c["name"].lower() for c in CATEGORIES}
    by_id = {c["id"]: c["category"] for c in CAPABILITIES}
    return {
        "declared": len(CATEGORIES),
        "names": names,
        "empty": {names[i] for i in names if i not in held},
        "placed": {cap: names[by_id[cap]] for cap in _WALLET_SECURITY},
    }


def _number(match: re.Match) -> int:
    raw = next(g for g in match.groups() if g)
    if raw in _WORDS:
        return _WORDS[raw]
    return int(re.match(r"\d+", raw).group())


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).lower()
    return [s for s in re.split(r"(?<=[.!?])\s+|\s*```\s*", flat) if s.strip()]


def _problems(rel: str, text: str, cat: dict) -> list[str]:
    out = []
    names = sorted(cat["names"].values(), key=len, reverse=True)
    for sentence in _sentences(text):
        # A named category said to hold nothing: the name within a few words
        # of the phrase, and "category" or "bucket" near both (a portfolio's
        # DeFi group being empty is not the DeFi category).
        for m in _EMPTY.finditer(sentence):
            before = sentence[max(0, m.start() - 40):m.start()]
            if not re.search(r"categor|bucket", sentence[max(0, m.start() - 80):m.end() + 20]):
                continue
            said = {n for n in names if n in before}
            for name in said - cat["empty"]:
                out.append(f"{rel}: {name!r} is said to hold nothing: ...{sentence[:160]}...")
        # A declared count, with the empty categories named beside it.
        if "categor" in sentence or "bucket" in sentence:
            for m in _DECLARED.finditer(sentence):
                if _number(m) != cat["declared"]:
                    out.append(f"{rel}: {_number(m)} categories declared; the catalog "
                               f"declares {cat['declared']}: ...{sentence[:160]}...")
                missing = {n for n in cat["empty"] if n not in sentence}
                if missing or not _EMPTY.search(sentence):
                    out.append(f"{rel}: the declared count is stated without saying "
                               f"{sorted(cat['empty'])} holds nothing: ...{sentence[:160]}...")
        # MPC, recovery and session keys, placed in a category's parentheses.
        for m in re.finditer(r"([a-z&,' -]{2,40})\(([^()]*)\)", sentence):
            head, inside = m.group(1).strip(" ,"), m.group(2)
            category = next((n for n in names if head.endswith(n)), None)
            if category is None and head.endswith(("security", "wallets", "security and wallets")):
                category = "security & wallets"
            if category is None:
                continue
            for cap, pattern in _WALLET_SECURITY.items():
                if re.search(pattern, inside) and category != cat["placed"][cap]:
                    out.append(f"{rel}: {cap} is listed under {category!r}; the catalog "
                               f"puts it under {cat['placed'][cap]!r}")
    return out


def _surfaces() -> list[str]:
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    return [rel for rel in out.splitlines()
            if rel not in _NOT_READ and not rel.startswith("tests/") and (ROOT / rel).is_file()]


def test_the_measured_shape():
    """The premises the text is read against, measured."""
    cat = _catalog()
    assert cat["declared"] == 21
    assert cat["empty"] == {"security & wallets"}
    assert set(cat["placed"].values()) == {"privacy & zk"}


def test_the_scan_sees_the_wrong_shapes():
    cat = _catalog()
    wrong = ("The catalog declares 22 categories. The Identity category has 0 capabilities. "
             "The categories route returns 21 buckets. "
             "security & wallets (MPC signing, social recovery, session keys).")
    problems = _problems("x", wrong, cat)
    assert any("22 categories declared" in p for p in problems), problems
    assert any("'identity' is said to hold nothing" in p for p in problems), problems
    assert any("without saying" in p for p in problems), problems
    assert sum("is listed under 'security & wallets'" in p for p in problems) == 3, problems
    right = ("privacy & ZK (ZK proofs, and MPC signing, social recovery and session keys). "
             "The catalog also declares a Security & Wallets category that holds none. "
             "Return the 21 declared categories with per-category capability counts "
             "(Security & Wallets has 0).")
    assert not _problems("x", right, cat)


def test_the_text_describes_the_categories_as_the_catalog_fills_them():
    cat = _catalog()
    problems, read = [], 0
    for rel in _surfaces():
        text = (ROOT / rel).read_text(encoding="utf-8")
        read += "security & wallets" in text.lower()
        problems += _problems(rel, text, cat)
    assert read, "no surface names Security & Wallets; the reader sees nothing"
    assert not problems, "\n".join(problems)
