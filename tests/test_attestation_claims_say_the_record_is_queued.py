"""No public text says every action is attested on-chain.

examples/README.md said "Every state-modifying action in The Matrix creates an
on-chain EAS attestation" and listed what each record held (code hashes,
amounts, transaction hashes, royalty info); examples/06 said "every
state-modifying capability is attested on-chain automatically"; example 07
said "Every routed payment is attested on-chain"; the README's example table
and runtime/blockchain/interface.py said the same.

What the code does, measured here rather than typed in: when an action on the
dispatcher's state-modifying list settles, `ServiceDispatcher._attest_action`
hands `AttestationService.attest` a record (action, service, actor, a params
hash, a timestamp) without `time_critical`, so it joins the in-memory batch,
which submits only when `batch_size` records have queued in the process. A
refusal and an unconfirmed broadcast are logged, not attested. So a statement
that every action creates, gets or is an on-chain attestation is not true of
any single action.

What this cannot see: the claim worded outside the patterns below.
"""

from __future__ import annotations

import ast
import inspect
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_CLAIMS = [
    r"\bevery (?:state-modifying |platform )?(?:action|capability|operation)\b[^.|\n]{0,60}"
    r"\b(?:creates?|gets?|is|are)\b[^.|\n]{0,40}\battest",
    r"\battest\w*[^.|\n]{0,40}\bfor every (?:state-modifying )?(?:action|capability|operation)\b",
    r"\bautomatically (?:creates?|attests?)\b[^.|\n]{0,30}\battestation",
    r"\battestations? (?:is|are) created for every\b",
    r"\b(?:every|each) (?:routed )?payment (?:is )?attested on-chain",
]
_SURFACES = ("README.md", "docs/", "web/", "education/", "examples/", "sdk/",
             "runtime/blockchain/interface.py")


def _claims(text: str) -> list[str]:
    flat = re.sub(r"[ \t]*\n[ \t]*(?:#\s*|\*\s*)?", " ", text)
    return [m.group(0) for p in _CLAIMS for m in re.finditer(p, flat, re.I)]


def test_the_record_is_queued_not_written():
    from runtime.blockchain.services.attestation.service import AttestationService
    from runtime.blockchain.services import service_dispatcher

    assert inspect.signature(AttestationService.__init__).parameters["batch_size"].default > 1
    source = inspect.getsource(service_dispatcher.ServiceDispatcher._attest_action)
    calls = [n for n in ast.walk(ast.parse(inspect.cleandoc("\n" + source)))
             if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "attest"]
    assert calls, "_attest_action no longer calls attest()"
    assert all("time_critical" not in {k.arg for k in c.keywords} for c in calls)


def test_the_claim_scan_catches_the_old_copy():
    assert _claims("Every state-modifying action in The Matrix creates an on-chain EAS "
                   "(Ethereum Attestation Service) attestation.")
    assert _claims("This is the trust layer: every state-modifying capability is attested "
                   "on-chain automatically.")
    assert _claims("- EAS attestations are created for every state-modifying action")
    assert _claims("3. Automatically creates an EAS attestation for state-modifying actions")
    assert _claims("Every routed payment is attested on-chain.")
    assert not _claims("When an action on the dispatcher's state-modifying list settles, "
                       "the dispatcher hands the attestation service a record of it.")


def test_no_public_text_says_every_action_is_attested_on_chain():
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if not rel.startswith(_SURFACES) or not rel.endswith((".md", ".html", ".py")):
            continue
        if not (ROOT / rel).is_file():
            continue
        for claim in _claims((ROOT / rel).read_text(encoding="utf-8")):
            offenders.append(f"{rel}: {claim!r}")
    assert not offenders, "\n".join(offenders)
