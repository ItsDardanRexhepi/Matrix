"""What the documents say is attested is what the code writes.

Three statements had no writer behind them:

* "Every action creates a verifiable on-chain attestation record", in the
  README's example table, examples/README.md, example 06 and 07, and the EAS
  client's module docstring. The service dispatcher QUEUES an attestation for
  a state-modifying action it completes; the queue is written to the chain
  once 50 have gathered in the same process, nothing drains it on a timer,
  and what is queued is lost if the process exits first.
* Glasswing badges "backed by on-chain EAS attestation" and "Recorded as an
  EAS attestation on-chain". The badge code writes no attestation.
* The course said every deployed contract's attestation certifies the audit.
  The attestation encodes the platform, the action, the agent and a
  timestamp, not the contract or the audit.

The tests derive each fact from the code, by running it or reading its
writes, and hold the documents to it.
"""
from __future__ import annotations

import ast
import asyncio
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_EVERY_ACTION_ATTESTED = re.compile(
    r"every ([a-z-]+ )?(action|payment|deployment|transaction|capability|operation)"
    r"[^.\n]{0,40}(is|are|gets|get|creates|receives) [^.\n]{0,30}attest"
    r"|every [a-z ]{0,30}attested (on-chain|via EAS)|attestation on every action"
    r"|automatic attestation",
    re.IGNORECASE)
_BADGE_ATTESTED = re.compile(
    r"badge[^.\n]*(backed by|recorded as|is an?|via) (an? )?(on-chain )?(EAS )?attestation",
    re.IGNORECASE)
_ATTESTATION_CERTIFIES_AUDIT = re.compile(
    r"on-chain record that certifies|attestation (that |which )?certifies|proof of audit"
    r"|professionally audited|linking the contract to its audit", re.IGNORECASE)


def _documents() -> list[str]:
    files = subprocess.run(["git", "-C", str(REPO), "ls-files", "*.md", "*.py"],
                           capture_output=True, text=True, check=True).stdout.split()
    return [f for f in files if not f.startswith(("tests/", "web/")) and f != "CHANGELOG.md"]


def _lines(pattern: re.Pattern) -> list[str]:
    hits = []
    for rel in _documents():
        try:
            text = (REPO / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits += [f"{rel}:{n}" for n, line in enumerate(text.splitlines(), 1)
                 if pattern.search(line)]
    return hits


def test_a_completed_action_is_queued_and_no_document_says_it_is_written():
    from runtime.blockchain.services.attestation.service import AttestationService

    service = AttestationService({"blockchain": {"eas_schema": "0x" + "cd" * 32}})
    answer = asyncio.run(service.attest(schema_uid="", data={"action": "transfer"},
                                        recipient="0x" + "11" * 20))
    queued = answer.get("status") == "queued" and service._batch_processor.pending_count == 1
    if not queued:
        pytest.skip(f"the attestation service no longer queues: {answer.get('status')}")
    claimed = _lines(_EVERY_ACTION_ATTESTED)
    assert not claimed, (
        "an attestation for a completed action is queued, not written, and these "
        f"lines say every action is attested: {claimed}")


def test_a_badge_is_called_attested_only_if_one_is_written():
    source = (REPO / "runtime/badges/badge_manager.py").read_text()
    statements = [node.value for node in ast.walk(ast.parse(source))
                  if isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and re.search(r"\b(INSERT|UPDATE)\b", node.value)]
    assert statements, "precondition: the badge code writes rows"
    if any("eas_uid" in sql for sql in statements) or ".attest(" in source:
        return
    claimed = _lines(_BADGE_ATTESTED)
    assert not claimed, (
        f"the badge code writes no attestation, and these lines say it does: {claimed}")


def test_the_attestation_is_not_said_to_certify_what_it_does_not_encode():
    source = (REPO / "runtime/blockchain/eas_client.py").read_text()
    attest = next(fn for fn in ast.walk(ast.parse(source))
                  if isinstance(fn, ast.AsyncFunctionDef) and fn.name == "attest")
    encoded = next(node for node in ast.walk(attest) if isinstance(node, ast.Call)
                   and getattr(node.func, "id", None) == "encode")
    fields = {el.slice.value for el in ast.walk(encoded.args[1])
              if isinstance(el, ast.Subscript) and isinstance(el.slice, ast.Constant)}
    assert fields, "precondition: the attestation encodes named fields"
    if fields & {"details", "audit", "contract_address"}:
        return
    claimed = _lines(_ATTESTATION_CERTIFIES_AUDIT)
    assert not claimed, (
        f"the attestation encodes only {sorted(fields)}, and these lines say it "
        f"certifies the audit: {claimed}")
