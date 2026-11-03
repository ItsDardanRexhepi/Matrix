"""The oracle example does not promise VRF randomness the platform cannot give.

examples/08_oracle_routing.py printed "Chainlink VRF provides verifiable
on-chain randomness", listed ``vrf`` among the "Oracle types supported", drew
a Chainlink VRF source feeding the gaming service, and on a VRF answer printed
"Source: Chainlink VRF v2". The VRF provider sends no request: it answers
``not_implemented`` (vrf_provider.py). And the example's request never reached
it: it passed ``request`` where the gateway takes ``params``, and ``vrf``
where the type is ``random_vrf``, so the dispatcher refused the call as
invalid and the example told the operator to configure a coordinator.

The example is run here with its VRF call answered by the real oracle
gateway, and what it prints is read.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "08_oracle_routing.py"


def _run(monkeypatch, capsys) -> tuple[str, list[dict]]:
    from runtime.blockchain.services.oracle_gateway.gateway import OracleGateway

    config = json.loads((ROOT / "matrix.config.json.example").read_text())
    # A coordinator configured, so the answer is the provider's own and not
    # the missing-coordinator refusal.
    gateway = OracleGateway({"oracle": {"vrf": {"coordinator_address": "0x" + "5" * 40}}})
    oracle_calls: list[dict] = []

    class _Dispatcher:
        async def execute(self, action, service=None, params=None, **kwargs):
            if action == "oracle_request":
                oracle_calls.append(dict(params or {}))
            if action == "oracle_request" and (params or {}).get("oracle_type") == "random_vrf":
                try:
                    out = await gateway.request(params["oracle_type"], params["params"])
                except Exception as exc:  # the dispatcher's shape for a refusal
                    return json.dumps({"status": "error", "error": str(exc)})
                return json.dumps({"status": "ok", "result": out})
            return json.dumps({"status": "error", "error": "not part of this test"})

    name = "example_under_test_08"
    spec = importlib.util.spec_from_file_location(name, EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_config", lambda: config)
    monkeypatch.setattr(module, "ServiceDispatcher", lambda _config: _Dispatcher())
    asyncio.run(module.main())
    return capsys.readouterr().out, oracle_calls


def test_the_vrf_step_reaches_the_provider_and_says_what_it_answered(monkeypatch, capsys):
    out, calls = _run(monkeypatch, capsys)
    vrf = [c for c in calls if c.get("oracle_type") == "random_vrf"]
    assert vrf and "params" in vrf[0], (
        f"the example's VRF call does not have the gateway's shape: {calls}")
    assert "No VRF request was sent" in out, out


def test_every_oracle_request_has_the_gateways_shape(monkeypatch, capsys):
    from runtime.blockchain.services.oracle_gateway.gateway import ORACLE_TYPES

    _out, calls = _run(monkeypatch, capsys)
    assert calls, "premise: the example makes oracle requests"
    for call in calls:
        assert set(call) == {"oracle_type", "params"}, call
        assert call["oracle_type"] in ORACLE_TYPES, call


def test_nothing_in_the_example_promises_vrf_randomness(monkeypatch, capsys):
    out, _calls = _run(monkeypatch, capsys)
    text = EXAMPLE.read_text()
    for phrase in ("verifiable on-chain randomness", "Source: Chainlink VRF v2",
                   "Verifiable random functions (Chainlink VRF v2)",
                   "Ensure VRF coordinator and subscription are configured"):
        assert phrase not in text and phrase not in out, phrase


def test_the_providers_docstring_does_not_say_it_submits():
    from runtime.blockchain.services.oracle_gateway.vrf_provider import VRFProvider

    doc = " ".join((VRFProvider.request_random.__doc__ or "").split())
    assert not doc.startswith("Submit a VRF randomness request on-chain")
    assert "NONE IS SENT" in doc
