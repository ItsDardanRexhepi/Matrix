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
import re
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


class _RefusingDispatcher(_RecordingDispatcher):
    """Refuses every action at the envelope (status "error"), the shape the
    dispatcher gives an exception or parameters the method does not take."""

    async def execute(self, action, service=None, params=None, **kwargs):
        self._actions.append(action)
        return json.dumps({"status": "error", "action": action,
                           "error": "not_deployed: refused by the test dispatcher"})


def _run_example(path: Path, monkeypatch, *, dispatcher_configs: list | None = None,
                 dispatcher=None):
    example = json.loads((ROOT / "matrix.config.json.example").read_text())
    bc = example.setdefault("blockchain", {})
    bc["rpc_url"] = "http://127.0.0.1:9"      # configured, and goes nowhere
    bc["demo_wallet_private_key"] = "0x" + "11" * 32
    bc["demo_wallet_address"] = "0x" + "22" * 20
    bc["paymaster_private_key"] = "0x" + "33" * 32
    # An operator who turned on on-chain deployment for the gateway. The key is
    # the one ContractConversionService reads; test_auto_deploy_key_is_real
    # holds that, so this cannot silently become a key nothing reads.
    example.setdefault("conversion", {})["auto_deploy"] = True

    reads: set[str] = set()
    actions: list[str] = []
    configs = dispatcher_configs if dispatcher_configs is not None else []
    name = f"example_under_test_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_config", lambda: _RecordingDict(example, reads, str(path)))
    make = dispatcher or _RecordingDispatcher
    monkeypatch.setattr(module, "ServiceDispatcher",
                        lambda config: configs.append(config) or make(actions))
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


def test_auto_deploy_key_is_real():
    """The config key the harness sets is the one the conversion service obeys.

    examples/01 used to name `contract_conversion.auto_deploy`, which nothing
    reads; the service reads `conversion.auto_deploy`.
    """
    from runtime.blockchain.services.contract_conversion.service import ContractConversionService
    on = {"blockchain": {"rpc_url": "http://127.0.0.1:9"}, "conversion": {"auto_deploy": True}}
    decoy = {"blockchain": {"rpc_url": "http://127.0.0.1:9"}, "contract_conversion": {"auto_deploy": True}}
    assert ContractConversionService(on)._auto_deploy is True
    assert ContractConversionService(decoy)._auto_deploy is False


def test_no_example_can_make_the_platform_deploy(monkeypatch):
    """Round-1 review: 01 said it "signs nothing", unconditionally.

    With conversion.auto_deploy on, the convert_contract it dispatches compiles
    the result and deploys it with the platform account
    (contract_conversion/service.py `_compile_and_deploy` -> `get_account()`),
    on whatever network is configured, with no warning. The claim is now made
    true rather than qualified: an example runs the platform with deployment
    off, whatever the operator set for the gateway. The verdict is the real
    service's, built from the config each example hands its dispatcher, for
    every example that dispatches anything to contract_conversion.
    """
    from runtime.blockchain.services.contract_conversion.service import ContractConversionService
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    checked, problems = [], []
    for path in EXAMPLES:
        configs: list = []
        _, actions = _run_example(path, monkeypatch, dispatcher_configs=configs)
        converts = sorted({a for a in actions if ACTION_MAP.get(a, ("",))[0] == "contract_conversion"})
        if not converts:
            continue
        checked.append(path.name)
        if any(ContractConversionService(c)._auto_deploy for c in configs):
            problems.append(f"{path.name} dispatches {converts} with conversion.auto_deploy on")
    assert checked, "no example dispatches to contract_conversion — this test observed nothing"
    assert not problems, "running these examples deploys with the platform account:\n  " + "\n  ".join(problems)


# ── An example reports what happened, not what it meant to do ──────────────
#
# examples/09_full_user_journey.py printed, for every step whose dispatch was
# refused, a success line marked "(fallback)" ("Staked: 100.0 ... (fallback)",
# "Vote cast: FOR (fallback)"), passed invented ids ("dao-builders-001",
# "proposal-001") to the steps after it, and ended "FULL USER JOURNEY COMPLETE"
# with "Attestations: 12 (one per state-modifying action)". Every example is
# run here against a dispatcher that refuses every action.

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_REFUSED_BUT_REPORTED = [
    r"\(fallback\)|fallback id",
    r"journey complete",
    r"attestations:\s*\d+",
]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_an_example_does_not_report_a_refused_action_as_done(path, monkeypatch, capsys):
    capsys.readouterr()
    _, actions = _run_example(path, monkeypatch, dispatcher=_RefusingDispatcher)
    out = _ANSI.sub("", capsys.readouterr().out).lower()
    offenders = [line.strip() for line in out.splitlines()
                 if any(re.search(p, line) for p in _REFUSED_BUT_REPORTED)]
    assert not offenders, (
        f"{path.name}, with every one of its {len(actions)} actions refused, printed: "
        + "; ".join(offenders[:8]))



