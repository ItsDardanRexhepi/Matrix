"""Forbidden-pattern matchers whose private word is held as a digest.

The export sanitizer and exporter block content that names the private
runtime's namespace. They used to spell that namespace in plain regular
expressions, each labelled "Private ..." — so the public tree stated, in text
anyone could read or grep, which word names the private runtime. The word is
now held only as the SHA-256 of its lower-cased spelling, as
tests/test_public_tree_names_no_private_repository.py holds it, and each
pattern is a template with a `{W}` placeholder where the word stood.

A `HeldWordPattern` answers `search` and `sub` the way the regular expression
it replaces does (IGNORECASE, the same surrounding text on each side), so the
sanitizer blocks what it blocked before. tests/test_bridge_held_patterns.py
checks that against the original expressions: rebuilt from a synthetic word on
a generated corpus, and rebuilt from this file's own history where the git
history is available.

What a digest does not do: the word is a common English word, so hashing a word
list recovers it in well under a second. This keeps it out of plain reading and
out of grep, and no more.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# sha256 of the private runtime's namespace word, lower-cased.
HELD_WORD_DIGEST = "6e00cd562cc2d88e238dfb81d9439de7ec843ee9d0c9879d549cb1436786f975"

PLACEHOLDER = "{W}"

# Longest candidate considered for the held word. It is far shorter; the bound
# only keeps the scan linear.
_MAX_WORD = 64

# Under IGNORECASE, Python's `re` also lets these four non-ASCII letters match
# ASCII ones; str.lower() does not map them, so they are folded here to keep
# matching identical.
_SPECIAL_FOLDS = {"İ": "i", "ı": "i", "ſ": "s", "K": "k"}


def _fold(chunk: str) -> str | None:
    out = []
    for ch in chunk:
        low = _SPECIAL_FOLDS.get(ch, ch.lower())
        if len(low) != 1:
            return None
        out.append(low)
    return "".join(out)


@dataclass(frozen=True)
class HeldMatch:
    """The span of one match (enough for truthiness, logging and `sub`)."""

    _start: int
    _end: int
    _text: str

    def start(self) -> int:
        return self._start

    def end(self) -> int:
        return self._end

    def span(self) -> tuple[int, int]:
        return self._start, self._end

    def group(self) -> str:
        return self._text[self._start:self._end]


class HeldWordPattern:
    """`before` + held word + `after`, matched as `re` would match the pattern.

    `before` and `after` are regular-expression fragments. When `after` is
    empty, `before` must not be able to match across a line break (the word is
    then looked for on the line where `before` matched).
    """

    def __init__(self, template: str, flags: int = re.IGNORECASE,
                 digest: str = HELD_WORD_DIGEST) -> None:
        if template.count(PLACEHOLDER) != 1:
            raise ValueError("a held-word template has exactly one {W}")
        before, after = template.split(PLACEHOLDER)
        if not before and not after:
            raise ValueError("a held-word template needs text around {W}")
        if not after and ("\\s" in before or "\\n" in before or "[" in before):
            raise ValueError("with nothing after {W}, the text before it must stay on one line")
        self.pattern = template
        self.flags = flags
        self._digest = digest
        self._before = before
        self._after_re = re.compile(after, flags) if after else None
        self._before_re = re.compile(before, flags) if before else None
        self._before_at_end = re.compile(f"(?:{before})\\Z", flags) if before else None

    # ── the held word ────────────────────────────────────────────────────

    def _is_word(self, chunk: str) -> bool:
        folded = _fold(chunk)
        return folded is not None and hashlib.sha256(folded.encode()).hexdigest() == self._digest

    def _before_start(self, text: str, s: int) -> int | None:
        """Leftmost start of a `before` match that ends exactly at `s`."""
        if self._before_at_end is None:
            return s
        m = self._before_at_end.search(text[:s])
        return m.start() if m else None

    # ── matching ─────────────────────────────────────────────────────────

    def _matches(self, text: str):
        """Every (start, end) of a match, in order of where the word starts."""
        found = []
        if self._after_re is not None:
            pos = 0
            while pos <= len(text):
                m = self._after_re.search(text, pos)
                if not m:
                    break
                p = m.start()
                j = p
                while j > 0 and p - j < _MAX_WORD and text[j - 1].isalpha():
                    j -= 1
                for s in range(j, p):
                    if self._is_word(text[s:p]):
                        start = self._before_start(text, s)
                        if start is not None:
                            after = self._after_re.match(text, p)
                            found.append((s, start, after.end()))
                pos = p + 1
        else:
            for a in self._before_re.finditer(text):
                line_end = text.find("\n", a.start())
                line_end = len(text) if line_end == -1 else line_end
                for run in re.finditer(r"[^\W\d_]+", text[a.start():line_end]):
                    base = a.start() + run.start()
                    word = run.group()
                    for i in range(len(word)):
                        for k in range(1, min(_MAX_WORD, len(word) - i) + 1):
                            s = base + i
                            if self._is_word(text[s:s + k]):
                                start = self._before_start(text, s)
                                if start is not None:
                                    found.append((s, start, s + k))
        found.sort()
        return [(start, end) for _s, start, end in found]

    def search(self, text: str) -> HeldMatch | None:
        matches = self._matches(text)
        if not matches:
            return None
        start, end = min(matches)
        return HeldMatch(start, end, text)

    def sub(self, repl: str, text: str) -> str:
        """Replace non-overlapping matches, leftmost first, with `repl` taken
        literally. Of the matches that start at one place the longest is taken,
        as a greedy expression takes it."""
        longest: dict[int, int] = {}
        for start, end in self._matches(text):
            longest[start] = max(end, longest.get(start, end))
        out, pos = [], 0
        for start in sorted(longest):
            if start < pos:
                continue
            out.append(text[pos:start])
            out.append(repl)
            pos = longest[start]
        out.append(text[pos:])
        return "".join(out)

    def __repr__(self) -> str:
        return f"HeldWordPattern({self.pattern!r})"
