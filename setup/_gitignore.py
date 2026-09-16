"""Keep the files the setup wizards write keys into out of git commits.

One implementation for every writer of those files: setup.py's wizard, and the
channel wizards run on their own (setup_communications.py, setup_telegram.py,
``python -m setup.<channel>``), which reach disk through setup/_shared.py.
Output goes through the caller's warn/info/success, so each entry point keeps
its own look.
"""

from __future__ import annotations

import os
import stat as _stat
import subprocess
import unicodedata
from pathlib import Path

# Files the wizards write credentials into. BOTH branches of setup_gitignore()
# protect every one of them — they used to disagree, and the amend branch (the
# common one) never covered .env.
SECRET_FILES = ("matrix.config.json", ".env")

# Git skips a pattern file of this size or larger with "ignoring excessively
# large pattern file" and applies none of its lines (dir.c; checked against git
# 2.50.1: 104857599 bytes is read, 104857600 is not).
GITIGNORE_MAX_SIZE = 100 * 1024 * 1024

GIT_TIMEOUT = 30


def _trim_trailing_spaces(line):
    """git's trim_trailing_spaces(): drop a run of trailing spaces, unless the
    run starts right after a backslash, which escapes the character after it."""
    last_space = None
    i = 0
    while i < len(line):
        if line[i] == " ":
            if last_space is None:
                last_space = i
        else:
            if line[i] == "\\":
                i += 1
                if i == len(line):
                    return line
            last_space = None
        i += 1
    return line if last_space is None else line[:last_space]


def _gitignore_pattern(raw):
    """The pattern git reads from one .gitignore line, or None for no pattern.

    Follows git's add_patterns_from_buffer() step for step. A line starting
    with `#` is a comment (checked before anything is dropped). One CR is
    dropped only when it is the line's last byte, i.e. right before the LF.
    The pattern is then a C string: it ends at the first NUL, so `!.env<NUL>x`
    is `!.env`. Last, trailing spaces that are not backslash-escaped go. Leading
    whitespace and tabs anywhere stay — `  .env` and `.env<TAB>` are patterns
    for other names.
    """
    if not raw or raw.startswith("#"):
        return None
    line = raw[:-1] if raw.endswith("\r") else raw
    line = _trim_trailing_spaces(line.split("\x00", 1)[0])
    return line or None


def _negation_may_match(pattern, entry):
    """Could `!pattern` re-include the root-level file *entry*? Unsure means yes.

    Only a literal (no `*`, `?`, `[` or backslash) can be ruled out: it matches
    a root file only when, less a leading and trailing `/`, it is that name —
    compared CASELESSLY. Git matches patterns without regard to case when
    core.ignorecase is true, which `git init` sets on macOS and Windows, so
    `!.ENV` re-includes .env there. Folding regardless of the repository's
    setting costs, where it is false, one redundant line; never a false
    "covered". (casefold() folds at least everything git's ASCII folding does.)
    """
    if any(ch in pattern for ch in "*?[\\"):
        return True
    name = pattern.strip("/")
    return not name or name.casefold() == entry.casefold()


def _gitignore_covers(lines, entry):
    """True if these .gitignore lines, read as git reads them, ignore *entry* at the root.

    Git's last matching line wins. So *entry* is covered when an exact
    `entry` / `/entry` pattern is followed by no negation that could match it.
    Everything this cannot decide — a wildcard that would cover the file, a
    negation that might re-include it — counts as NOT covered, which costs one
    redundant line at the end of the file, where it is the last match and wins.

    What is shown, not assumed: for every starting file in the tests'
    parametrised list and 400 generated from their line pool, git ignores both
    files afterwards under core.ignorecase true and false. A line form outside
    those is decided only by the rules above. This says nothing about whether
    git reads the file at all (a symlink, 100 MiB or more, unreadable) or about
    a file git already tracks; setup_gitignore() handles those and then asks git.
    """
    covered = False
    for raw in lines:
        pattern = _gitignore_pattern(raw)
        if pattern is None:
            continue
        if pattern.startswith("!"):
            if _negation_may_match(pattern[1:], entry):
                covered = False
        elif pattern in (entry, "/" + entry):
            covered = True
    return covered


