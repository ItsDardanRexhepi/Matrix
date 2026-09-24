"""The skills in skills/ call attributes their sources actually have.

Each of the four skills failed on every call, into its own `except`, and the
model was handed the failure sentence as the tool's answer:

* audit_contract read `Finding.check_id`; the field is `rule_id`, so any
  contract with a finding came back "Audit failed: 'Finding' object has no
  attribute 'check_id'". A contract with no findings did render, and one with
  no function body at all was called "clean" under a BLOCKED status.
* check_balance, explain_transaction and gas_estimate built
  `BlockchainInterface(config)`, an abstract class, and read `.w3`, which it
  does not have. `.w3` is `Web3Manager`'s, the platform's shared connection.

And a skill never saw the server's configuration: the dispatcher calls a tool
with the model's arguments, so `config` was `{}`, or whatever the model wrote.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_WITH_FINDING = """pragma solidity 0.8.20;
contract Owned {
    address owner;
    function withdraw() external {
        require(tx.origin == owner);
        payable(msg.sender).transfer(address(this).balance);
    }
}
"""

_UNPROTECTED_SELFDESTRUCT = """pragma solidity 0.8.20;
contract Doomed {
    function destroy() external {
        selfdestruct(payable(msg.sender));
    }
}
"""

_NO_FUNCTION_BODY = "pragma solidity 0.8.20;\ncontract Store { uint256 value; }\n"


def _skill(name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"skill_{name}", ROOT / "skills" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


# ── audit_contract ────────────────────────────────────────────────────────


async def test_a_contract_with_findings_is_reported_not_failed():
    out = await _skill("audit_contract")(source_code=_WITH_FINDING, contract_name="Owned")
    assert "Audit failed" not in out, out
    assert "[SWC-115]" in out, out  # the tx.origin finding, by its rule id
    assert "(line 5)" in out, out


async def test_a_source_with_nothing_to_audit_is_not_called_clean():
    out = await _skill("audit_contract")(source_code=_NO_FUNCTION_BODY, contract_name="Store")
    assert "clean" not in out.lower(), out
    assert "**Status**: NOT AUDITABLE" in out, out
    assert "NOT an all-clear" in out, out


async def test_a_blocked_audit_does_not_claim_the_platform_blocked_a_deployment():
    # This platform does not deploy contracts; the skill advises whoever will.
    out = await _skill("audit_contract")(source_code=_UNPROTECTED_SELFDESTRUCT, contract_name="Doomed")
    assert "**Status**: BLOCKED" in out, out
    assert "Deployment blocked" not in out, out
    assert "Do not deploy this contract yet" in out, out


# ── the chain skills ──────────────────────────────────────────────────────


class _Eth:
    gas_price = 2_000_000_000

    @staticmethod
    def get_transaction(tx_hash):
        return {
            "from": "0x" + "11" * 20, "to": "0x" + "22" * 20, "value": 10**18,
            "gasPrice": 10**9, "input": bytes.fromhex("a9059cbb" + "00" * 64),
        }

    @staticmethod
    def get_transaction_receipt(tx_hash):
        return {"gasUsed": 50_000, "status": 1, "blockNumber": 1234}


class _W3:
    eth = _Eth()

    @staticmethod
    def from_wei(value, unit):
        return Decimal(value) / Decimal(10 ** (18 if unit == "ether" else 9))


class _Chain:
    available = True
    network = "base-sepolia"
    w3 = _W3()

    def __init__(self):
        self.balance_reads: list[str] = []

    def get_balance_eth(self, address):
        self.balance_reads.append(address)
        return 1.5


@pytest.fixture
def chain(monkeypatch):
    """The shared connection, stood in for, recording the config it was asked with."""
    from runtime.blockchain.web3_manager import Web3Manager

    fake = _Chain()
    fake.configs = []

    def get_shared(cls, config=None):
        fake.configs.append(config)
        return fake

    monkeypatch.setattr(Web3Manager, "get_shared", classmethod(get_shared))
    return fake


async def test_check_balance_reads_the_balance(chain):
    out = await _skill("check_balance")(address="0x" + "ab" * 20)
    assert "1.500000 ETH" in out, out
    assert chain.balance_reads == ["0x" + "ab" * 20]


async def test_check_balance_names_the_network_it_read_not_the_one_asked_for(chain):
    out = await _skill("check_balance")(address="0x" + "ab" * 20, network="polygon")
    assert "**Network**: base-sepolia" in out, out
    assert "polygon was not read" in out, out


async def test_explain_transaction_explains_it(chain):
    out = await _skill("explain_transaction")(tx_hash="0x" + "ee" * 32)
    assert "Could not fetch" not in out, out
    assert "**Value**: 1.000000 ETH" in out, out
    assert "`0xa9059cbb`" in out, out           # the selector, from bytes calldata
    assert "**Input Data**: 68 bytes" in out, out


async def test_gas_estimate_estimates(chain):
    out = await _skill("gas_estimate")(operation="transfer")
    assert "Gas estimation failed" not in out, out
    assert "2.00 Gwei" in out, out
    assert "| ETH Transfer | 21,000 |" in out, out


async def test_with_no_chain_configured_each_says_so(monkeypatch):
    from runtime.blockchain.web3_manager import Web3Manager

    offline = Web3Manager({})  # no rpc_url: offline, nothing reachable
    monkeypatch.setattr(Web3Manager, "get_shared", classmethod(lambda cls, config=None: offline))
    for name, kwargs in (("check_balance", {"address": "0x" + "ab" * 20}),
                         ("explain_transaction", {"tx_hash": "0x" + "ee" * 32}),
                         ("gas_estimate", {})):
        out = await _skill(name)(**kwargs)
        assert "abstract" not in out.lower(), (name, out)
        assert "not configured" in out, (name, out)


# ── the dispatcher hands a skill the server's config, never the model's ────


def _dispatcher(config: dict):
    from runtime.tools.dispatcher import ToolDispatcher

    return ToolDispatcher({"workspace": str(ROOT), **config})


async def test_a_skill_gets_the_servers_config_and_not_the_models(chain):
    server_wallet, model_wallet = "0x" + "cd" * 20, "0x" + "ef" * 20
    d = _dispatcher({"blockchain": {"platform_wallet": server_wallet}})
    out = await d._tools["check_balance"](
        config={"blockchain": {"platform_wallet": model_wallet,
                               "rpc_url": "http://model-chosen.invalid"}},
    )
    assert "1.500000 ETH" in out, out
    assert chain.balance_reads == [server_wallet]
    assert all("model-chosen" not in str(c) for c in chain.configs), chain.configs


async def test_the_model_cannot_lower_the_auditors_threshold():
    d = _dispatcher({})
    out = await d._tools["audit_contract"](
        source_code=_UNPROTECTED_SELFDESTRUCT, contract_name="Doomed",
        config={"security": {"block_on_critical": False}},
    )
    assert "**Status**: BLOCKED" in out, out
