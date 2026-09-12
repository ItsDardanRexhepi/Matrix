"""The shipped examples may only do what the platform can do.

examples/01_contract_conversion.py read ``blockchain.demo_wallet_private_key``,
printed "Deploying to Base Sepolia...", and dispatched ``deploy_contract`` — an
action NEW-4 removed from ACTION_MAP. The deploy could never happen (the key was
never passed to anything, and the dispatcher answers "Unknown action"), so the
script did not spend the key. What it did instead was ask the operator to put a
private key in a config file for a step that does not exist, treat that key's
presence as the gate for it, and then explain the inevitable failure as "your
wallet lacks Base Sepolia ETH" — sending them to a faucet to fix nothing.

Each example is RUN here, against a stand-in dispatcher that records what it is
asked to do and a config that records which keys are read. Nothing is inferred
from the examples' prose.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = sorted((ROOT / "examples").glob("[0-9][0-9]_*.py"))
SIGNING_KEYS = {"demo_wallet_private_key", "private_key", "paymaster_private_key"}


class _RecordingDict(dict):
    """A config section that remembers every key the EXAMPLE FILE looked up.

    Only lookups made from the example's own code count. Platform classes an
    example constructs (NeoSafeRouter, say) read their own signer settings from
    the same config, and that is the platform's business, not the example's.
    """

    def __init__(self, data, reads, source):
        super().__init__({k: _RecordingDict(v, reads, source) if isinstance(v, dict) else v
                          for k, v in data.items()})
        self._reads = reads
        self._source = source

    def _note(self, key):
        if sys._getframe(2).f_code.co_filename == self._source:
            self._reads.add(key)

    def __getitem__(self, key):
        self._note(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._note(key)
        return super().get(key, default)


class _RecordingDispatcher:
    def __init__(self, actions):
        self._actions = actions

    async def execute(self, action, service=None, params=None, **kwargs):
        self._actions.append(action)
        return json.dumps({"status": "ok", "action": action, "result": {}})


def _run_example(path: Path, monkeypatch):
    example = json.loads((ROOT / "openmatrix.config.json.example").read_text())
    bc = example.setdefault("blockchain", {})
    bc["rpc_url"] = "http://127.0.0.1:9"      # configured, and goes nowhere
    bc["demo_wallet_private_key"] = "0x" + "11" * 32
    bc["demo_wallet_address"] = "0x" + "22" * 20

    reads: set[str] = set()
    actions: list[str] = []
    name = f"example_under_test_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_config", lambda: _RecordingDict(example, reads, str(path)))
    monkeypatch.setattr(module, "ServiceDispatcher", lambda config: _RecordingDispatcher(actions))
    try:
        asyncio.run(module.main())
    except SystemExit:
        pass
    return reads, actions


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_example_dispatches_only_actions_that_exist(path, monkeypatch):
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    _, actions = _run_example(path, monkeypatch)
    missing = sorted({a for a in actions if a not in ACTION_MAP})
    assert not missing, (
        f"{path.name} dispatches {missing}, which the platform does not have — "
        "the example narrates a step that cannot happen"
    )


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_example_does_not_read_a_signing_key_it_never_uses(path, monkeypatch):
    """No example signs anything itself. None may ask for, or gate on, a key.

    demo.py is the script that deploys with the operator's own key, and it
    prints the never-a-funded-wallet warning before it reads it.
    """
    reads, _ = _run_example(path, monkeypatch)
    assert not reads & SIGNING_KEYS, f"{path.name} reads {sorted(reads & SIGNING_KEYS)}"


def test_the_harness_sees_reads_and_actions(monkeypatch):
    """Not vacuous: the stand-ins really observe what an example does."""
    path = next(p for p in EXAMPLES if p.stem == "02_defi_loan")
    reads, actions = _run_example(path, monkeypatch)
    assert {"blockchain", "demo_wallet_address"} <= reads and actions
