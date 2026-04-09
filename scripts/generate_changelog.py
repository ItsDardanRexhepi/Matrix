#!/usr/bin/env python3
"""Generate a changelog section from git history.

Usage::

    python scripts/generate_changelog.py [--since TAG_OR_REF] [--version X.Y.Z]

The script reads ``git log`` between ``--since`` (default: the most
recent ``v*`` tag, or the entire history if there are no tags) and
``HEAD``, groups commits by Conventional-Commit-style prefix
(``feat:``, ``fix:``, ``docs:``, ``chore:``, ``refactor:``, ``test:``,
``ci:``, ``build:``, ``perf:``), and prints a Markdown section that can
be pasted into ``CHANGELOG.md``.

If ``--write`` is passed, the new section is prepended to
``CHANGELOG.md`` directly (under the top-level heading).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import OrderedDict
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"

# Conventional-commit prefix → user-facing section heading.
SECTIONS: "OrderedDict[str, str]" = OrderedDict(
    [
        ("feat", "Added"),
        ("fix", "Fixed"),
        ("perf", "Performance"),
        ("refactor", "Changed"),
        ("docs", "Documentation"),
        ("test", "Tests"),
        ("build", "Build"),
        ("ci", "CI"),
        ("chore", "Chore"),
    ]
)

# Matches `type: subject` or `type(scope): subject`. Type is captured
# in group 1, the rest of the subject in group 2.
COMMIT_RE = re.compile(r"^(?P<type>[a-z]+)(?:\([^)]+\))?!?:\s*(?P<subject>.+)$")


def run(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def latest_tag() -> str | None:
    out = run("tag", "--list", "v*", "--sort=-creatordate")
    tags = [line.strip() for line in out.splitlines() if line.strip()]
    return tags[0] if tags else None


def collect_commits(since: str | None) -> list[tuple[str, str]]:
    """Return a list of (subject, sha) for commits in the range."""
    rev_range = f"{since}..HEAD" if since else "HEAD"
    out = run("log", rev_range, "--pretty=format:%H%x09%s", "--no-merges")
    commits: list[tuple[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition("\t")
        commits.append((subject.strip(), sha[:7]))
    return commits


def group_commits(
    commits: list[tuple[str, str]],
) -> "OrderedDict[str, list[tuple[str, str]]]":
    grouped: "OrderedDict[str, list[tuple[str, str]]]" = OrderedDict(
        (heading, []) for heading in SECTIONS.values()
    )
    grouped["Other"] = []
    for subject, sha in commits:
        match = COMMIT_RE.match(subject)
        if match:
            ctype = match.group("type").lower()
            heading = SECTIONS.get(ctype, "Other")
            grouped[heading].append((match.group("subject"), sha))
        else:
            grouped["Other"].append((subject, sha))
    # Drop empty buckets so the output stays tidy.
    return OrderedDict((k, v) for k, v in grouped.items() if v)


def render_section(version: str, grouped: "OrderedDict[str, list[tuple[str, str]]]") -> str:
    today = date.today().isoformat()
    lines = [f"## [{version}] — {today}", ""]
    for heading, entries in grouped.items():
        lines.append(f"### {heading}")
        for subject, sha in entries:
            lines.append(f"- {subject} ({sha})")
        lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def prepend_to_changelog(section: str) -> None:
    if not CHANGELOG_PATH.exists():
        CHANGELOG_PATH.write_text("# Changelog\n\n" + section)
        return
    existing = CHANGELOG_PATH.read_text()
    # Insert after the top-level "# Changelog" heading and any blurb.
    marker = "---\n"
    idx = existing.find(marker)
    if idx == -1:
        new = "# Changelog\n\n" + section + existing
    else:
        # Place new section right before the first existing release block.
        head = existing[: idx + len(marker)]
        tail = existing[idx + len(marker):]
        new = f"{head}\n{section}{tail}"
    CHANGELOG_PATH.write_text(new)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        help="Git ref to compute changes from. Defaults to the latest v* tag.",
    )
    parser.add_argument(
        "--version",
        default="UNRELEASED",
        help="Version label for the new section header (default: UNRELEASED).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Prepend the generated section to CHANGELOG.md instead of stdout.",
    )
    args = parser.parse_args()

    since = args.since or latest_tag()
    commits = collect_commits(since)
    if not commits:
        print(f"No commits found since {since or 'beginning of history'}.", file=sys.stderr)
        return 0

    grouped = group_commits(commits)
    section = render_section(args.version, grouped)

    if args.write:
        prepend_to_changelog(section)
        print(f"Prepended {len(commits)} commits to {CHANGELOG_PATH}", file=sys.stderr)
    else:
        print(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