_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _read_gitignore(path):
    """(bytes, None) for a .gitignore git reads; (None, None) when there is none;
    (None, reason) when one is there but git applies none of its lines.

    Git opens an in-tree .gitignore without following a symlink (since 2.32),
    skips one of GITIGNORE_MAX_SIZE or more, and gets nothing from a directory
    or a file it cannot open. Reading such a file here — through the link, or at
    all — would count lines git never reads as protection.
    """
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None, None
    if _stat.S_ISLNK(st.st_mode):
        return None, "it is a symbolic link, and git (2.32 and later) does not follow one"
    if not _stat.S_ISREG(st.st_mode):
        return None, "it is not a regular file"
    try:
        fd = os.open(path, os.O_RDONLY | _NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
    except OSError as exc:
        return None, f"it cannot be opened ({exc.strerror or exc})"
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())          # what was opened, not what lstat saw
        if not _stat.S_ISREG(st.st_mode):
            return None, "it is not a regular file"
        if st.st_size >= GITIGNORE_MAX_SIZE:
            return None, "it is 100 MiB or larger, and git skips a pattern file that big"
        return f.read(), None


def _fold(name):
    """A name as a case-insensitive filesystem compares it (APFS and NTFS fold
    case; APFS also compares canonically equivalent spellings as one name)."""
    return unicodedata.normalize("NFD", name).casefold()


def git_verdict(names, *, info):
    """Ask git which of *names* it would commit, here, as configured.

    Returns {name: tracked_spellings} for each name git would commit: a list of
    the index entries in this directory that ARE that file (empty when it is
    simply not ignored), or None when there is no verdict to be had — no git,
    not inside a work tree, or git failed; every case but "not a work tree" is
    said through *info*.

    Ignore rules come from `check-ignore --no-index`. Tracking does NOT come
    from `check-ignore` with the index: that looks a name up case-sensitively,
    so with `.ENV` tracked it calls `.env` ignored, while on a case-insensitive
    filesystem (the macOS and Windows default) the wizard's write to .env lands
    in the tracked .ENV and `git commit -a` commits it. The index entries in
    this directory are listed instead and compared caselessly, whatever
    core.ignorecase says; on a case-sensitive filesystem that can cost a false
    alarm about a differently-cased file, never a silent commit. Git runs
    without the operator's GIT_*_PATHSPECS switches: check-ignore, the first
    call here, refuses to run under any of them. Git's output is bytes and is
    decoded without raising: it echoes paths, and a path need not be UTF-8.
    """
    asked = ", ".join(names)

    # The pathspecs below are this function's own, so none of the operator's
    # pathspec switches may apply to them. Under any one of GIT_LITERAL_PATHSPECS,
    # GIT_GLOB_PATHSPECS, GIT_NOGLOB_PATHSPECS or GIT_ICASE_PATHSPECS, check-ignore
    # — the first call below — dies with "pathspec magic not supported by this
    # command: 'literal'" ('glob', 'literal', 'icase'), and the whole verdict — a
    # tracked secret, or one no rule ignores — became a single "Could not ask
    # git" line. The four switches never differed: ls-files, whose `:(glob)*`
    # GIT_LITERAL_PATHSPECS alone would turn into a literal name matching
    # nothing, is never reached. (git 2.50.1.)
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("GIT_") and k.endswith("_PATHSPECS"))}

    def run(argv, stdin=None):
        return subprocess.run(["git", *argv], input=stdin, capture_output=True,
                              timeout=GIT_TIMEOUT, env=env)

    def failed(result):
        err = result.stderr.decode("utf-8", "replace").strip()
        if "not a git repository" not in err:
            info(f"Could not ask git whether {asked} are kept out of commits: "
                 f"{err.splitlines()[0] if err else 'exit ' + str(result.returncode)}")

    try:
        rules = run(["check-ignore", "--no-index", "--stdin", "-z"],
                    stdin=b"".join(os.fsencode(n) + b"\0" for n in names))
        if rules.returncode not in (0, 1):
            failed(rules)
            return None
        listed = run(["ls-files", "-z", "--", ":(glob)*"])   # this directory's entries only
        if listed.returncode != 0:
            failed(listed)
            return None
    except subprocess.TimeoutExpired:
        info(f"Could not ask git whether {asked} are kept out of commits: git did not "
             f"answer within {GIT_TIMEOUT} seconds.")
        return None
    except OSError as exc:
        why = "git is not installed or not on PATH" if isinstance(exc, FileNotFoundError) \
            else (exc.strerror or str(exc))
        info(f"Could not ask git whether {asked} are kept out of commits: {why}.")
        return None

    ignored = {os.fsdecode(p) for p in rules.stdout.split(b"\0") if p}
    entries = [os.fsdecode(p) for p in listed.stdout.split(b"\0") if p and b"/" not in p]
    verdict = {}
    for name in names:
        tracked = sorted(e for e in entries if _fold(e) == _fold(name))
        if tracked or name not in ignored:
            verdict[name] = tracked
    return verdict


