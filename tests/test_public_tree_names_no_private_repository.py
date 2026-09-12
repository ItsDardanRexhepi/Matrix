"""The public tree must not hand out the name or access shape of a private repo.

This repository is public and installable with one `curl | bash`. Its tracked
files named the closed-source security core by its private repository name, gave
the doc paths inside that repository, and spelled out the `git+ssh` install and
deploy-key shape a build needs to reach it. None of that is needed to USE the
seam — the seam binds by Python import name (`morpheus_security`), which stays —
but all of it tells an attacker exactly which private repository, and which
credential, the whole enforcement layer lives behind.

The properties checked here are about what the tree publishes, so the check is
necessarily on tracked text. Two things keep it from being a string list that
re-leaks the thing it guards:

  * the forbidden repository identifiers are held as SHA-256 digests of their
    lower-cased spelling, and every token of every tracked file is hashed and
    compared — so this file does not publish the names it is keeping out, and a
    new file anywhere in the tree (not just the ones that leaked last time) is
    covered;
  * path-shaped references into a private checkout (`<PrivateRepo>/<file>`) and
    `git+ssh://` install URLs are matched structurally, and a backticked `*.md`
    reference in the operator docs must resolve to a file that is actually in
    this tree — a doc path that only exists in a private repository is exactly
    the leak, and it is also a dead link for every public reader.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# sha256 of the lower-cased private repository names (current and former).
_PRIVATE_REPO_DIGESTS = {
    "c18bcda4d3a921badc80ed85abfaac746bcfaa01a326e11bd9ea940a95e936fc",
    "06df33f6ff60cde5181fa5d8d5621442afa0f44ecd74e3562bdccffe6d21dc2d",
}

# Top-level directories of private checkouts that operator docs used to address
# as sibling paths (`<name>/deploy/...`). A path into one of them is only
# meaningful to someone holding that checkout.
_PRIVATE_CHECKOUT_PATH = re.compile(r"(?<![\w/.-])Matrix/[A-Za-z0-9_.-]+")

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*[A-Za-z0-9]")

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


def _digest(token: str) -> str:
    return hashlib.sha256(token.lower().encode()).hexdigest()


def test_digest_matcher_catches_a_planted_name():
    """Planted positive: the matcher is not vacuous. The digest set must match a
    token built at runtime from pieces, so no whole name appears in this file."""
    planted = "-".join(["Morpheus", "Security", "System"])
    assert _digest(planted) in _PRIVATE_REPO_DIGESTS
    assert any(_digest(t) in _PRIVATE_REPO_DIGESTS
               for t in _TOKEN.findall(f"pip install git+ssh://host/{planted}"))


def test_no_tracked_file_names_a_private_repository():
    offenders = []
    for path in _tracked_text_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(_digest(t) in _PRIVATE_REPO_DIGESTS for t in _TOKEN.findall(line)):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert not offenders, (
        "tracked files name a private repository (the security core's access "
        "target): " + ", ".join(offenders))


def test_no_tracked_file_addresses_a_private_checkout_or_install_url():
    offenders = []
    for path in _tracked_text_files():
        rel = path.relative_to(ROOT)
        if rel == Path(__file__).relative_to(ROOT):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _PRIVATE_CHECKOUT_PATH.search(line) or "git+ssh://" in line:
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
