"""The export sanitizer blocks what it blocked before its private word became a digest.

bridge/sanitizer.py and bridge/exporter.py spelled the private runtime's
namespace in plain regular expressions labelled "Private ...". They now hold the
word as a digest (bridge/held_patterns.py). A matcher that no longer contains
the word could quietly stop matching it, so equivalence is measured, not
assumed, two ways, and neither writes the word into this file:

  * SYNTHETIC. Each held template is rebuilt as a plain expression around a
    synthetic word (with the letters Python's IGNORECASE folds specially), and
    both are run over a generated corpus: same match or no match, same start,
    same `sub` output.
  * FROM HISTORY. The expressions as they stood at 9f4aa37 are read with
    `git show`, the held word is found in them by its digest, and the old
    expressions are compared with today's patterns on a corpus built with that
    word. Skipped where the history is not available (a shallow clone).
"""

from __future__ import annotations

import hashlib
import random
import re
import subprocess
from pathlib import Path

import pytest

from bridge import exporter as exporter_mod
from bridge import sanitizer as sanitizer_mod
from bridge.held_patterns import HELD_WORD_DIGEST, HeldWordPattern

ROOT = Path(__file__).resolve().parent.parent
BASE = "9f4aa37"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _held_patterns() -> list[HeldWordPattern]:
    held = [p for pats in sanitizer_mod.ALL_PATTERN_CATEGORIES.values()
            for p, _ in pats if isinstance(p, HeldWordPattern)]
    held += [p for p in exporter_mod._PRIVATE_PATTERNS if isinstance(p, HeldWordPattern)]
    return held


def _variants(word: str) -> list[str]:
    folds = {"i": ["ı", "İ", "I"], "s": ["ſ", "S"], "k": ["K", "K"]}
    out = [word, word.upper(), word.capitalize(), word[:-1], word[1:], "x" + word,
           word + "y", word + word]
    for i, ch in enumerate(word):
        for alt in folds.get(ch, []):
            out.append(word[:i] + alt + word[i + 1:])
    return out


def _corpus(word: str, seed: int, n: int = 2500) -> list[str]:
    tokens = _variants(word) + [
        ".", "private", ".private.", ".PRIVATE.", "internal", ".internal.", ".security",
        "security", "SecurityLayer", "securitylayer", "_router", "_router.", ".routing",
        "from", "FROM", "import", " ", "  ", "\n", "\t", "#", "# ", "COPYRIGHT",
        "copyright", "a", "Z", "1", "_", "-", "x.y", "(c)",
    ]
    rng = random.Random(seed)
    corpus = []
    for _ in range(n):
        corpus.append("".join(rng.choice(tokens) for _ in range(rng.randint(1, 10))))
    return corpus


def _assert_equivalent(old: re.Pattern, new: HeldWordPattern, corpus: list[str]) -> None:
    for text in corpus:
        a, b = old.search(text), new.search(text)
        assert bool(a) == bool(b), (new.pattern, text)
        if a:
            assert a.start() == b.start(), (new.pattern, text)
        assert old.sub("#S#", text) == new.sub("#S#", text), (new.pattern, text)


def test_held_patterns_match_as_the_plain_expressions_do_for_a_synthetic_word():
    word = "zkisqa"
    templates = sorted({p.pattern for p in _held_patterns()})
    assert len(templates) >= 7, templates
    for template in templates:
        old = re.compile(template.replace("{W}", re.escape(word)), re.IGNORECASE)
        new = HeldWordPattern(template, digest=_sha(word))
        _assert_equivalent(old, new, _corpus(word, seed=len(template)))
        # A planted positive for every template, so the corpus is not vacuous.
        planted = template.replace("{W}", word.upper())
        planted = (planted.replace(r"\s+", " ").replace(r"\.", ".").replace(".*", " x ")
                   .replace(" ?", " "))
        assert new.search(planted), (template, planted)


def _historical_word_and_expressions() -> tuple[str, list[str]]:
    sources = []
    for rel in ("bridge/sanitizer.py", "bridge/exporter.py"):
        try:
            sources.append(subprocess.check_output(
                ["git", "show", f"{BASE}:{rel}"], cwd=ROOT, text=True,
                stderr=subprocess.DEVNULL))
        except (subprocess.CalledProcessError, OSError):
            pytest.skip(f"{BASE} is not in this checkout's history")
    expressions = []
    for src in sources:
        expressions += re.findall(r're\.compile\(r"((?:[^"\\]|\\.)*)"', src)
    word = ""
    for expr in expressions:
        for run in re.findall(r"[A-Za-z]+", expr):
            for i in range(len(run)):
                for k in range(i + 1, len(run) + 1):
                    if _sha(run[i:k].lower()) == HELD_WORD_DIGEST:
                        word = run[i:k].lower()
    assert word, "no expression at the base commit held the word; re-derive this check"
    held = [e for e in expressions if word in e.lower()]
    return word, held


def test_held_patterns_are_the_historical_expressions_and_block_the_same_text():
    word, historical = _historical_word_and_expressions()
    as_templates = {re.sub(re.escape(word), "{W}", e, flags=re.IGNORECASE) for e in historical}
    current = {p.pattern for p in _held_patterns()}
    assert as_templates == current, (sorted(as_templates ^ current))
    by_template = {}
    for p in _held_patterns():
        by_template.setdefault(p.pattern, p)
    for expr in historical:
        template = re.sub(re.escape(word), "{W}", expr, flags=re.IGNORECASE)
        _assert_equivalent(re.compile(expr, re.IGNORECASE), by_template[template],
                           _corpus(word, seed=len(expr), n=1500))


async def test_the_sanitizer_still_blocks_the_private_namespace():
    word, _ = _historical_word_and_expressions()
    from bridge.exporter import ExportBundle
    bundle = ExportBundle(component_name="probe", version="1.0.0",
                          source_files={"a.py": f"from {word}.security import gate\n"
                                                f"x = {word}.private.route()\n"},
                          metadata={}, content_hash="")
    result = await sanitizer_mod.SanitizationValidator().validate(bundle)
    labels = {v["pattern"] for v in result.violations}
    assert not result.is_clean
    assert {"Private security import", "Private runtime routing"} <= labels, labels
    stripped = exporter_mod.ComponentExporter.__new__(exporter_mod.ComponentExporter)
    assert word not in stripped._strip_private_refs(f"{word}.private.x", "a.py").lower()
