"""The texts about who signs on their own, and what gives a signature's budget
back, say what the code does.

Besides `Web3Manager.send_transaction`, five service paths sign and broadcast a
transaction themselves: the conversion pipeline's deploy, the attestation
service's revocation, its time-critical write and its queued writes, and
NeoSafe's revenue record. The last two go through the EAS client. The texts
that list them named the first three, and the check on that list found only a
`send_raw_transaction` written in a service module itself, so a broadcast made
through a runtime/blockchain helper was invisible to it. The queued writes,
metered as `attestation.attest` and `attestation.batch_attest`, came in beside
the three and were left out. The list is now derived from the services' own
broadcasts and from their calls into a helper that broadcasts.

Three texts said the revocation and the time-critical write signed under listed
exemptions. The revocation is metered, as `attestation.revoke`, and there is no
`eas.revoke` exemption; the time-critical write is metered when a caller asks
for it, and only the platform's own record of it is the listed
`eas.attest_time_critical`.

The README said a node's refusal is read where the services send and gives the
signature's budget back. No answer to a send is read now: the budget comes back
when another transaction in the signature's nonce slot is mined, whichever path
broadcast either one (tests/test_a_signature_is_settled_or_given_back.py).
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
BLOCKCHAIN = REPO / "runtime" / "blockchain"
SERVICES = BLOCKCHAIN / "services"

#: How the texts name each service path that signs and broadcasts on its own.
_NAMED = {
    "contract_conversion/service.py": "conversion pipeline's deploy",
    "attestation/service.py": "revoke",
    "attestation/time_critical.py": "time-critical write",
    "attestation/batch_processor.py": "queued writes",
    "neosafe.py": "revenue record",
}

#: The texts that list them: the exemption list's account of the shared send,
#: and `Web3Manager.get_account`, which says the same of its handle.
_LISTS = {
    "runtime/blockchain/sponsorship.py": "It is not their only one",
    "runtime/blockchain/web3_manager.py": "It is not their only one",
}


def _broadcasting_helpers() -> dict[str, set[str]]:
    """{class: its methods that call send_raw_transaction} for the classes in
    runtime/blockchain/*.py outside the shared manager and the services."""
    helpers: dict[str, set[str]] = {}
    for path in sorted(BLOCKCHAIN.glob("*.py")):
        if path.name == "web3_manager.py":
            continue
        for cls in ast.parse(path.read_text()).body:
            if not isinstance(cls, ast.ClassDef):
                continue
            for fn in cls.body:
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                        isinstance(n, ast.Attribute) and n.attr == "send_raw_transaction"
                        for n in ast.walk(fn)):
                    helpers.setdefault(cls.name, set()).add(fn.name)
    return helpers


def _service_modules_that_sign_on_their_own() -> set[str]:
    helpers = _broadcasting_helpers()
    found = set()
    for path in SERVICES.rglob("*.py"):
        tree = ast.parse(path.read_text())
        reached: set[str] = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.ImportFrom) and node.module
                    and node.module.startswith("runtime.blockchain.")
                    and not node.module.startswith("runtime.blockchain.services")):
                for alias in node.names:
                    reached |= helpers.get(alias.name, set())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and (node.func.attr == "send_raw_transaction" or node.func.attr in reached)):
                found.add(path.relative_to(SERVICES).as_posix())
    return found


def _prose(path: pathlib.Path) -> str:
    text = path.read_text()
    if path.suffix == ".py":
        text = "\n".join(re.sub(r"^\s*#:?\s?", "", line) for line in text.splitlines())
    return " ".join(text.split())


def test_the_derivation_follows_a_broadcast_through_a_helper():
    """SCOPE PIN for the control below: the EAS client's attest is a helper that
    broadcasts, and the batch processor reaches it."""
    assert "attest" in _broadcasting_helpers().get("EASClient", set())
    assert "attestation/batch_processor.py" in _service_modules_that_sign_on_their_own()


def test_each_list_names_every_service_path_that_signs_on_its_own():
    modules = _service_modules_that_sign_on_their_own()
    assert modules == set(_NAMED), (
        f"the service modules that sign and broadcast on their own are {sorted(modules)}; "
        f"the texts are held to {sorted(_NAMED)}")
    for rel, opening in _LISTS.items():
        prose = _prose(REPO / rel)
        start = prose.index(opening)
        listed = prose[start:prose.index(")", start)]
        missing = [phrase for phrase in _NAMED.values() if phrase not in listed]
        assert not missing, (
            f"{rel} lists the service paths that sign on their own and does not "
            f"name {missing}: {listed}")


def _sponsorship_bullet() -> str:
    readme = (REPO / "README.md").read_text()
    start = readme.index("- **Gas sponsorship is metered against what the EntryPoint can charge.**")
    end = readme.index("\n- **", start + 1)
    return " ".join(readme[start:end].split())


async def test_the_readme_says_what_gives_a_signatures_budget_back(tmp_path):
    """Measured first: a refusal from the list a node gives at its pool, on the
    shared send, leaves the signature's row holding budget. Then the README:
    it gives the rule that does give the budget back, the nonce, and says no
    answer to the send does."""
    from eth_account import Account
    from web3.exceptions import Web3RPCError

    from runtime.blockchain.sponsorship import SPEND_STATES, MeteredSigner, SponsorshipPolicy
    from runtime.blockchain.web3_manager import Web3Manager

    refusal = {"code": -32000, "message": "insufficient funds for gas * price + value"}

    class _Eth:
        gas_price = 1_000_000_000

        def get_transaction_count(self, _addr):
            return 0

        def send_raw_transaction(self, _raw):
            raise Web3RPCError(repr(refusal), rpc_response={"error": refusal})

        def get_transaction(self, _hash):
            from web3.exceptions import TransactionNotFound
            raise TransactionNotFound("not found")

    policy = SponsorshipPolicy.from_config({
        "paymaster": {"policy": {"daily_cap_usd": 100.0}},
        "database": {"path": str(tmp_path / "sponsor.db")}})
    signer = MeteredSigner(Account.create(), policy, "web3.send_transaction", "0xA", 3000.0)
    mgr = Web3Manager.__new__(Web3Manager)
    mgr.w3 = type("W3", (), {"eth": _Eth()})()
    mgr.available, mgr.chain_id, mgr._nonce_lock = True, 8453, None

    async def _signer_for(_action=None):
        return signer

    mgr.signer = _signer_for
    with pytest.raises(Web3RPCError):
        await mgr.send_transaction({"to": "0x" + "11" * 20, "value": 0, "gas": 21000,
                                    "gasPrice": 10**9, "nonce": 0, "chainId": 8453})
    assert policy.state_of(signer.last_reservation_id) == SPEND_STATES.SIGNED, (
        "a refusal on the shared send gave the budget back; the README says no "
        "answer to a send does")

    bullet = _sponsorship_bullet()
    assert "same nonce" in bullet, (
        "the README does not say what gives a signature's budget back: " + bullet)
    stale = re.findall(r"asked right after|holds no transaction under that hash|"
                       r"worker thread|refusal is read", bullet)
    assert not stale, f"the README still describes a refusal read at the send: {stale}"


#: How a receipt is waited for: `wait_for_receipt_on` and the helpers over it.
_RECEIPT_WAITS = {"wait_for_receipt_on", "wait_for_receipt", "receipt_within",
                  "settle_transaction", "_receipt"}


def _service_modules_that_send_without_waiting() -> set[str]:
    found = set()
    for path in SERVICES.rglob("*.py"):
        calls = {node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                 for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.Call)}
        if calls & {"send_transaction", "send_raw_transaction"} and not calls & _RECEIPT_WAITS:
            found.add(path.relative_to(SERVICES).as_posix())
    return found


def test_the_readme_says_a_receipt_nobody_waits_for_gives_nothing_back():
    """Some service modules send and never wait for a receipt, found here from
    their source; their rows are never settled and never close a slot. The
    README said a receipt counts when the platform waits for it, "as its
    services and blockchain capabilities do"."""
    senders = _service_modules_that_send_without_waiting()
    assert senders, "re-derive this test: every service module that sends now waits for a receipt"
    bullet = _sponsorship_bullet()
    assert "not waited for" in bullet, (
        f"{sorted(senders)} send without waiting for a receipt, and the README does "
        f"not say such a send gives nothing back: {bullet}")
    assert not re.search(r"as its services and (?:the )?blockchain capabilities do", bullet), bullet


_CALLED_AN_EXEMPTION = re.compile(
    r"revoke[^.;]{0,160}?(?:listed|unmetered)[^.;]{0,40}?exemption", re.IGNORECASE)


def test_no_text_says_the_revocation_signs_under_an_exemption():
    from runtime.blockchain.sponsorship import UNMETERED_PLATFORM_OPERATIONS

    if any("revoke" in op for op in UNMETERED_PLATFORM_OPERATIONS):
        return
    texts = [REPO / "README.md", *sorted((REPO / "docs").glob("*.md")),
             *sorted((REPO / "runtime").rglob("*.py")), *sorted((REPO / "gateway").rglob("*.py"))]
    saying_so = []
    for path in texts:
        for match in _CALLED_AN_EXEMPTION.finditer(_prose(path)):
            saying_so.append(f"{path.relative_to(REPO)}: ...{match.group(0)}...")
    assert not saying_so, (
        "no revocation is a listed exemption (the attestation service's revoke "
        "is metered as attestation.revoke), and these say it is:\n  "
        + "\n  ".join(saying_so))