def setup_gitignore(*, warn, info, success, verdict=None):
    """Keep the files holding real keys out of commits, and say so when it cannot.

    Writes or amends .gitignore when git reads it; never writes to one git does
    not read (the write would land where git does not look). Then, where git
    and a work tree are there, takes git's own verdict and warns by name about
    every secret file it would still commit.
    """
    if verdict is None:
        def verdict(names):
            return git_verdict(names, info=info)

    gitignore = Path(".gitignore")
    content, unread = _read_gitignore(gitignore)
    if unread:
        warn(f"git does not read .gitignore: {unread}. Nothing in it keeps "
             f"{' or '.join(SECRET_FILES)} out of a commit, and nothing was written to it.")
        info("Make .gitignore a regular file that lists both, or list them in .git/info/exclude.")
    elif content is None:
        try:
            fd = os.open(gitignore, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o644)
        except FileExistsError:           # appeared since the lstat: read it next run
            warn(".gitignore appeared while setup was writing it; re-run setup to check it.")
        except OSError as exc:            # read-only directory, and the like
            warn(f"Could not create .gitignore to list {', '.join(SECRET_FILES)}: "
                 f"{exc.strerror or exc}.")
        else:
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write("\n".join(SECRET_FILES) + "\n__pycache__/\n*.pyc\n")
            except OSError as exc:        # the disk filled between the open and the write
                try:
                    os.unlink(gitignore)  # ours (O_EXCL): leave no empty or half-written file
                except OSError:
                    pass
                warn(f"Could not write .gitignore to list {', '.join(SECRET_FILES)}: "
                     f"{exc.strerror or exc}. Nothing keeps them out of a commit.")
            else:
                success(".gitignore created")
    else:
        # Split on LF only: git ends a line only at LF, and a lone CR inside a
        # line is part of its pattern. read_text()'s universal newlines (or
        # splitlines()) would turn "!.env\r.env" — one literal negation to git —
        # into a `.env` line that looks like coverage. Git skips a UTF-8 BOM at
        # the start of the file. Undecodable bytes become U+FFFD, which matches
        # no entry: a redundant line, not a false "covered".
        text = content[3:] if content.startswith(b"\xef\xbb\xbf") else content
        lines = text.decode("utf-8", "replace").split("\n")
        missing = [e for e in SECRET_FILES if not _gitignore_covers(lines, e)]
        addition = (("\n" if content and not content.endswith(b"\n") else "")
                    + "\n# Real config and credentials — never commit\n"
                    + "".join(e + "\n" for e in missing)).encode("utf-8")
        if missing and len(content) + len(addition) >= GITIGNORE_MAX_SIZE:
            warn(f"Adding {', '.join(missing)} would make .gitignore 100 MiB or larger, and git "
                 f"skips a pattern file that big; nothing was written to it.")
        elif missing:
            try:
                fd = os.open(gitignore, os.O_WRONLY | os.O_APPEND | _NOFOLLOW)
                with os.fdopen(fd, "ab") as f:
                    f.write(addition)
            except OSError as exc:        # read-only, or swapped for a link since the read
                warn(f"Could not add {', '.join(missing)} to .gitignore: {exc.strerror or exc}.")
            else:
                success(f".gitignore updated ({', '.join(missing)})")

    for name, tracked in (verdict(SECRET_FILES) or {}).items():
        for spelling in tracked:
            same = "" if spelling == name else (
                f", which is {name} wherever the filesystem ignores case (the macOS and "
                f"Windows default)")
            warn(f"git already tracks {spelling}{same}, so no ignore rule applies to it and "
                 f"`git commit -a` commits the keys written to {name}. Untrack it: "
                 f"git rm --cached {spelling} (a copy already committed stays in history).")
        if not tracked:
            warn(f"git would commit {name}: no ignore rule it reads keeps it out.")
