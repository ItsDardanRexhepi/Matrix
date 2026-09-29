"""What the public text says about sending money is what the payment paths do.

The README's list of what you can do opened a bullet with "Send money anywhere
in the world in seconds" and paired it with "the transfer capability deducts a
small tiered fee"; the landing page offered to "transfer stablecoins". The
transfer_stablecoin capability debits and credits an in-process dict and
answers recorded_unsettled, value_moved false, and its ledger starts empty with
only a test helper to fund it; the cross-border send_payment answers
recorded_unsettled too. The one path that sends tokens on chain is Neo's
stablecoins tool, which builds its transfer from the platform wallet.

The premises are measured here, through the service dispatcher and from the
tool's source; the texts are then read against them.

The README also said "Every one of those runs against a blockchain you
configure" of the whole list; the payment ledgers record with no chain
configured at all, as the last test measures.

What this cannot see: a claim about moving money worded outside the patterns.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_NOT_READ = {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}
_A, _B = "0x" + "11" * 20, "0x" + "22" * 20

_SENDS_MONEY = [
    r"send money anywhere",
    r"anywhere in the world in seconds",
    r"transfer capability deducts",
    # The capability map's row for bridge_stargate, "Transfer stablecoins using
    # Stargate", describes a capability the catalog marks unavailable; it is
    # not an offer to send.
    r"\btransfer stablecoins\b(?! using)",
]


def _dispatcher():
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
    config = json.loads((ROOT / "matrix.config.json.example").read_text(encoding="utf-8"))
    config["blockchain"]["platform_wallet"] = "0x" + "44" * 20
    return ServiceDispatcher(config)


def _run(dispatcher, action: str, params: dict) -> dict:
    return json.loads(asyncio.run(dispatcher.execute(action=action, params=params)))


def _premises() -> list[str]:
    from runtime.access_policy import default_agent_access
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP

    problems = []
    dispatcher = _dispatcher()
    transfer = {"token": "USDC", "from_addr": _A, "to_addr": _B, "amount": 100}
    unfunded = _run(dispatcher, "transfer_stablecoin", transfer)["result"]
    if "Insufficient balance" not in str(unfunded.get("error", "")):
        problems.append(f"an unfunded ledger transfer answered {unfunded}")
    if any(pair == ("stablecoin", "set_balance") for pair in ACTION_MAP.values()):
        problems.append("an action funds the stablecoin ledger now")
    dispatcher._get_registry().get("stablecoin").set_balance(_A, "USDC", 1_000)
    funded = _run(dispatcher, "transfer_stablecoin", transfer)["result"]
    if not (funded.get("status") == "recorded_unsettled" and funded.get("value_moved") is False
            and funded.get("fee", 0) > 0):
        problems.append(f"a funded ledger transfer answered {funded}")
    payment = _run(dispatcher, "send_payment", {"sender": _A, "recipient": _B, "amount": 100,
                                                "from_currency": "USDC", "to_currency": "USDT"})
    if payment.get("result", {}).get("status") not in ("recorded_unsettled", "compliance_hold"):
        problems.append(f"a cross-border payment answered {payment.get('result')}")

    source = (ROOT / "runtime" / "blockchain" / "stablecoins.py").read_text(encoding="utf-8")
    senders = [ast.unparse(k_v[1]) for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Dict)
               for k_v in zip(node.keys, node.values)
               if isinstance(k_v[0], ast.Constant) and k_v[0].value == "from"]
    if not senders or any("platform_wallet" not in s for s in senders):
        problems.append(f"Neo's stablecoins tool sends from {senders} now")
    if default_agent_access("trinity", "stablecoins")[0]:
        problems.append("Trinity can use the stablecoins tool now")
    return problems


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).lower()


def test_the_scan_catches_the_old_copy():
    old = _flat("Send money anywhere in the world in seconds. The agent's stablecoin transfer takes "
                "nothing from it, the transfer capability deducts a small tiered fee. Create "
                "payments, transfer stablecoins, and record cross-border payments.")
    assert {p for p in _SENDS_MONEY if re.search(p, old)} == set(_SENDS_MONEY)
    assert not [p for p in _SENDS_MONEY if re.search(p, _flat(
        "Record payments today: the stablecoin-transfer capability records a payment. Create "
        "payments, and record stablecoin transfers and cross-border payments. | Bridge via "
        "Stargate | Transfer stablecoins using Stargate |"))]


def test_no_public_text_says_a_payment_capability_sends_money():
    premises = _premises()
    assert not premises, "re-derive this check: " + "; ".join(premises)
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        flat = _flat((ROOT / rel).read_text(encoding="utf-8"))
        for pattern in _SENDS_MONEY:
            for m in re.finditer(pattern, flat):
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 50):m.end() + 50]}...")
    assert not offenders, "\n".join(offenders)


_EVERY_ITEM_NEEDS_A_CHAIN = re.compile(r"every one of those runs against a blockchain", re.I)


def test_no_text_says_every_capability_needs_a_chain():
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
    config = json.loads((ROOT / "matrix.config.json.example").read_text(encoding="utf-8"))
    config["blockchain"] = {"platform_wallet": "0x" + "44" * 20}  # no RPC, no chain
    dispatcher = ServiceDispatcher(config)
    dispatcher._get_registry().get("stablecoin").set_balance(_A, "USDC", 1_000)
    recorded = _run(dispatcher, "transfer_stablecoin",
                    {"token": "USDC", "from_addr": _A, "to_addr": _B, "amount": 100})["result"]
    assert recorded.get("status") == "recorded_unsettled", (
        f"the ledger needs a chain now; re-derive this check: {recorded}")
    assert _EVERY_ITEM_NEEDS_A_CHAIN.search("Every one of those runs against a blockchain you configure.")
    offenders = [rel for rel in subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT,
                                                        text=True).splitlines()
                 if rel not in _NOT_READ and not rel.startswith("tests/") and (ROOT / rel).is_file()
                 and _EVERY_ITEM_NEEDS_A_CHAIN.search(_flat((ROOT / rel).read_text(encoding="utf-8")))]
    assert not offenders, offenders
