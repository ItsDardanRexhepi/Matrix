"""The education pages and the README offer only what the repository has.

education/README.md offered Discord access, certification prep material and a
completion certificate, and education/COMMUNITY_GUIDE.md described a community
Discord with course channels "accessible after purchase", weekly office hours
in a Discord voice channel, a certification portal and certificates verified
by an EAS attestation. No chat invite of any kind is in the repository, and
the certification code writes no attestation. The README said its
certifications are backed by on-chain attestations.

Each test derives the fact from the repository and holds the words to it:
a chat server may be described only if an invite to one is here, and a
certificate may be called attested only if the certification code writes an
attestation for it.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_INVITE = re.compile(r"discord\.gg/|discord(?:app)?\.com/invite/|t\.me/|telegram\.me/|join\.slack\.com/",
                     re.IGNORECASE)
_CHAT_SERVER = re.compile(
    r"discord (?:server|channel|access|voice)|community discord|(?:^|[\s*])#[a-z][a-z0-9-]*\b.*channel",
    re.IGNORECASE)
_ATTESTED_CERTIFICATE = re.compile(
    r"certific\w*[^.\n]*(?:backed by|verified by|via|with an?) (?:on-chain )?(?:EAS )?attestation",
    re.IGNORECASE)


def _tracked(*patterns: str) -> list[str]:
    return subprocess.run(["git", "-C", str(REPO), "ls-files", *patterns],
                          capture_output=True, text=True, check=True).stdout.split()


def _pages() -> list[str]:
    return ["README.md", *(p for p in _tracked("education") if p.endswith(".md"))]


def test_no_chat_server_is_described_without_an_invite():
    invites = [rel for rel in _tracked() if not rel.startswith("tests/")
               and _INVITE.search(_read(rel))]
    if invites:
        return
    described = [f"{rel}:{n}" for rel in _pages()
                 for n, line in enumerate(_read(rel).splitlines(), 1)
                 if _CHAT_SERVER.search(line)]
    assert not described, (
        "no chat invite is anywhere in the repository, and these lines describe a "
        f"chat server as if there were one: {described}")


def test_a_certificate_is_called_attested_only_if_one_is_written():
    source = (REPO / "runtime/certification/assessments.py").read_text()
    statements = [node.value for node in ast.walk(ast.parse(source))
                  if isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and re.search(r"\b(INSERT|UPDATE)\b", node.value)]
    assert statements, "precondition: the certification code writes rows"
    writes_attestation = (any("eas_uid" in sql for sql in statements)
                          or re.search(r"\.attest\(", source) is not None)
    if writes_attestation:
        return
    claimed = [f"{rel}:{n}" for rel in _pages()
               for n, line in enumerate(_read(rel).splitlines(), 1)
               if _ATTESTED_CERTIFICATE.search(line)]
    assert not claimed, (
        "the certification code writes no attestation for a certificate, and these "
        f"lines say one is: {claimed}")


def _read(rel: str) -> str:
    try:
        return (REPO / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