# ── An example judges a step by what the dispatcher says happened ────────────
#
# The refusing dispatcher above answers at the envelope. The real dispatcher
# does that only for an exception or bad parameters: a service that answers
# {"status": "not_deployed"} comes back in an envelope whose "status" is "ok"
# (it is about the dispatch) and whose call_outcome is "failure". Example 09
# read envelope "ok" as done and printed "stake: done" and "3 of 12 steps
# happened" for a stake that answered not_deployed. And examples 02, 03, 04,
# 06, 08 and 09 passed parameters their services do not take (create_loan's
# ltv_ratio, create_dao without config, tokenize_asset without metadata,
# create_nft_collection without collection_type, create_attestation without
# schema_uid, get_price without pair, oracle_request without params), so the
# real dispatcher refused them as invalid before any service ran, and deploying
# the contracts would not have changed that.
#
# This dispatcher binds each call's parameters to the real service method's
# signature, answering a binding failure as the real dispatcher does, and
# answers every call that binds with the real envelope shape around a
# not_deployed result, its call_outcome computed by the platform's own
# report_of.

class _NotDeployedDispatcher(_RecordingDispatcher):
    problems: list = []

    async def execute(self, action, service=None, params=None, **kwargs):
        import importlib
        import inspect
        from runtime.blockchain.services.registry import _SERVICE_MAP
        from runtime.blockchain.services.service_dispatcher import (
            ACTION_MAP, _STATE_MODIFYING_ACTIONS)
        from runtime.protocols.outcome_truth import FAILURE, OUTCOME_FIELD, report_of

        self._actions.append(action)
        params = params or {}
        target, method_name = ACTION_MAP[action][:2]
        module_path, class_name = _SERVICE_MAP[target]
        cls = getattr(importlib.import_module(module_path, "runtime.blockchain.services"), class_name)
        try:
            inspect.signature(getattr(cls, method_name)).bind(None, **params)
        except TypeError as exc:
            _NotDeployedDispatcher.problems.append(f"{action}: {exc}")
            return json.dumps({"status": "error", OUTCOME_FIELD: FAILURE,
                               "error_category": "validation",
                               "error": f"Invalid parameters for {action}: {exc}"})
        result = {"status": "not_deployed",
                  "message": "This service requires a deployed contract."}
        return json.dumps({
            "status": "ok",
            OUTCOME_FIELD: report_of(result, status_describes_the_call=action in _STATE_MODIFYING_ACTIONS),
            "action": action,
            "service": target,
            "result": result,
        })


def test_the_not_deployed_envelope_is_the_real_one():
    """Not vacuous: report_of reads a not_deployed answer as a failure for a
    write and for a read, so the envelope carries what the real one carries."""
    from runtime.protocols.outcome_truth import report_of
    assert report_of({"status": "not_deployed"}, status_describes_the_call=True) == "failure"
    assert report_of({"status": "not_deployed"}, status_describes_the_call=False) == "failure"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_every_example_passes_parameters_its_services_take(path, monkeypatch):
    _NotDeployedDispatcher.problems = []
    _run_example(path, monkeypatch, dispatcher=_NotDeployedDispatcher)
    assert not _NotDeployedDispatcher.problems, (
        f"{path.name} passes parameters the service method does not take:\n  "
        + "\n  ".join(_NotDeployedDispatcher.problems))


_REPORTED_AS_DONE = [
    r":\s*done\s*$",
    r"\b[1-9]\d* of \d+ steps happened",
    r"\bcomplete\s*$",
    r"\(fallback\)|fallback id",
    r"(?:royalty distribution|payout) breakdown",
]


def test_the_done_scan_sees_the_old_output():
    old = ["+ stake: done", "Journey summary: 3 of 12 steps happened", "NFT WITH ROYALTIES COMPLETE",
           "Staked: 100.0 (fallback)", "Royalty Distribution Breakdown:", "Payout Breakdown:"]
    for line in old:
        assert any(re.search(p, line.lower()) for p in _REPORTED_AS_DONE), line
    fine = ["! stake: not done (not_deployed: ...)", "Journey summary: 0 of 12 steps happened",
            "! stake: not confirmed (recorded, not settled)", "Example 07 summary"]
    for line in fine:
        assert not any(re.search(p, line.lower()) for p in _REPORTED_AS_DONE), line


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_an_example_does_not_report_a_not_deployed_action_as_done(path, monkeypatch, capsys):
    capsys.readouterr()
    _NotDeployedDispatcher.problems = []
    _, actions = _run_example(path, monkeypatch, dispatcher=_NotDeployedDispatcher)
    out = _ANSI.sub("", capsys.readouterr().out).lower()
    offenders = [line.strip() for line in out.splitlines()
                 if any(re.search(p, line) for p in _REPORTED_AS_DONE)]
    assert not offenders, (
        f"{path.name}, with every one of its {len(actions)} actions answered not_deployed, printed: "
        + "; ".join(offenders[:8]))
