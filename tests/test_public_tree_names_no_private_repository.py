"""The public tree must not hand out the name or access shape of a private repo.

This repository is public and installable with one `curl | bash`. Its tracked
files named the closed-source security core by its private repository name, gave
the doc paths inside that repository, and spelled out the `git+ssh` install and
deploy-key shape a build needs to reach it. None of that is needed to USE the
seam, which binds by its Python import name, but all of it tells an attacker
which private repository, and which credential, the enforcement layer lives
behind.

A clone carries more than the tracked files. COMMIT MESSAGES ship with it, are
rendered by the hosting UI, and answer `git log | grep` the same way a tracked
file answers a grep of the checkout. Scanning only `git ls-files` therefore
measured half the artefact: the same wording this file's checks removed from
the tree went on being published by the messages of the commits that removed
it. The scans below run over `git log --format=%B` as well, and what history
already published is carried as an explicit, digest-keyed debt list rather than
quietly excluded — see `_ACKNOWLEDGED_MESSAGE_DIGESTS`.

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
    word does not. One kind of occurrence passes, pinned by digest, not by
    plain text: a token whose surrounding words form one of two decorative
    phrases the project's pages and installer use (the preceding three words,
    or the following word, hashed with it). Nothing else passes, and no line
    of any file is pinned: the export sanitizer and exporter, which must
    recognise the word to block it, hold it as a digest too
    (bridge/held_patterns.py), so they no longer print it beside the
    "private" labels that said what it names.
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
repository. What it does not see: a word glued inside a longer identifier
(for example the project's own public name) passes by design, so a pairing
written that way would not be caught.

The digests were checked against the tree before each fix: on a copy of
9f4aa37 the core-name test fails with nine hits in three files, and on a copy of
8f8b724 the deployment-word test fails with 31 hits in 12 files. With the
pinned sanitizer lines removed from this file and bridge/ not yet changed, it
failed with seven hits in two files (bridge/sanitizer.py six, bridge/exporter.py
one).
"""

from __future__ import annotations

import bisect
import hashlib
import os
import re
import secrets
import string
import subprocess
import tempfile
from pathlib import Path

import pytest

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

