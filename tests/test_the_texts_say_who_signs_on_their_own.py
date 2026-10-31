"""The texts about who signs on their own, and what gives a signature's budget
back, say what the code does.

Three texts said the attestation service's revocation and its time-critical
write signed under listed exemptions. The revocation is metered, as
`attestation.revoke`, and there is no `eas.revoke` exemption; the time-critical
write is metered when a caller asks for it, and only the platform's own record
of it is the listed `eas.attest_time_critical`.

The README said a node's refusal is read where the services send and gives the
signature's budget back, save on three service paths that sign on their own.
No answer to a send is read now: the budget comes back when another
transaction in the signature's nonce slot is mined, whichever path broadcast
either one (tests/test_a_signature_is_settled_or_given_back.py), and the README
says so.
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


def _prose(path: pathlib.Path) -> str:
    text = path.read_text()
    if path.suffix == ".py":
        text = "\n".join(re.sub(r"^\s*#:?\s?", "", line) for line in text.splitlines())
    return " ".join(text.split())


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
