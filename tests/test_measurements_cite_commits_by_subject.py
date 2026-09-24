"""A measurement a test records names the commit it was measured against by subject.

THE DEFECT. The §CC notes in this repository's test docstrings named the tree a
control was measured against by its commit id. The 2026-09 history rewrite
gave every commit a new id, and nine ids cited in six files' notes named no
commit in this history any more, although each commit they had named was
still here under another id. An id is only as stable as the history it was
read from; a subject is carried across a rewrite.

THE RULE. A §CC note (from "§CC" to the end of the docstring it sits in) names
a commit by its subject, quoted after the words "the commit", and never by id;
and every subject it names is the subject of a commit in this history, where
the history is here to read (a checkout that is not shallow).

§CC, measured against the tree at the commit "Merge main into
fix/phase0-bypasses: the one-spelling rewrite is schema migration 10, after
engines Phase 1's 8 and 9", with this file added: 1 failed and 1 passed. The
first failed naming the nine ids, at eleven places in six files; the second
passed, as the one subject a note named then (this file's own) is a commit
here. After the change, both pass, and the second checks every subject the
notes now name.
"""

from __future__ import annotations

import ast
import re
import subprocess
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