# sha256 of the FULL message body of every commit reachable from HEAD whose
# message publishes what the tracked files no longer say. These are history:
# rewriting them is a filter-branch or a squash, which is the owner's call
# for published history, not something a commit on this branch can do. Listing
# them keeps the gate meaningful for new commits while stating the debt out
# loud. THE PUBLIC PUSH STILL NEEDS A FILTERED OR SQUASHED HISTORY; until then
# a clone and the hosting UI carry these messages.
#
# The key is the digest of the message body, which is content-derived: a new
# commit cannot be written into this set, because any new wording hashes
# somewhere else. The one thing it does not catch is a new commit that
# reproduces one of these messages byte for byte — which republishes nothing
# that these commits do not already publish.
_ACKNOWLEDGED_MESSAGE_DIGESTS = frozenset({
    # 177f51f 2026-09-12  9 word tokens (11 counting the two decorative
    # phrases it quotes) — the message of the commit that removed the same
    # pairing from the files, so it prints the word beside "private runtime".
    "df05f9b3d7ad752d32ba12b35236a69011857db75fcfb820c741a0df91fc21b2",
    "2dee9cfa5ec0febb52e65aa415442014580cf6fb459eff1700b70c0db598efe9",  # 76e1969 2026-08-12
    "98901be141d4403d185eb2b40d274b4a939563b6af72b730e16f6e4e4a30c02e",  # d8af178 2026-07-02
    "48e5bff2b23c0eb3b2b0b5acdc359bb4c236da835b64da2bd1342a0bf4985b02",  # 53b83df 2026-07-01
    "3ac3d14b1cadd8175761cc316aa657910880c66af2cae1b784fbc4677015fb25",  # 7087216 2026-06-30 (+2 core-name hits)
    "96fc8ef5f2b32e4eb20f0c3419f609af35f7141f93d5e72d1cdb560a7a194b14",  # 0de9ac3 2026-06-19 (+1 core-name hit)
    "5bf8561d558bde8ecb57d0dd58ed5f3b4de9c398bce10957d0fb87113cbf1212",  # d0690b6 2026-04-10
    "8f3e0b283d906e7543df4ab371e1d8c3af78c25ff8852c14fe1af21d5a418fe8",  # c170e73 2026-04-09
    "4c11d5885771ebd1405e19e927cb4b88e314695d720f63ae1852c013e12cf074",  # 38b8138 2026-04-01
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
                      ) -> list[tuple[int, str]]:
    """(line, text) for each standalone token whose lower-cased digest is the
    deployment word, unless its context is one of the pinned phrases."""
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
        hits.append((lineno, line.strip()[:100]))
    return hits


def _synthetic_word(prefix: str = "Zq") -> str:
    return prefix + "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))


# --- commit messages, which a clone carries just as it carries the files -----

_MSG_SEP = "\x1f"   # between sha and body
_REC_SEP = "\x00"   # between records; git never emits a NUL inside a message
# Written as git's own escapes, not as the bytes: argv cannot carry a NUL.
_LOG_FORMAT = "--format=%H%x1f%B%x00"


def _commit_messages(repo: Path = ROOT, rev_range: str = "HEAD") -> list[tuple[str, str]]:
    """[(sha, message body)] for every commit reachable from `rev_range`."""
    out = subprocess.check_output(
        ["git", "log", _LOG_FORMAT, rev_range], cwd=repo, text=True)
    records = []
    for chunk in out.split(_REC_SEP):
        if not chunk.strip():
            continue
        sha, _, body = chunk.lstrip("\n").partition(_MSG_SEP)
        records.append((sha.strip(), body))
    return records


def _message_digest(body: str) -> str:
    """The key the acknowledged list uses: the message body with surrounding
    blank lines removed, so the digest does not move with a git version's
    trailing-newline handling."""
    return _sha(body.strip())


def _message_offenders(
    messages: list[tuple[str, str]],
    *,
    word_digest: str = _DEPLOY_WORD_DIGEST,
    allowed_contexts: frozenset[str] = _DEPLOY_WORD_ALLOWED_CONTEXTS,
    name_digests: frozenset[str] = _PRIVATE_REPO_DIGESTS,
    acknowledged: frozenset[str] = _ACKNOWLEDGED_MESSAGE_DIGESTS,
) -> list[str]:
    """Commit messages that name a private repository, the deployment word or an
    install URL, minus the ones whose whole body is on the acknowledged list.

    The same three matchers the tracked-file scans use, so a message cannot say
    what a file may not. Grouped per commit rather than per line: a message is
    published whole."""
    offenders = []
    for sha, body in messages:
        if _message_digest(body) in acknowledged:
            continue
        reasons = []
        word_hits = _deploy_word_hits(body, "<commit message>",
                                      word_digest=word_digest,
                                      allowed_contexts=allowed_contexts)
        if word_hits:
            reasons.append(f"names the private deployment repository "
                           f"({len(word_hits)}x, first at message line {word_hits[0][0]})")
        name_hits = _name_hits(body, name_digests)
        if name_hits:
            reasons.append(f"names a private repository ({len(name_hits)}x)")
        if _INSTALL_URL.search(body):
            reasons.append("gives a git+ssh install URL")
        if reasons:
            subject = body.splitlines()[0][:60] if body.splitlines() else ""
            offenders.append(f"{sha[:12]} ({subject}): " + "; ".join(reasons))
    return offenders


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
    """Planted positive with a synthetic word and its own allowed contexts:
    every case and position is caught, and only the pinned contexts and
    identifiers containing the word pass. The planted lines are generic token
    positions, not the shapes of phrases that were removed from the tree."""
    w = _synthetic_word("Qx")
    lw = w.lower()
    kwargs = dict(
        word_digest=_sha(lw),
        allowed_contexts=frozenset({_sha(f"alphabetagamma{lw}"), _sha(f"{lw}delta")}),
    )
    caught = [f"alpha {w} omega", f"({w})", f"a/{w}/b", f"{w}-", f"{lw}.",
              f"{w.upper()}", f"x={w};", f"<{lw}>", f"'{w}'",
              f"pattern(r\"{lw}\\.kappa\\.\")"]
    for line in caught:
        assert _deploy_word_hits(line, "other.py", **kwargs), line
    passed = [f"Alpha beta gamma {w}", f"/* {w} delta effect */", f".{lw}-delta{{",
              f"a token called {w}Coin", f"pre{w}post", f"{lw}_zeta."]
    for line in passed:
        assert not _deploy_word_hits(line, "other.py", **kwargs), line
    # No file or line is exempt: the same line is caught under any path.
    assert _deploy_word_hits(f"pattern(r\"{lw}\\.kappa\\.\")", "bridge/sanitizer.py", **kwargs)
    # The real digest is a different digest: the synthetic word is not it.
    assert not _deploy_word_hits(f"alpha {w} omega", "other.py")


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


def test_message_scan_catches_a_planted_commit_in_a_real_repository():
    """Planted positive in an actual git repository, with a synthetic word and
    synthetic name: the message reader really reads git's output, the matchers
    really run over it, and the acknowledgement really exempts one body and not
    a neighbouring one. No real name is written anywhere in this test."""
    word = _synthetic_word("Qx")
    name = "-".join([_synthetic_word(), "Planted", "Vault"])
    kwargs = dict(
        word_digest=_sha(word.lower()),
        allowed_contexts=frozenset({_sha(f"alphabetagamma{word.lower()}")}),
        name_digests=frozenset({_digest(name.replace("-", ""))}),
        acknowledged=frozenset(),
    )
    clean = "Reword the operator docs\n\nNo private repository is named here.\n"
    dirty_word = f"Wire the export seam\n\nreads from the {word} private runtime\n"
    dirty_name = f"Bind the seam\n\ninstalls {name} as a build dependency\n"
    pinned = f"Landing copy\n\nAlpha beta gamma {word} stays as decoration\n"

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        run = lambda *args: subprocess.run(  # noqa: E731
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
             "-c", "commit.gpgsign=false", *args],
            cwd=repo, env=env, check=True, capture_output=True)
        run("init", "-q", "-b", "main")
        for message in (clean, dirty_word, dirty_name, pinned):
            run("commit", "--allow-empty", "-q", "-m", message)

        messages = _commit_messages(repo)
        assert len(messages) == 4, messages
        offenders = _message_offenders(messages, **kwargs)
        flagged = {line.split(" ", 1)[0] for line in offenders}
        by_body = {body: sha[:12] for sha, body in messages}

        # Caught: the word beside "private runtime", and the name.
        assert by_body[dirty_word] in flagged, offenders
        assert by_body[dirty_name] in flagged, offenders
        # Passed: a clean message, and the word in its pinned decorative context.
        assert by_body[clean] not in flagged, offenders
        assert by_body[pinned] not in flagged, offenders
        blamed = " ".join(offenders)
        assert "private deployment repository" in blamed
        assert "names a private repository" in blamed

        # Acknowledging one body exempts exactly that body.
        acked = dict(kwargs, acknowledged=frozenset({_message_digest(dirty_word)}))
        assert len(_message_offenders(messages, **acked)) == 1

        # And the real digests do not fire on the synthetic words.
        assert not _message_offenders(messages, acknowledged=frozenset())


def test_no_commit_message_names_a_private_repository_or_an_install_url():
    """A clone carries the messages. Anything the tracked-file scans refuse, a
    commit message refuses too — except the bodies already in history, which are
    listed by digest above and still need a filtered or squashed push."""
    try:
        subprocess.check_output(["git", "rev-parse", "--git-dir"], cwd=ROOT,
                                stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, OSError):  # pragma: no cover
        pytest.skip("no git history here: nothing to publish through messages")
    offenders = _message_offenders(_commit_messages())
    assert not offenders, (
        "commit messages publish what the tracked files no longer say; a clone "
        "and the hosting UI carry them and `git log | grep` finds them. Reword "
        "the message before committing (a message cannot be edited afterwards "
        "on this branch):\n" + "\n".join(offenders))


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
