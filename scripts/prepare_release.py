#!/usr/bin/env python3
"""
0pnMatrx Release Preparation — standalone wrapper around the OpenMatrix
release CLI that defaults the workspace to *this* repository.

The canonical release scanner lives in the OpenMatrix iOS repo under
``matrix/cli/prepare_release.py``; this script vendors just enough of it
to be self-contained here, so operators don't need the iOS checkout on
the same machine.

Usage::

    python3 scripts/prepare_release.py scan
    python3 scripts/prepare_release.py export
    python3 scripts/prepare_release.py full

All commands implicitly target the 0pnMatrx workspace (the parent
directory of this file). Pass ``--workspace /path/to/repo`` to target a
different checkout — the same semantics as the OpenMatrix version.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── ANSI colors ────────────────────────────────────────────────────────

GREEN = "\033[32m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"

# The workspace is this repo's root (scripts/ is directly under it).
WORKSPACE = Path(__file__).resolve().parents[1]

# ── Sensitive data patterns ────────────────────────────────────────────
#
# Kept in sync with the OpenMatrix CLI. When new patterns are added on
# one side they should be mirrored on the other; see the CONTRIBUTING
# note in that file.

SENSITIVE_PATTERNS = [
    (re.compile(r"0x[0-9a-fA-F]{64}"), "private key (64-char hex)"),
    (re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"), "PEM private key"),
    (re.compile(r"nvapi-[A-Za-z0-9]{48,}"), "NVIDIA API key"),
    (re.compile(r"sk-[A-Za-z0-9]{32,}"), "OpenAI API key"),
    (re.compile(r"sk-ant-[A-Za-z0-9-]{80,}"), "Anthropic API key"),
    (re.compile(r"xoxb-[0-9]{10,}-[A-Za-z0-9-]+"), "Slack bot token"),
    (re.compile(r"\d{9,10}:[A-Za-z0-9_-]{35}"), "Telegram bot token"),
    (re.compile(r"(?<!\d)\d{10}(?!\d)"), "Possible Telegram user ID"),
    (re.compile(r"0x46fF491D7054A6F500026B3E81f358190f8d8Ec5"), "NeoSafe address"),
    (re.compile(r"0x45C07600825E79e36629537BFcAC64cfB285B5ae"), "NeoWrite address"),
    (re.compile(r"password\s*[=:]\s*[\"'][^\"']+[\"']", re.IGNORECASE), "hardcoded password"),
    (re.compile(r"secret\s*[=:]\s*[\"'][^\"']+[\"']", re.IGNORECASE), "hardcoded secret"),
]

PRIVATE_FILES = {
    ".env",
    "neowrite.env",
    "secrets/",
    "identity/",
    "governance/",
    "data/",
    "runtime/cache/",
    "runtime/streams/",
    "runtime/usage/",
    "runtime/memory_sync/",
    "hivemind/",
    "gateway/gateway.pid",
    "gateway/gateway.log",
    "gateway/gateway.err.log",
    "gateway/status.json",
    "openmatrix.config.json",
}

SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dylib", ".dll",
    ".log", ".jsonl", ".db", ".sqlite", ".sqlite3",
    ".pid", ".lock", ".tick",
}

SKIP_DIRS = {
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".tox", "export",
}


def _should_skip(path: Path) -> bool:
    if path.suffix in SKIP_EXTENSIONS:
        return True
    for skip in SKIP_DIRS:
        if skip in path.parts:
            return True
    return False


def _is_private(path: Path, workspace: Path) -> bool:
    rel = str(path.relative_to(workspace))
    for private in PRIVATE_FILES:
        if private.endswith("/"):
            if rel.startswith(private) or f"/{private}" in f"/{rel}":
                return True
        elif rel == private or rel.endswith(f"/{private}"):
            return True
    return False


def cmd_scan(workspace: Path) -> list[dict]:
    findings: list[dict] = []
    print(f"\n  {BOLD}Scanning for sensitive data in {workspace.name}…{RESET}\n")

    targets = (
        list(workspace.rglob("*.py"))
        + list(workspace.rglob("*.json"))
        + list(workspace.rglob("*.env"))
        + list(workspace.rglob("*.md"))
    )
    scanned = 0
    for fpath in targets:
        if _should_skip(fpath):
            continue
        try:
            content = fpath.read_text(errors="ignore")
        except Exception:
            continue
        scanned += 1
        rel = str(fpath.relative_to(workspace))

        for pattern, desc in SENSITIVE_PATTERNS:
            for match in pattern.findall(content)[:3]:
                token = match if isinstance(match, str) else str(match)
                redacted = token[:6] + "…" + token[-4:] if len(token) > 10 else token
                findings.append({"file": rel, "type": desc, "match": redacted})
                print(f"  {RED}[FOUND]{RESET} {rel}")
                print(f"         {desc}: {DIM}{redacted}{RESET}")

    if findings:
        print(f"\n  {YELLOW}{len(findings)} sensitive items found in {scanned} files.{RESET}")
    else:
        print(f"  {GREEN}No sensitive data found in {scanned} files.{RESET}")
    print()
    return findings


def cmd_export(workspace: Path) -> Path:
    export_dir = workspace / "export" / f"{workspace.name}-{datetime.now().strftime('%Y%m%d')}"
    print(f"\n  {BOLD}Creating clean export at {export_dir}…{RESET}\n")

    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True)

    copied = skipped = private = 0
    for fpath in sorted(workspace.rglob("*")):
        if not fpath.is_file():
            continue
        if _should_skip(fpath):
            skipped += 1
            continue
        if "export/" in str(fpath):
            continue
        if _is_private(fpath, workspace):
            private += 1
            continue

        if fpath.suffix in (".py", ".json", ".md", ".txt", ".sh", ".yaml", ".yml"):
            try:
                content = fpath.read_text(errors="ignore")
                if any(p.search(content) for p, _ in SENSITIVE_PATTERNS):
                    private += 1
                    continue
            except Exception:
                pass

        dest = export_dir / fpath.relative_to(workspace)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fpath, dest)
        copied += 1

    print(f"  {GREEN}Exported:{RESET} {copied}")
    print(f"  {YELLOW}Private (excluded):{RESET} {private}")
    print(f"  {DIM}Skipped (binary/cache):{RESET} {skipped}")
    print()
    return export_dir


def cmd_manifest(workspace: Path) -> None:
    print(f"\n  {BOLD}Generating manifest…{RESET}\n")
    public: list[str] = []
    private_list: list[str] = []

    for fpath in sorted(workspace.rglob("*")):
        if not fpath.is_file() or _should_skip(fpath):
            continue
        if "export/" in str(fpath):
            continue
        rel = str(fpath.relative_to(workspace))

        if _is_private(fpath, workspace):
            private_list.append(rel)
            continue

        sensitive = False
        if fpath.suffix in (".py", ".json", ".md", ".txt", ".sh"):
            try:
                content = fpath.read_text(errors="ignore")
                sensitive = any(p.search(content) for p, _ in SENSITIVE_PATTERNS)
            except Exception:
                pass
        (private_list if sensitive else public).append(rel)

    manifest_path = workspace / "RELEASE_MANIFEST.md"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        f"# {workspace.name} Release Manifest",
        "",
        f"**Generated:** {now}",
        f"**Public files:** {len(public)}",
        f"**Private files (excluded):** {len(private_list)}",
        "",
        "---",
        "",
        "## Public Files",
        "",
        *(f"- `{f}`" for f in public),
        "",
        "---",
        "",
        "## Private Files (Never Released)",
        "",
        *(f"- `{f}`" for f in private_list),
    ]
    manifest_path.write_text("\n".join(lines) + "\n")
    print(f"  {GREEN}Manifest saved:{RESET} {manifest_path.name}")
    print(f"  Public: {len(public)}  Private: {len(private_list)}")
    print()


def _resolve_workspace(raw: str | None) -> Path:
    if raw is None:
        return WORKSPACE
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise SystemExit(f"error: workspace not found: {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="prepare_release",
        description="0pnMatrx release preparation (scan / export / manifest).",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="scan",
        choices=("scan", "export", "manifest", "full"),
    )
    parser.add_argument("--workspace", "-w", default=None)
    ns = parser.parse_args()

    workspace = _resolve_workspace(ns.workspace)
    print(f"  {DIM}Workspace: {workspace}{RESET}")

    if ns.command == "scan":
        cmd_scan(workspace)
    elif ns.command == "export":
        cmd_scan(workspace)
        cmd_export(workspace)
    elif ns.command == "manifest":
        cmd_manifest(workspace)
    elif ns.command == "full":
        cmd_scan(workspace)
        cmd_export(workspace)
        cmd_manifest(workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
