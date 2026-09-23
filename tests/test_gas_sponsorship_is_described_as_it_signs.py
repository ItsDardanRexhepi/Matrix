"""What the code and the documents say about gas sponsorship is what the
signers do.

Two statements had drifted from the code:

* runtime/blockchain/gas_sponsor.py said its paymaster "funds the operations
  the policy allows; the rest are refused", and that sponsor_transaction pays
  "when the sponsorship policy allows it". sponsor_transaction signs through
  unmetered_platform_signer(..., "gas_sponsor.sponsor"), an exemption listed
  in UNMETERED_PLATFORM_OPERATIONS, and an exempt signer checks nothing
  before it signs. A signing path that skips the policy has to say so where
  it is written, so each exempt call site's docstring names its exemption.

* The README, docs/blockchain.md and docs/COMPLETE_CAPABILITY_MAP.md said an
  action outside the allowlist is refused. The paymaster route reads the
  allowlist on every request, but the signer the platform uses for its own
  capability transactions reads it only when a daily cap is set. The test
  runs that signer and checks that each document describes what it did, so
  a change to either side has to bring the other along.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
POLICY_DOCS = ("README.md", "docs/blockchain.md", "docs/COMPLETE_CAPABILITY_MAP.md")


def _exempt_call_sites():
    for path in sorted((REPO / "runtime").rglob("*.py")):
        src = path.read_text()
        if "unmetered_platform_signer(" not in src:
            continue
        for fn in ast.walk(ast.parse(src)):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name == "unmetered_platform_signer":
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name != "unmetered_platform_signer":
                    continue
                actions = [a.value for a in node.args
                           if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                yield path.relative_to(REPO), fn, actions


def test_every_exempt_signer_names_its_exemption_in_its_docstring():
    from runtime.blockchain.sponsorship import UNMETERED_PLATFORM_OPERATIONS

    sites = list(_exempt_call_sites())
    assert sites, "no call site of unmetered_platform_signer was found"
    silent = []
    for path, fn, actions in sites:
        assert actions, f"{path}:{fn.lineno} {fn.name} names its exemption indirectly"
        for action in actions:
            assert action in UNMETERED_PLATFORM_OPERATIONS, (
                f"{path}:{fn.name} signs as {action!r}, which is not a listed exemption")
            doc = ast.get_docstring(fn) or ""
            if action not in doc or "UNMETERED_PLATFORM_OPERATIONS" not in " ".join(doc.split()):
                silent.append(f"{path}:{fn.lineno} {fn.name} ({action})")
    assert not silent, (
        "these functions sign with no sponsorship check, and their docstrings "
        "do not say so: " + ", ".join(silent))


def test_gas_sponsor_does_not_claim_the_policy_governs_it():
    text = " ".join((REPO / "runtime/blockchain/gas_sponsor.py").read_text().split())
    for claim in ("funds the operations the policy allows",
                  "when the sponsorship policy allows it",
                  "users never pay",
                  "covers ALL gas fees"):
        assert claim not in text, f"gas_sponsor.py still says {claim!r}"


def test_the_documents_say_when_the_allowlist_is_read():
    pytest.importorskip("eth_account")
    from eth_account import Account

    from runtime.blockchain.sponsorship import (
        MeteredSigner,
        SponsorshipDenied,
        SponsorshipPolicy,
    )

    policy = SponsorshipPolicy(allowed_actions=["listed.action"], daily_cap_usd=None)
    signer = MeteredSigner(Account.create(), policy, "unlisted.action",
                           "0x" + "ab" * 20, None)
    tx = {"to": "0x" + "11" * 20, "value": 0, "gas": 21000,
          "gasPrice": 10**9, "nonce": 0, "chainId": 84532}
    try:
        signer.sign_transaction(tx)
        allowlist_read_without_a_cap = False
    except SponsorshipDenied:
        allowlist_read_without_a_cap = True

    wrong = []
    for rel in POLICY_DOCS:
        text = " ".join((REPO / rel).read_text().split())
        says_unread = ("only when a daily cap is set" in text
                       or "without reading the allowlist" in text)
        if says_unread == allowlist_read_without_a_cap:
            wrong.append(rel)
    if allowlist_read_without_a_cap:
        detail = "the capability signer now refuses an unlisted action with no cap set"
    else:
        detail = ("the capability signer signed an action outside the allowlist "
                  "with no daily cap set")
    assert not wrong, f"{detail}, and these documents say otherwise: {wrong}"
