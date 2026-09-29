"""A measurement a test records names the commit it was measured against by subject.

THE DEFECT. The §CC notes in this repository's test docstrings named the tree a
control was measured against by its commit id. The 2026-09 history rewrite
gave every commit a new id, and nine ids cited in seven files' notes named
no commit in this history any more, although each commit they had named was
still here under another id. An id is only as stable as the history it was
read from; a subject is carried across a rewrite.

THE RULE. The prose of every test file — its docstrings and its comments —
names a commit by its subject, quoted after the words "the commit" (between «
and » when the subject itself holds a double quote), and never by its id; and
every subject it names is the subject of a commit in this history, where the
history is here to read (a checkout that is not shallow). An id inside a quoted
subject is part of that subject, not a citation. The first two checks below
hold the §CC notes to this, as the rule was first written; the next two hold
every docstring and comment under tests/ to it.

WHY THE RULE WAS WIDENED. It read the §CC notes only, while its first line
speaks of every measurement a test records. A measurement recorded anywhere
else in a test's prose still named its commit by id: the sixth check's note
below says how many, against which tree. Some of those ids named no commit in
this history any more — the 2026-09 rewrite had changed them, or a later rebase
had — although each commit they had named is still here under another id.

§CC, measured against the tree at the commit "Merge main into
fix/phase0-bypasses: the one-spelling rewrite is schema migration 10, after
engines Phase 1's 8 and 9", with this file added: 1 failed and 1 passed. The
first failed naming the nine ids, at eleven places in seven files; the second
passed, as the one subject a note named then (this file's own) is a commit
here. After the change, both pass, and the second checks every subject the
notes now name.

The counts above are checked against the tree they were measured on: the
third check reads that tree from the history, counts the ids its notes named,
their places and their files the way the first check finds them, and compares
each with the number stated above. Measured with it added: it failed, since
this note said six files where that tree has seven; with the note corrected,
it passes. It is skipped where the history is not here to read.
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: A token shaped like an abbreviated or full commit id: 7 to 40 lower-case
#: hex digits, at least one of each kind, standing alone.
_COMMIT_ID = re.compile(
    r"(?<![0-9A-Za-z_])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}(?![0-9A-Za-z_])")
_BY_SUBJECT = re.compile(r'the commit "([^"]+)"')


def _notes() -> list[tuple[str, str]]:
    """Each §CC note in a test file's docstrings, with the file it is in."""
    notes = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False) or ""
                if "§CC" in doc:
                    notes.append((str(path.relative_to(ROOT)), doc[doc.index("§CC"):]))
    return notes


def test_no_measurement_names_a_commit_by_id():
    by_id = sorted({f"{path}: {token}" for path, note in _notes()
                    for token in _COMMIT_ID.findall(note)})
    assert not by_id, f"a §CC note names a commit by id; name it by subject: {by_id}"


def _history_subjects() -> set[str] | None:
    """Every commit subject in HEAD's history, or None where it is not here
    to read."""
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              check=True, timeout=60).stdout
    try:
        if git("rev-parse", "--is-shallow-repository").strip() != "false":
            return None
        return {line.strip() for line in git("log", "--format=%s", "HEAD").splitlines()}
    except (OSError, subprocess.SubprocessError):
        return None


def test_every_subject_a_measurement_names_is_a_commit_here():
    named = {(path, " ".join(subject.split()))
             for path, note in _notes() for subject in _BY_SUBJECT.findall(note)}
    subjects = _history_subjects()
    if subjects is None:
        pytest.skip("the history is not here to read (no checkout, or a shallow one)")
    unknown = sorted(f"{path}: {subject!r}" for path, subject in named if subject not in subjects)
    assert not unknown, f"a §CC note names a commit this history does not hold: {unknown}"


# ── The counts this file's own note states, against the tree it names ────────

_NUMBER_WORDS = {w: n for n, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}
_STATED = re.compile(r"the (\w+) ids, at (\w+) places in (\w+) files", re.IGNORECASE)


def _notes_in(sources: dict[str, str]) -> list[tuple[str, str]]:
    """_notes(), over the test files *sources* holds (path -> text)."""
    notes = []
    for path, text in sorted(sources.items()):
        if "§CC" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False) or ""
                if "§CC" in doc:
                    notes.append((path, doc[doc.index("§CC"):]))
    return notes


def _test_sources_at(subject: str) -> dict[str, str] | None:
    """The tests/*.py files of the newest commit in HEAD's history whose
    subject is *subject*, or None where the history is not here to read or
    holds no such commit."""
    def git(*args, stdin=None):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True,
                              timeout=120, input=stdin).stdout
    try:
        if git("rev-parse", "--is-shallow-repository").decode().strip() != "false":
            return None
        commit = next((line.split(" ", 1)[0]
                       for line in git("log", "--format=%H %s", "HEAD").decode().splitlines()
                       if line.partition(" ")[2].strip() == subject), None)
        if commit is None:
            return None
        paths = [p for p in git("ls-tree", "-r", "--name-only", commit, "tests")
                 .decode().splitlines() if p.endswith(".py")]
        batch = git("cat-file", "--batch",
                    stdin="".join(f"{commit}:{p}\n" for p in paths).encode())
    except (OSError, subprocess.SubprocessError):
        return None
    sources, at = {}, 0
    for path in paths:
        header_end = batch.index(b"\n", at)
        size = int(batch[at:header_end].split()[2])
        sources[path] = batch[header_end + 1:header_end + 1 + size].decode("utf-8", "replace")
        at = header_end + 1 + size + 1
    return sources


