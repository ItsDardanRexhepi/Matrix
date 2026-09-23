"""The deploy scripts' NeoSafe step reports what it read, not a revenue route.

contracts/neosafe_verifier.py called itself a revenue verifier that
"confirms all platform fees reach NeoSafe wallet". Its verify_revenue_route
read the wallet's balance and its nonce (eth_getTransactionCount, the count
of what the address has SENT, or for a contract account such as a Safe the
contracts it has created) and reported "is_receiving" when either was above
zero, so any deployed Safe was "receiving" whether or not anything had
reached it. scripts/deploy_all.py ran it as "Verify NeoSafe revenue routing
is set up", and scripts/verify_platform.py counted it as a passing
"revenue_route" check under "Confirm ... revenue routing works", with a
status that was OK whenever the balance was not negative.

The test drives verify_platform's NeoSafe check against a stand-in chain
where the NeoSafe wallet holds nothing and has a nonce of 1, which is what a
freshly deployed Safe that has received nothing looks like, and requires
that nothing it reports as passing claims receipt or routing. It then holds
the three files to the same.
"""
from __future__ import annotations

import asyncio
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
FILES = ("contracts/neosafe_verifier.py", "scripts/deploy_all.py", "scripts/verify_platform.py")
_ROUTE_OR_RECEIPT = re.compile(r"rout|receiv|incoming|revenue", re.IGNORECASE)
_CLAIMS = re.compile(
    r"confirms all platform fees|revenue routing (works|is set up)|NeoSafe revenue routing"
    r"|incoming transactions|revenue received|routing verified", re.IGNORECASE)


class _Eth:
    async def get_balance(self, address):
        return 0

    async def get_transaction_count(self, address):
        return 1

    async def get_block(self, which):
        return {"number": 1}


class _W3:
    eth = _Eth()

    @staticmethod
    def from_wei(value, unit):
        return value / 10**18


def test_a_wallet_that_received_nothing_is_not_reported_as_receiving(monkeypatch):
    pytest.importorskip("web3")
    pytest.importorskip("eth_account")
    from eth_account import Account

    import contracts.neosafe_verifier as neosafe
    from scripts import verify_platform

    async def stand_in(config):
        return _W3(), None

    monkeypatch.setattr(neosafe, "_build_web3", stand_in)
    config = {"rpc_url": "http://127.0.0.1:9", "chain_id": 84532,
              "private_key": Account.create().key.hex(),
              "neosafe_address": "0x" + "46" * 20}
    verifier = verify_platform.PlatformVerifier(config, {"contracts": {}})
    results = asyncio.run(verifier.check_neosafe())

    passing = sorted(key for key, value in results.items()
                     if isinstance(value, dict) and value.get("status") == "OK")
    assert passing, "precondition: the NeoSafe reads answered"
    claimed = [key for key in passing if _ROUTE_OR_RECEIPT.search(key)]
    assert not claimed, (
        f"the NeoSafe wallet holds nothing and has only a Safe's nonce, and "
        f"verify_platform reports {claimed} as passing")

    readers = {name: fn for name, fn in vars(verify_platform).items()
               if callable(fn) and getattr(fn, "__module__", "") == neosafe.__name__
               and asyncio.iscoroutinefunction(fn)}
    assert readers, "precondition: verify_platform uses the NeoSafe readers"
    for name, fn in readers.items():
        answer = asyncio.run(fn(config))
        said = {k: v for k, v in answer.items() if _ROUTE_OR_RECEIPT.search(k) and v}
        assert not said, (
            f"{name} read a balance of 0 and a nonce of 1, and answered {said}")


def test_the_neosafe_step_is_not_described_as_a_revenue_check():
    lines = [f"{rel}:{n}" for rel in FILES
             for n, line in enumerate((REPO / rel).read_text().splitlines(), 1)
             if _CLAIMS.search(line)]
    assert not lines, (
        "the NeoSafe step reads a balance and a nonce and checks no route, and "
        f"these lines say it verifies revenue: {lines}")
