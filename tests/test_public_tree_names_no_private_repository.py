"""The public tree must not hand out the name or access shape of a private repo.

This repository is public and installable with one `curl | bash`. Its tracked
files named the closed-source security core by its private repository name, gave
the doc paths inside that repository, and spelled out the `git+ssh` install and
deploy-key shape a build needs to reach it. None of that is needed to USE the
seam — the seam binds by Python import name (`morpheus_security`), which stays —
but all of it tells an attacker exactly which private repository, and which
credential, the whole enforcement layer lives behind.

What this file holds, and what it does not:

  * the forbidden repository names are held only as SHA-256 digests of their
    NORMALISED spelling (lower-cased, every separator removed), and every run of
    one to four words in every tracked file is normalised the same way and
    hashed — so `Name-Of-Repo`, `Name Of Repo`, `name_of_repo`, `NameOfRepo`
    and a spelling broken across a line all match. Neither the names nor pieces
    of them appear in this file, and the planted positive uses a synthetic name
    generated at run time with its own digest.
  * a digest does NOT stop a reader who already has a candidate name from
    confirming it. No detector that runs on the public tree can avoid that: it
    must be able to recognise the name. What the tree no longer does is give the
    name to a reader who does not already have it.
  * the private deployment repository is addressed by a common word, so it is
    matched as a word: `Matrix` standing alone (a path segment, `Matrix deploy`,
    `the Matrix private runtime`, `Matrix register entry`) is refused; the
    project's film references (`Welcome to the Matrix`, `Matrix rain`) and
    identifiers that merely contain the word (`MatrixCoin`, `0pnMatrx`) are not
    names of a repository and pass.
  * `git+ssh://` install URLs are refused anywhere, and a backticked `*.md`
    reference in the operator docs must resolve to a file that is actually in
    this tree — a doc path that only exists in a private repository is exactly
    the leak, and it is also a dead link for every public reader.

The digests were checked against the tree before the fix: the name test failed
with nine hits in four files, so they encode the real names.
"""

from __future__ import annotations

import bisect
import hashlib
import re
import secrets
import string
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# sha256 of the normalised private repository names (current and former).
_PRIVATE_REPO_DIGESTS = frozenset({
    "2dfc44d49207c2b203fd77fe7ed18b742834e50f879bc48bca5b565684622ab4",
    "cac896330e55d3ed2b3e9e583345bfdc344d9a50a157a896c9db1f12865050a6",
})

_MAX_WORDS = 4

# Alphanumeric runs, then split on case changes so CamelCase yields its words.
_RUN = re.compile(r"[A-Za-z0-9]+")
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")

# The private deployment repository as a standalone word. A letter, digit or
# underscore on either side means it is part of an identifier, not the name.
_PRIVATE_DEPLOY_WORD = re.compile(r"(?<![A-Za-z0-9_])Matrix(?![A-Za-z0-9_])")
_FILM_REFERENCES = ("Welcome to the Matrix", "Matrix rain")

# Docs an operator follows step by step; every `x.md` they cite must exist here.
_OPERATOR_DOCS = ["CREDENTIALS_NEEDED.md", "docs/OPS.md", "README.md",
                  "SECURITY_STUB.md", ".github/SECURITY.md",
                  "runtime/security/SECURITY_INTERFACE.md"]


def _tracked_text_files() -> list[Path]:
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    files = []
    for rel in out.splitlines():
        p = ROOT / rel
        if not p.is_file():
            continue
        try:
            p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        files.append(p)
    return files


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _digest(name: str) -> str:
    return hashlib.sha256(_normalise(name).encode()).hexdigest()


def _name_hits(text: str, digests: frozenset[str]) -> list[int]:
    """Line numbers where a run of 1.._MAX_WORDS words normalises to a digest."""
    words: list[tuple[str, int]] = []
    line_starts = [0] + [m.end() for m in re.finditer(r"\n", text)]
    for run in _RUN.finditer(text):
        lineno = bisect.bisect_right(line_starts, run.start())
        for w in _WORD.findall(run.group()):
            words.append((w.lower(), lineno))
    hits = []
    for i in range(len(words)):
        joined = ""
        for n in range(_MAX_WORDS):
            if i + n >= len(words):
                break
            joined += words[i + n][0]
            if hashlib.sha256(joined.encode()).hexdigest() in digests:
                hits.append(words[i][1])
    return hits


def _deploy_word_hits(text: str) -> list[tuple[int, str]]:
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        scrubbed = line
        for phrase in _FILM_REFERENCES:
            scrubbed = scrubbed.replace(phrase, "")
        if _PRIVATE_DEPLOY_WORD.search(scrubbed):
            hits.append((lineno, line.strip()[:100]))
    return hits


def test_name_matcher_catches_every_spelling_of_a_planted_name():
    """Planted positive with a synthetic name: the matcher is not vacuous, and it
    is not blind to spacing, separators, case or a line break."""
    parts = ["Zq" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(6)),
             "Planted", "Vault"]
    digests = frozenset({_digest("".join(parts))})
    spellings = [
        "-".join(parts), " ".join(parts), "_".join(p.lower() for p in parts),
        "".join(parts), "".join(parts).lower(), "_".join(parts).upper(),
        f"{parts[0]} {parts[1]}\n{parts[2]}",
        f"pip install git+ssh://host/{'-'.join(parts)}.git",
    ]
    for spelling in spellings:
        assert _name_hits(f"see {spelling} here", digests), spelling
    assert not _name_hits(f"{parts[0]} and {parts[1]} alone", digests)
    # The real digest set is a different set: the synthetic name is not in it.
    assert not _name_hits(" ".join(parts), _PRIVATE_REPO_DIGESTS)


def test_deploy_word_matcher_catches_the_word_and_passes_identifiers():
    for line in ("# APNs push (Matrix deploy)", "from the Matrix private runtime",
                 "see /Users/x/Matrix/derived", "Matrix-side exporter",
                 "(Matrix register entry::X)"):
        assert _deploy_word_hits(line), line
    for line in ("Welcome to the Matrix", "/* Matrix rain effect */",
                 "a token called MatrixCoin", "0pnMatrx", "MatrixBridge now"):
        assert not _deploy_word_hits(line), line


def test_no_tracked_file_names_a_private_repository():
    offenders = []
    for path in _tracked_text_files():
        for lineno in _name_hits(path.read_text(encoding="utf-8"),
                                 _PRIVATE_REPO_DIGESTS):
            offenders.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert not offenders, (
        "tracked files name a private repository (the security core's access "
        "target): " + ", ".join(offenders))


def test_no_tracked_file_names_the_private_deployment_or_an_install_url():
    this_file = Path(__file__).resolve()
    offenders = []
    for path in _tracked_text_files():
        if path.resolve() == this_file:
            continue
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for lineno, line in _deploy_word_hits(text):
            offenders.append(f"{rel}:{lineno}: {line}")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "git+ssh://" in line:
                offenders.append(f"{rel}:{lineno}: {line.strip()[:100]}")
    assert not offenders, "\n".join(offenders)


def test_operator_docs_cite_only_documents_that_exist_in_this_tree():
    tracked_names = {p.name for p in _tracked_text_files()}
    dangling = []
    for doc in _OPERATOR_DOCS:
        path = ROOT / doc
        if not path.exists():
            continue
        for ref in re.findall(r"`([^`\s]+\.md)`", path.read_text(encoding="utf-8")):
            if Path(ref).name not in tracked_names:
                dangling.append(f"{doc} -> {ref}")
    assert not dangling, (
        "operator docs cite documents that are not in this repository (a path "
        "into a private checkout): " + ", ".join(dangling))