def test_the_counts_this_note_states_are_those_of_the_tree_it_names():
    doc = ast.get_docstring(ast.parse(Path(__file__).read_text(encoding="utf-8")))
    note = " ".join(doc[doc.index("§CC"):].split())
    subject = _BY_SUBJECT.search(note).group(1)
    stated = _STATED.search(note)
    assert stated, "the note no longer states how many ids, places and files it found"
    ids, places, files = (_NUMBER_WORDS[w.lower()] for w in stated.groups())
    sources = _test_sources_at(subject)
    if sources is None:
        pytest.skip("the history is not here to read, or does not hold the named commit")
    found = [(path, token) for path, text in _notes_in(sources)
             for token in _COMMIT_ID.findall(text)]
    measured = (len({t for _, t in found}), len(found), len({p for p, _ in found}))
    assert measured == (ids, places, files), (
        f"the note states {ids} ids at {places} places in {files} files; the tree at the "
        f"commit {subject!r} has {measured[0]} at {measured[1]} in {measured[2]}")


# ── Every docstring and comment under tests/ ────────────────────────────────

_QUOTED = re.compile(r'[Tt]he commit (?:"([^"]+)"|«([^»]+)»)')


def _prose_blocks(text: str) -> list[str]:
    """Every docstring in *text*, and every run of comment lines (one comment
    per line, each alone on its line and in the same column) joined into one
    block, each with its whitespace made single spaces."""
    blocks = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return blocks
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                blocks.append(" ".join(doc.split()))
    lines = text.splitlines()
    run: list[str] = []
    last = (None, None)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        tokens = []
    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        row, col = tok.start
        alone = not lines[row - 1][:col].strip()
        body = re.sub(r"^#:?\s?", "", tok.string)
        if alone and last == (row - 1, col):
            run.append(body)
        else:
            if run:
                blocks.append(" ".join(" ".join(run).split()))
            run = [body]
        last = (row, col) if alone else (None, None)
    if run:
        blocks.append(" ".join(" ".join(run).split()))
    return blocks


def _cited_ids(sources: dict[str, str]) -> list[tuple[str, str]]:
    """(file, id) for every commit id the prose in *sources* names, outside a
    quoted subject."""
    return [(path, token) for path, text in sorted(sources.items())
            for block in _prose_blocks(text)
            for token in _COMMIT_ID.findall(_QUOTED.sub(" ", block))]


def _test_sources() -> dict[str, str]:
    return {str(p.relative_to(ROOT)): p.read_text(encoding="utf-8")
            for p in sorted((ROOT / "tests").rglob("*.py"))}


def test_no_test_prose_names_a_commit_by_id():
    by_id = sorted({f"{path}: {token}" for path, token in _cited_ids(_test_sources())})
    assert not by_id, f"a test's prose names a commit by id; name it by subject: {by_id}"


def test_every_subject_test_prose_names_is_a_commit_here():
    named = {(path, " ".join((a or b).split()))
             for path, text in _test_sources().items()
             for block in _prose_blocks(text) for a, b in _QUOTED.findall(block)}
    subjects = _history_subjects()
    if subjects is None:
        pytest.skip("the history is not here to read (no checkout, or a shallow one)")
    unknown = sorted(f"{path}: {subject!r}" for path, subject in named if subject not in subjects)
    assert not unknown, f"a test's prose names a commit this history does not hold: {unknown}"


_STATED_WIDE = re.compile(r"named (\d+) commits by id at (\d+) places in (\d+) files", re.I)


def test_the_counts_the_widened_rule_states_are_those_of_the_tree_it_names():
    """§CC, measured against the tree at the commit "Where a gate that raises lets
    a read through, the three public texts say the hand-off refuses every
    request", with this file's fourth and fifth checks added: the fourth failed,
    and the fifth passed. The prose of the test files there named 41 commits by
    id at 81 places in 38 files, and 15 of those ids named no commit in this
    history. Each place now names its commit by subject: 13 of the 15 through
    the 2026-09 rewrite's own record of the commit each became, and the other
    two — ids a rebase after the rewrite replaced — by the commits at which the
    counts their note states reproduce. After the change the fourth and fifth
    checks pass. This check reads that tree from the history, counts the ids the
    way the fourth check does, and compares the counts with the ones stated
    here."""
    doc = " ".join(test_the_counts_the_widened_rule_states_are_those_of_the_tree_it_names
                   .__doc__.split())
    subject = _QUOTED.search(doc)
    stated = _STATED_WIDE.search(doc)
    assert subject and stated, "the note no longer names its tree or states its counts"
    sources = _test_sources_at(subject.group(1) or subject.group(2))
    if sources is None:
        pytest.skip("the history is not here to read, or does not hold the named commit")
    found = _cited_ids(sources)
    measured = (len({t for _, t in found}), len(found), len({p for p, _ in found}))
    assert measured == tuple(int(x) for x in stated.groups()), (
        f"the note states {stated.groups()}; the tree has {measured}")
