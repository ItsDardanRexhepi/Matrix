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
import asyncio
import importlib.util
import inspect
import json
import re
import subprocess
import sys
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


# ── The record is queued only where a schema is configured ──────────────────
#
# Example 09 ended "When a state-modifying action completes, the service
# dispatcher queues an EAS attestation of it; the queue is written to the chain
# once 50 have gathered", example 06 said the dispatcher's record is "queued like
# any record that is not time-critical", and examples/README.md and
# docs/blockchain.md said the record joins an in-memory batch, each with no
# condition. The attestation service resolves its schema before it queues
# anything and refuses the record when blockchain.eas_schema is not a
# well-formed bytes32 UID; the shipped example config's placeholder is not one.
# Run with that config, example 09 logged "Attestation failed ... EAS schema is
# not configured" for each of the steps that happened, queued nothing, and
# printed that sentence. A section of a document, or an example's docstring,
# that says an attestation or a record is queued states that condition; an
# example says what happened under the config it ran with.

_QUEUED = re.compile(
    r"\bqueues? an? (?:eas )?attestation\b"
    r"|\b(?:record|attestation)s?\b[^.;]{0,90}?\b(?:(?:is|are) queued|queued (?:in memory|until|like|on))\b"
    r"|\bjoins an in-memory batch\b|\bqueued on (?:the|an|a new) attestation service\b"
    r"|\beach queue an attestation\b|\bqueued unless time-critical\b", re.I)
_THE_CONDITION = re.compile(
    r"eas_schema|schemas\.<component>|\bschema (?:is )?(?:configured|registered)\b|well-formed bytes32"
    r"|where eas is set up", re.I)
_WELL_FORMED = "0x" + "ab" * 32


def _example_config(schema: str | None = None) -> dict:
    config = json.loads((ROOT / "matrix.config.json.example").read_text(encoding="utf-8"))
    bc = config.setdefault("blockchain", {})
    bc["rpc_url"] = "http://127.0.0.1:9"
    bc["demo_wallet_address"] = "0x" + "22" * 20
    if schema is not None:
        bc["eas_schema"] = schema
    return config


def _schema_resolves(config: dict) -> bool:
    from runtime.blockchain.services.attestation.service import AttestationService
    try:
        AttestationService(config)._resolve_schema("")
    except ValueError:
        return False
    return True


def _units() -> list[tuple[str, str]]:
    """(where, text): each section of a public document, and each example's docstring."""
    out = subprocess.check_output(["git", "ls-files", "*.md", "examples/*.py"], cwd=ROOT, text=True)
    units = []
    for rel in out.splitlines():
        if rel.startswith("tests/") or rel == "CHANGELOG.md" or not (ROOT / rel).is_file():
            continue
        text = (ROOT / rel).read_text(encoding="utf-8")
        if rel.endswith(".py"):
            units.append((rel, ast.get_docstring(ast.parse(text)) or ""))
            continue
        for section in re.split(r"\n(?=#{1,6} )", text):
            units.append((f"{rel} ({section.splitlines()[0][:60]})", section))
    return units


def _unconditional_queue_claims(units) -> list[str]:
    offenders = []
    for where, text in units:
        flat = " ".join(text.split())
        m = _QUEUED.search(flat)
        if m and not _THE_CONDITION.search(flat):
            offenders.append(f"{where}: ...{flat[max(0, m.start() - 60):m.end() + 40]}...")
    return offenders


def _run_example(stem: str, config: dict, monkeypatch, capsys) -> str:
    path = ROOT / "examples" / f"{stem}.py"
    name = f"example_queue_note_{stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)

    class _Refusing:
        async def execute(self, action, service=None, params=None, **kwargs):
            return json.dumps({"status": "error", "action": action, "error": "refused here"})

    monkeypatch.setattr(module, "load_config", lambda: config)
    monkeypatch.setattr(module, "ServiceDispatcher", lambda cfg: _Refusing())
    capsys.readouterr()
    asyncio.run(module.main())
    return " ".join(capsys.readouterr().out.split())


def test_the_shipped_example_config_attests_nothing():
    assert not _schema_resolves(_example_config()), (
        "the shipped example config's schema resolves now; re-derive this check")
    assert _schema_resolves(_example_config(_WELL_FORMED))


def test_the_queue_scan_catches_the_old_copy():
    old = [("examples/README.md (## EAS)", "It is not written on-chain straight away: it joins an "
                                          "in-memory batch that is submitted when 50 records have queued."),
           ("06", "the ServiceDispatcher hands the attestation service a record of it (action, "
                  "service), queued like any record that is not time-critical."),
           ("readme", "| `06_eas_attestation_chain.py` | Attest sample records through the attestation "
                      "capabilities (queued unless time-critical), batch them, verify one |"),
           ("docs", "| The service dispatcher's record | Queued on the attestation service of the "
                    "dispatcher's service registry, as a platform record |")]
    assert len(_unconditional_queue_claims(old)) == len(old)
    assert not _unconditional_queue_claims([("x", "When blockchain.eas_schema is a well-formed "
                                                  "bytes32 UID, the record joins an in-memory batch.")])


def test_no_section_says_a_record_is_queued_without_the_schema_it_needs():
    offenders = _unconditional_queue_claims(_units())
    assert not offenders, "\n".join(offenders)


def test_the_examples_say_what_happened_to_the_record_under_their_config(monkeypatch, capsys):
    for stem in ("06_eas_attestation_chain", "09_full_user_journey"):
        out = _run_example(stem, _example_config(), monkeypatch, capsys)
        assert "queues an EAS attestation" not in out, (
            f"{stem} says the dispatcher queues an attestation under a config whose schema "
            "the attestation service refuses")
        assert "nothing was queued" in out, stem
        out = _run_example(stem, _example_config(_WELL_FORMED), monkeypatch, capsys)
        assert "queues an EAS attestation" in out and "nothing was queued" not in out, stem
