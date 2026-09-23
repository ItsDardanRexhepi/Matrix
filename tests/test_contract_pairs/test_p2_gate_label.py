"""Contract pair P2: every call site -> the security gate's action label (engines Phase 1).

Six call sites hand the security gate an action through the public seam
(``runtime.security.get_morpheus_security().evaluate``, directly or through
``gateway/security_gate.py gate_action``): the ReAct pre-action (ProtocolStack),
the mobile bridge's direct action route, Trinity's hand-off, the ``/api/v1``
funnel (``ServiceRoutes._call``), the capability-invoke route
(``POST /api/v1/capabilities/{id}/invoke``) and the security preflight
(``POST /api/v1/security/preflight``). The consumer reads one field to decide
what it is looking at: ``action["action_type"]``.
``test_every_gate_call_site_is_driven`` finds the sites in the source: every
function outside tests/ that names the seam's accessor, the gateway's wrapper
or the core's class in any form the source shows (a call, a value passed on,
an import under any alias, an attribute, a string), imports the core directly
(an ``import`` statement, or ``import_module``/``__import__``/``resolve_name``
with a literal name, under an alias too), or touches a method called
``evaluate``. Each one found is either one of the six driven sites or is
listed with the reason it is not a site of its own, so a seventh written in
any of those forms fails here until it is driven or listed;
``test_the_finder_reads_each_form_of_a_seventh_site`` shows each form is found.
What it cannot see is a gate object handed in from elsewhere and reached
under a name built at run time, or the core imported under a name built at
run time.

This test drives each site for real, with a recording gate standing in for the
consumer, and pins what each one hands over against a golden file:

  * for every name the dispatcher can run: the label the ReAct seam, the bridge
    and the hand-off send — today the name itself, at every site;
  * for every ``_call`` pair in the funnel: the label it sends — the method
    name, after five aliases;
  * for every capability in the catalog: the label the invoke route sends —
    the capability's ``action``, which is an ACTION_MAP name;
  * the preflight's one fixed label, which dispatches nothing;
  * where two conventions meet (an action the funnel also reaches), how many
    actions reach the gate under two different labels.

That last number is the contract's defect, and one label per action from
every site is written as a strict xfail for the phase that consults one
vocabulary at every gate site. A change on either side — a producer that
starts sending something else, a funnel route added or renamed — fails this
pair, not a behaviour test three layers away. Rewrite the golden with
``ENGINES_BASELINE=write`` when the change is intended.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from runtime.blockchain.services.service_dispatcher import ACTION_MAP  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "p2_gate_labels.json"
WRITE = os.environ.get("ENGINES_BASELINE", "").strip().lower() == "write"


class RecordingGate:
    """The consumer side: records the label, then refuses, so nothing runs."""

    mode = SimpleNamespace(value="observe")

    def __init__(self):
        self.labels: list[str] = []

    async def initialize(self):
        return None

    async def persist_security_state(self):
        return None

    async def evaluate(self, action, context):
        self.labels.append(action.get("action_type"))
        return {"allow": False, "would_block": True, "route": "recorded", "reason": "recorded"}

    def take(self):
        labels, self.labels = self.labels, []
        return labels


@pytest.fixture
def gate(monkeypatch):
    import runtime.security as seam
    recording = RecordingGate()
    monkeypatch.setattr(seam, "get_morpheus_security", lambda *a, **k: recording)
    return recording


async def react_labels(gate) -> dict[str, str | None]:
    from runtime.protocols.integration import ProtocolStack
    stack = ProtocolStack({}, "neo")
    out = {}
    for name in sorted(ACTION_MAP):
        await stack.pre_action("platform_action", {"action": name, "params": {}},
                               {"agent": "neo", "memory_scope": "conv:p2"})
        seen = gate.take()
        out[name] = seen[0] if seen else None
    return out


async def handoff_labels(gate) -> dict[str, str | None]:
    from runtime.agents.handoff import AgentHandoff
    handoff = AgentHandoff({}, None)
    out = {}
    for name in sorted(ACTION_MAP):
        await handoff.escalate(name, {}, {})
        seen = gate.take()
        out[name] = seen[0] if seen else None
    return out


async def http_labels(gate, scratch) -> dict[str, dict]:
    """The three HTTP sites, through one gateway over *scratch*: the bridge per
    ACTION_MAP name, the capability-invoke route per catalog capability, and the
    security preflight once."""
    from aiohttp.test_utils import TestClient, TestServer
    from gateway.server import GatewayServer
    from runtime.capabilities import catalog
    from test_route_sweep import SWEEP_CONFIG
    server = GatewayServer({**SWEEP_CONFIG, "memory_dir": str(scratch),
                            "database": {"path": f"{scratch}/a.db"}})
    bridge, invoke = {}, {}
    async with TestClient(TestServer(server.create_app())) as client:
        gate.take()
        for name in sorted(ACTION_MAP):
            await client.post("/bridge/v1/action", json={"action": name, "params": {}})
            seen = gate.take()
            bridge[name] = seen[0] if seen else None
        for capability in sorted(c["id"] for c in catalog.CAPABILITIES):
            await client.post(f"/api/v1/capabilities/{capability}/invoke", json={"params": {}})
            seen = gate.take()
            invoke[capability] = seen[0] if seen else None
        await client.post("/api/v1/security/preflight", json={"to": "", "value_usd": 0})
        preflight = gate.take()
    return {"bridge": bridge, "capability_invoke": invoke, "security_preflight": preflight}


async def funnel_labels(gate) -> dict[str, str | None]:
    from gateway.service_routes import ServiceRoutes
    from test_privileged_vocabulary_coverage import funnel_call_sites
    out = {}
    for service, method in sorted(set(funnel_call_sites())):
        try:
            await ServiceRoutes._call(SimpleNamespace(), service, method)
        except web.HTTPForbidden:
            pass
        seen = gate.take()
        out[f"{service}.{method}"] = seen[0] if seen else None
    return out


def summarise_invoke(invoke: dict[str, str | None]) -> dict:
    """The invoke route's labels against the catalog and the ReAct seam's."""
    from runtime.capabilities import catalog
    actions = {c["id"]: c["action"] for c in catalog.CAPABILITIES}
    return {
        "capabilities": len(invoke),
        "reaches_gate": sum(v is not None for v in invoke.values()),
        "label_is_the_catalog_action": sum(invoke[c] == actions[c] for c in invoke),
        "catalog_action_is_an_action_map_name": sum(actions[c] in ACTION_MAP for c in invoke),
        "exceptions": {c: invoke[c] for c in sorted(invoke) if invoke[c] != actions[c]},
    }


def summarise(sites: dict[str, dict], funnel: dict[str, str | None]) -> dict:
    names = sorted(ACTION_MAP)
    summary = {"names": len(names), "sites": {}}
    for site, labels in sites.items():
        summary["sites"][site] = {
            "reaches_gate": sum(v is not None for v in labels.values()),
            "label_is_the_name": sum(labels[n] == n for n in names),
            "exceptions": {n: labels[n] for n in names if labels[n] != n},
        }
    # Where both conventions label the same action: the funnel pair an action
    # dispatches to, against the label the ReAct seam sends for that action.
    two_labels = {}
    for name in names:
        service, method = ACTION_MAP[name]
        funnel_label = funnel.get(f"{service}.{method}")
        if funnel_label is not None and funnel_label != sites["react"][name]:
            two_labels[name] = {"react": sites["react"][name], "funnel": funnel_label}
    reached_by_both = sum(1 for n in names if f"{ACTION_MAP[n][0]}.{ACTION_MAP[n][1]}" in funnel)
    return {**summary, "funnel": funnel,
            "actions_reached_by_the_funnel_too": reached_by_both,
            "actions_under_two_labels": two_labels}


async def measure(gate, scratch) -> dict:
    http = await http_labels(gate, scratch)
    sites = {"react": await react_labels(gate), "bridge": http["bridge"],
             "handoff": await handoff_labels(gate)}
    summary = summarise(sites, await funnel_labels(gate))
    # The invoke route labels an action by its catalog action, an ACTION_MAP
    # name; where that differs from the ReAct seam's label for the same name,
    # it is one more action under two labels.
    from runtime.capabilities import catalog
    for capability, label in http["capability_invoke"].items():
        name = catalog.get_by_id(capability)["action"]
        if label is not None and label != sites["react"].get(name):
            summary["actions_under_two_labels"].setdefault(name, {})["capability_invoke"] = label
    summary["capability_invoke"] = summarise_invoke(http["capability_invoke"])
    summary["security_preflight"] = {"labels": http["security_preflight"], "dispatches": False}
    return summary


@pytest.fixture
async def measured(gate, tmp_path):
    return await measure(gate, tmp_path)


async def test_every_site_hands_the_gate_the_golden_label(measured):
    if WRITE:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(measured, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert measured == golden


async def test_every_name_reaches_the_gate_from_every_dispatching_site(measured):
    for site, facts in measured["sites"].items():
        assert facts["reaches_gate"] == measured["names"], (site, facts["exceptions"])


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Phase 4 (authorization): the gate sites consult runtime/security/vocabulary.py, "
    "so an action has one label wherever it enters"))
async def test_one_action_reaches_the_gate_under_one_label(measured):
    assert not measured["actions_under_two_labels"], (
        f"{len(measured['actions_under_two_labels'])} actions reach the gate under two labels")


#: Where each driven site hands the gate its action, as (file, function).
DRIVEN_SITES = {
    ("runtime/protocols/integration.py", "_pre_action"),
    ("gateway/bridge.py", "execute_action"),
    ("runtime/agents/handoff.py", "escalate"),
    ("gateway/service_routes.py", "_call"),
    ("gateway/service_routes.py", "_handle_capability_invoke"),
    ("gateway/service_routes.py", "_handle_security_preflight"),
}

#: Every other place the finder below reports, and why it hands the gate no
#: action of its own.
NOT_A_SITE = {
    ("gateway/security_gate.py", "gate_action"):
        "the wrapper the funnel, the bridge, the invoke route and the preflight call",
    ("runtime/protocols/integration.py", "_init_protocols"):
        "builds the stack's gate; _pre_action hands it the action",
    ("gateway/server.py", "_start_cleanup_task"):
        "builds and initialises the process-wide gate at startup",
    ("runtime/protocols/omega.py", "_phase_gate"):
        "evaluates the framework's own RexhepiGate, not the security gate",
}

#: The seam itself, which defines the names the finder looks for.
SEAM = "runtime/security/__init__.py"

#: The names code reaches the security gate by: the seam's accessor, the
#: gateway's wrapper around it, and the core's class.
GATE_NAMES = {"get_morpheus_security", "gate_action", "MorpheusSecurity"}
#: The private core's package, imported directly rather than through the seam.
CORE_PACKAGE = "morpheus_security"


def _docstring_ids(tree: ast.AST) -> set[int]:
    return {id(node.body[0].value) for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)}


def _names_the_core(module: str) -> bool:
    return module == CORE_PACKAGE or module.startswith(CORE_PACKAGE + ".")


def _gate_references(tree: ast.AST) -> list[tuple[ast.AST, str]]:
    """Each node in *tree* that reaches for the gate, with what it names."""
    from test_no_event_sequence_grants_authority import import_call_targets, import_callees
    callees = import_callees(tree)
    aliases = set(GATE_NAMES)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            aliases |= {a.asname for a in node.names if a.name in GATE_NAMES and a.asname}
    prose = _docstring_ids(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in aliases:
            found.append((node, node.id))
        elif isinstance(node, ast.Attribute) and (node.attr in GATE_NAMES or node.attr == "evaluate"):
            found.append((node, node.attr))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            found += [(node, a.name) for a in node.names if a.name in GATE_NAMES]
            if _names_the_core(module):
                found.append((node, module))
        elif isinstance(node, ast.Import):
            found += [(node, a.name) for a in node.names if _names_the_core(a.name)]
        elif (isinstance(node, ast.Constant) and id(node) not in prose
              and node.value in GATE_NAMES | {"evaluate"}):
            found.append((node, node.value))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "evaluate":
            found.append((node, "evaluate"))
        elif isinstance(node, ast.Call):
            found += [(node, target) for target in import_call_targets(node, callees)[1] or ()
                      if _names_the_core(target)]
    return found


def gate_call_sites(root: Path = ROOT) -> set[tuple[str, str]]:
    """Every function outside tests/ (or ``<module>`` for module level) that
    reaches for the security gate in a form the source shows: it names the
    seam's accessor, the gateway's wrapper or the core's class — calling it,
    passing it, importing it under any alias, reaching it as an attribute or
    naming it in a string — imports the core's package directly (by an
    ``import`` statement or a call that imports a literal name), or touches a
    method called ``evaluate`` (called, passed or named in a string). The seam
    itself is left out."""
    sites = set()
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if rel.parts[0] == "tests" or rel.parts[0].startswith(".") or str(rel) == SEAM:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        owner: dict[int, str] = {}
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(fn):
                    owner[id(node)] = fn.name  # the innermost function is walked last
        for node, _ in _gate_references(tree):
            sites.add((str(rel), owner.get(id(node), "<module>")))
    return sites


def test_every_gate_call_site_is_driven():
    """The six sites above are all the places that hand the gate an action;
    every other place the finder reports is listed, with its reason, in
    NOT_A_SITE. A new site in any form the finder reads fails here until it
    is driven or listed."""
    found = gate_call_sites()
    assert found == DRIVEN_SITES | set(NOT_A_SITE), (
        sorted(found - DRIVEN_SITES - set(NOT_A_SITE)), sorted((DRIVEN_SITES | set(NOT_A_SITE)) - found))


#: A seventh site in each form the finder reads, one function per form.
SEVENTH_SITES = '''
async def by_accessor(request):
    from runtime.security import get_morpheus_security
    sec = get_morpheus_security()
    return await sec.evaluate({"action_type": "transfer_stablecoin"}, {})

async def by_wrapper_attribute(request):
    from gateway import security_gate
    return await security_gate.gate_action("transfer", {}, None)

async def by_alias(request):
    from gateway.security_gate import gate_action as g
    return await g("transfer", {}, None)

async def by_string(request):
    import runtime.security as seam
    return await getattr(seam, "get_morpheus_security")().evaluate({}, {})

async def by_core(request):
    import morpheus_security
    return morpheus_security

async def by_core_import_call(request):
    import importlib
    return importlib.import_module("morpheus_security")

class Handler:
    def __init__(self, gate):
        self.gate = gate

    async def by_stored_gate(self, request):
        return await self.gate.evaluate({"action_type": "transfer"}, {})

    async def by_passed_method(self, request):
        check = self.gate.evaluate
        return await check({}, {})
'''


def test_the_finder_reads_each_form_of_a_seventh_site(tmp_path):
    """Each form above is reported as its own site, and a module that only
    mentions the gate in prose is not."""
    (tmp_path / "gateway").mkdir()
    (tmp_path / "gateway" / "quiet.py").write_text(
        '"""Calls gate_action and get_morpheus_security().evaluate elsewhere."""\n'
        'NOTE = "evaluate the gate_action path"\n', encoding="utf-8")
    assert gate_call_sites(tmp_path) == set()
    (tmp_path / "gateway" / "seventh.py").write_text(SEVENTH_SITES, encoding="utf-8")
    found = {fn for rel, fn in gate_call_sites(tmp_path)}
    assert found == {"by_accessor", "by_wrapper_attribute", "by_alias", "by_string", "by_core",
                     "by_core_import_call", "by_stored_gate", "by_passed_method"}, found
