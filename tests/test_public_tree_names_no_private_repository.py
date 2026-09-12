"""The public tree must not hand out the name or access shape of a private repo.

This repository is public and installable with one `curl | bash`. Its tracked
files named the closed-source security core by its private repository name, gave
the doc paths inside that repository, and spelled out the `git+ssh` install and
deploy-key shape a build needs to reach it. None of that is needed to USE the
seam, which binds by its Python import name, but all of it tells an attacker
which private repository, and which credential, the enforcement layer lives
behind.

What this file holds, and what it does not:

  * no private repository name is written in this file, in any spelling. Each
    is held as a SHA-256 digest, and the planted positives use synthetic words
    generated at run time with their own digests. The file scans itself like
    any other tracked file; it has no exemption.
  * the security core's names (current and former) are multi-word. They are
    held as digests of their NORMALISED spelling (lower-cased, separators
    removed), and every run of one to four words in every tracked file is
    normalised and hashed, so hyphen, space, underscore, CamelCase and
    line-broken spellings all match.
  * the private deployment repository's name is a single common word. It is
    held as the digest of that word, lower-cased, and every standalone token
    (letters, digits and underscore; anything else is a boundary) is hashed
    case-insensitively, so a path segment, a capitalised or upper-case word and
    a lower-case one all match, while an identifier that merely contains the
    word does not. Two kinds of occurrence pass, and both are pinned by digest,
    not by plain text: a token whose surrounding words form one of two
    decorative phrases the project's pages and installer use (the preceding
    three words, or the following word, hashed with it), and seven exact
    lines of the export sanitizer's pattern table (hashed with their path),
    which is what that sanitizer blocks. Any other occurrence fails, including a new line in those files.
  * `git+ssh` install URLs are refused anywhere, and a backticked `*.md`
    reference in the operator docs must resolve to a file that is actually in
    this tree — a doc path that only exists in a private repository is exactly
    the leak, and it is also a dead link for every public reader.

What a digest does not do. It does not stop a reader who already has a
candidate name from confirming it; no detector that runs on the public tree can
avoid that, because it must recognise the name. For the single common word it
does less: hashing an English word list recovers it in well under a second, so
that digest keeps the word out of plain reading and out of grep, and no more.
Pieces of the names are also public by necessity elsewhere in the tree: the
seam's import name shares two words with the current core name. What this file
no longer does is state, in plain text, which word names which private
repository.

The digests were checked against the tree before each fix: on a copy of
9f4aa37 the core-name test fails with nine hits in three files, and on a copy of
8f8b724 the deployment-word test fails with 31 hits in 12 files.
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

# sha256 of the normalised security-core repository names (current and former).
_PRIVATE_REPO_DIGESTS = frozenset({
    "2dfc44d49207c2b203fd77fe7ed18b742834e50f879bc48bca5b565684622ab4",
    "cac896330e55d3ed2b3e9e583345bfdc344d9a50a157a896c9db1f12865050a6",
})

# sha256 of the private deployment repository's one-word name, lower-cased.
_DEPLOY_WORD_DIGEST = "6e00cd562cc2d88e238dfb81d9439de7ec843ee9d0c9879d549cb1436786f975"

# sha256 of the lower-cased context (three preceding tokens + the word, or the
# word + the following token) of the two decorative phrases.
_DEPLOY_WORD_ALLOWED_CONTEXTS = frozenset({
    "2510deb1de9187f4db19f10a90a9914cc598083477c1f22067455cb8dee88518",
    "8eb056ca3f9c63b359f56f84b1c9dc4c0a07d01be1422a8ff58de0f5d53173c6",
})

# sha256 of "<path>:<stripped line>" for the export sanitizer's pattern lines.
_DEPLOY_WORD_PINNED_LINES = frozenset({
    "2d4c5103e3b4d00e986de69b7b9ad4cb7f05049b231bc2d901dcd32243e2d779",  # bridge/exporter.py
    "88c7af9ccd4e37a59650ad81b730ada379b9c5dbfa25b7cb28d3b2d61ed13406",  # bridge/sanitizer.py
    "43c88fa75778f6863540c9b7ff11641ebd6be1f4bf51501be25254c6ac92e2b9",
    "6da34a3047dd39b9c8ff04f561410f61021d2765e208c72572688b72ac74c974",
    "08b35d533fa4b7f83cd67514f3b641b77db12b45243e83ec2f384151c305e2e5",
    "fc2a9ae388420318de23663455ab109a513551a277064cbc5492ca4ee3586b45",
    "7f8fcbaaed01f33e962c7757aaaceb9d763d3d1d93f931a47671a0596d9d7a1c",
})

_MAX_WORDS = 4

# Alphanumeric runs, then split on case changes so CamelCase yields its words.
_RUN = re.compile(r"[A-Za-z0-9]+")
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")
# Standalone tokens for the one-word name: an identifier is one token.
_TOKEN = re.compile(r"[A-Za-z0-9_]+")
# An install URL: the scheme followed by a host.
_INSTALL_URL = re.compile(r"git\+ssh://[\w@.-]+")

# Docs an operator follows step by step; every `x.md` they cite must exist here.
_OPERATOR_DOCS = ["CREDENTIALS_NEEDED.md", "docs/OPS.md", "README.md",
                  "SECURITY_STUB.md", ".github/SECURITY.md",
                  "runtime/security/SECURITY_INTERFACE.md"]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


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
    return _sha(_normalise(name))


def _line_of(text: str):
    line_starts = [0] + [m.end() for m in re.finditer(r"\n", text)]
    return lambda offset: bisect.bisect_right(line_starts, offset)


def _name_hits(text: str, digests: frozenset[str]) -> list[int]:
    """Line numbers where a run of 1.._MAX_WORDS words normalises to a digest."""
    line_of = _line_of(text)
    words: list[tuple[str, int]] = []
    for run in _RUN.finditer(text):
        lineno = line_of(run.start())
        for w in _WORD.findall(run.group()):
            words.append((w.lower(), lineno))
    hits = []
    for i in range(len(words)):
        joined = ""
        for n in range(_MAX_WORDS):
            if i + n >= len(words):
                break
            joined += words[i + n][0]
            if _sha(joined) in digests:
                hits.append(words[i][1])
    return hits


def _deploy_word_hits(text: str, rel: str, *, word_digest: str = _DEPLOY_WORD_DIGEST,
                      allowed_contexts: frozenset[str] = _DEPLOY_WORD_ALLOWED_CONTEXTS,
                      pinned_lines: frozenset[str] = _DEPLOY_WORD_PINNED_LINES,
                      ) -> list[tuple[int, str]]:
    """(line, text) for each standalone token whose lower-cased digest is the
    deployment word, unless its context or its whole line is pinned by digest."""
    line_of = _line_of(text)
    lines = text.splitlines()
    tokens = [(m.group().lower(), m.start()) for m in _TOKEN.finditer(text)]
    hits = []
    for i, (tok, start) in enumerate(tokens):
        if _sha(tok) != word_digest:
            continue
        before = "".join(t for t, _ in tokens[max(0, i - 3):i]) + tok
        after = tok + (tokens[i + 1][0] if i + 1 < len(tokens) else "")
        if _sha(before) in allowed_contexts or _sha(after) in allowed_contexts:
            continue
        lineno = line_of(start)
        line = lines[lineno - 1] if lineno - 1 < len(lines) else ""
        if _sha(f"{rel}:{line.strip()}") in pinned_lines:
            continue
        hits.append((lineno, line.strip()[:100]))
    return hits


def _synthetic_word(prefix: str = "Zq") -> str:
    return prefix + "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))


def test_name_matcher_catches_every_spelling_of_a_planted_name():
    """Planted positive with a synthetic name: the matcher is not vacuous, and it
    is not blind to spacing, separators, case or a line break."""
    parts = [_synthetic_word(), "Planted", "Vault"]
    digests = frozenset({_digest("".join(parts))})
    spellings = [
        "-".join(parts), " ".join(parts), "_".join(p.lower() for p in parts),
        "".join(parts), "".join(parts).lower(), "_".join(parts).upper(),
        f"{parts[0]} {parts[1]}\n{parts[2]}",
        f"pip install from host/{'-'.join(parts)}.git",
    ]
    for spelling in spellings:
        assert _name_hits(f"see {spelling} here", digests), spelling
    assert not _name_hits(f"{parts[0]} and {parts[1]} alone", digests)
    # The real digest set is a different set: the synthetic name is not in it.
    assert not _name_hits(" ".join(parts), _PRIVATE_REPO_DIGESTS)


def test_deploy_word_matcher_catches_every_case_and_passes_pinned_uses():
    """Planted positive with a synthetic word, its own allowed contexts
    and its own pinned line: every case and position is caught, and only the
    pinned contexts, the pinned line and identifiers containing it pass."""
    w = _synthetic_word("Qx")
    lw = w.lower()
    kwargs = dict(
        word_digest=_sha(lw),
        allowed_contexts=frozenset({_sha(f"alphabetagamma{lw}"), _sha(f"{lw}delta")}),
        pinned_lines=frozenset({_sha(f"pkg/scrub.py:pattern(r\"{lw}\\.private\\.\")")}),
    )
    caught = [f"# push ({w} deploy)", f"from the {w} private runtime",
              f"a/{w}/b", f"{w}-side exporter", f"({w} register entry::X)",
              f"the {lw} deploy", f"{w.upper()} DEPLOY", f"{w}'s compose mount",
              f"pattern(r\"{lw}\\.private\\.\")"]  # unpinned in another file
    for line in caught:
        assert _deploy_word_hits(line, "other.py", **kwargs), line
    passed = [f"Alpha beta gamma {w}", f"/* {w} delta effect */", f".{lw}-delta{{",
              f"a token called {w}Coin", f"0pn{w}x", f"{lw}_router."]
    for line in passed:
        assert not _deploy_word_hits(line, "other.py", **kwargs), line
    assert not _deploy_word_hits(f"pattern(r\"{lw}\\.private\\.\")", "pkg/scrub.py", **kwargs)
    # A second line in the pinned file is not pinned.
    assert _deploy_word_hits(f"pattern(r\"{lw}\\.deploy\\.\")", "pkg/scrub.py", **kwargs)
    # The real digest is a different digest: the synthetic word is not it.
    assert not _deploy_word_hits(f"the {w} deploy", "other.py")


def test_install_url_matcher_catches_a_planted_url():
    scheme = "git+ssh:" + "//"  # split so this file's own text holds no URL
    assert _INSTALL_URL.search(f"pip install {scheme}git@host.example/org/repo.git")
    assert not _INSTALL_URL.search("pip install https://host.example/org/repo.git")


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
    offenders = []
    for path in _tracked_text_files():
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(ROOT))
        for lineno, line in _deploy_word_hits(text, rel):
            offenders.append(f"{rel}:{lineno}: {line}")
        for lineno, line in enumerate(text.splitlines(), 1):
            if _INSTALL_URL.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()[:100]}")
    assert not offenders, (
        "tracked files name the private deployment repository or give an install "
        "URL (reword the line; a common-noun use of the word must be reworded "
        "too, since the scan cannot tell it from the name):\n" + "\n".join(offenders))


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
