"""How many state changes reach the security gate under a name it classifies (engines Phase 1).

The security core is handed a label for every action it evaluates, and answers,
label by label, whether it classifies it; what it does with a label it
classifies, or with one it does not, is the core's and is not described here.
A dispatcher action reaches it under one of two conventions, and no one
vocabulary joins them (``test_contract_pairs/test_p2_gate_label.py`` drives all
six sites that hand it a label; this file counts one site of each convention):

  * the ReAct seam hands it the ACTION_MAP name itself — ``platform_action``'s
    inner ``action`` verbatim (runtime/security/action_map.py canonical_action) —
    as do the mobile bridge, the hand-off and the capability-invoke route;
  * the ``/api/v1`` funnel hands it the service METHOD name after five aliases
    (gateway/security_gate.py action_type_for, called from
    gateway/service_routes.py ``_call``).

This file measures that gap before anything is changed to close it:

  * the DENOMINATORS are public, pinned in MEASURED and always checked, so a
    change to the dispatcher's or the funnel's table is a CI event: the
    state-modifying ACTION_MAP names (132 in the literal, 184 once the
    capability catalog is installed at import) and the state-modifying
    ``_call`` pairs (51). The Phase 0 packet's census found 50 pairs with a
    regex over the source; the regex misses ``supply_chain.log_event``, whose
    call is split across lines with a comment between the parenthesis and its
    arguments, which the AST below does not. (The regex also matches a
    docstring that quotes a ``social.create_community`` call, a pair that has
    real call sites too, so its match count equals the AST's 87 by
    coincidence.)
  * the NUMERATORS — how many of those reach the gate under a label the
    separately installed security core classifies, directly or through
    ``runtime/security/vocabulary.py`` — are counts of the core's answers, so
    they are measured only where the core is importable and are not pinned in
    this repository (Phase 0 packet OD-7: which verbs carry which privileges
    is the core's to decide). Where the core is installed they are checked to
    be counts within their denominators, and against a pin kept beside the
    core when ENGINES_COVERAGE_PINS names one;
  * full coverage is written as ``xfail(strict=True, raises=AssertionError)``.
    It fails today and is expected to pass only when the phase that makes the
    gate sites consult one vocabulary lands — at which point strict makes the
    unexpected pass a failure until the marker is removed.

Nothing here says which labels the core classifies, or how many; the core is
asked, label by label, through the one method (``_requires_morpheus``) the
repository's own seam test already calls.

It also holds the vocabulary table itself to its Phase 1 contract: it covers
exactly the dispatchable names, a name reads iff the dispatcher calls it a read,
it agrees with the funnel's aliases, and nothing consults it yet: no module
outside tests/ imports or reaches it in any form ``vocabulary_consumers``
reads (each exercised by a probe below), and a gateway booted in shadow mode
never loads it.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime.blockchain.services import service_dispatcher as sd  # noqa: E402
from runtime.security.action_map import canonical_action  # noqa: E402
from runtime.security.vocabulary import CANONICAL, READ  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DISPATCHER = ROOT / "runtime" / "blockchain" / "services" / "service_dispatcher.py"
SERVICE_ROUTES = ROOT / "gateway" / "service_routes.py"
SECURITY_GATE = ROOT / "gateway" / "security_gate.py"
VOCABULARY = ROOT / "runtime" / "security" / "vocabulary.py"

#: The public denominators, measured at The Matrix c637715 (the tables this
#: branch leaves as they were).
MEASURED = {
    "action_map_literal": 193,
    "action_map_runtime": 253,
    "state_modifying_literal": 132,
    "state_modifying_runtime": 184,
    "funnel_call_sites": 87,
    "funnel_pairs": 84,
    "funnel_state_modifying_pairs": 51,
}

#: Each numerator, and the denominator it counts within. Measured only where
#: the security core is importable, and not pinned here (see the docstring).
NUMERATORS = {
    "react_classified_literal": "state_modifying_literal",
    "react_classified_runtime": "state_modifying_runtime",
    "funnel_classified": "funnel_state_modifying_pairs",
    "vocabulary_classified_runtime": "state_modifying_runtime",
}
#: A JSON file of the numerators, kept beside the security core, never here.
PINS_ENV = "ENGINES_COVERAGE_PINS"

PHASE_4 = ("measured gap, not a target: the gate sites consult one vocabulary only in "
           "engines Phase 4 (authorization), which flips this")


# ── instruments ──────────────────────────────────────────────────────────────

def _literal_keys(path: Path, name: str) -> list[str]:
    """The string constants of the dict or frozenset({...}) literal bound to *name*."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        target = (node.target if isinstance(node, ast.AnnAssign) else
                  node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1
                  else None)
        if not (isinstance(target, ast.Name) and target.id == name) or node.value is None:
            continue
        value = node.value
        if isinstance(value, ast.Dict):
            return [k.value for k in value.keys]
        if isinstance(value, ast.Call) and value.args and isinstance(value.args[0], ast.Set):
            return [e.value for e in value.args[0].elts]
    raise AssertionError(f"{name} literal not found in {path}")


def funnel_call_sites() -> list[tuple[str, str]]:
    """Every ``self._call("service", "method", ...)`` in the /api/v1 funnel, by AST."""
    sites = []
    for node in ast.walk(ast.parse(SERVICE_ROUTES.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_call" and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"):
            args = node.args[:2]
            assert len(args) == 2 and all(isinstance(a, ast.Constant) for a in args), (
                f"a _call site at line {node.lineno} is not two string literals; "
                "the census cannot see it")
            sites.append((args[0].value, args[1].value))
    return sites


def funnel_state_modifying_pairs() -> list[tuple[str, str]]:
    """Distinct funnel pairs that some state-modifying ACTION_MAP name dispatches to."""
    names_by_pair: dict[tuple[str, str], list[str]] = {}
    for name, pair in sd.ACTION_MAP.items():
        names_by_pair.setdefault(tuple(pair), []).append(name)
    return sorted(p for p in set(funnel_call_sites())
                  if any(n in sd._STATE_MODIFYING_ACTIONS for n in names_by_pair.get(p, [])))


def react_label(name: str) -> str:
    """The label the ReAct seam hands the gate for ``platform_action(action=name)``."""
    return canonical_action("platform_action", {"action": name})[0]


def funnel_label(service: str, method: str) -> str:
    from gateway.security_gate import action_type_for
    return action_type_for(service, method)


def funnel_aliases() -> dict[str, str]:
    """The alias literal inside action_type_for, read rather than copied."""
    for node in ast.walk(ast.parse(SECURITY_GATE.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "aliases" and isinstance(node.value, ast.Dict)):
            return {k.value: v.value for k, v in zip(node.value.keys, node.value.values)}
    raise AssertionError("aliases literal not found in action_type_for")


def classifier():
    """The security core's own classifier, or a skip where it is not installed."""
    morpheus = pytest.importorskip("morpheus_security.morpheus")
    return morpheus.MorpheusSecurity._requires_morpheus


def measure(classified=None) -> dict[str, int]:
    """Every figure in MEASURED; the NUMERATORS too when *classified* is given."""
    literal_sm = set(_literal_keys(DISPATCHER, "_STATE_MODIFYING_ACTIONS"))
    runtime_sm = set(sd._STATE_MODIFYING_ACTIONS)
    pairs = funnel_state_modifying_pairs()
    out = {
        "action_map_literal": len(_literal_keys(DISPATCHER, "ACTION_MAP")),
        "action_map_runtime": len(sd.ACTION_MAP),
        "state_modifying_literal": len(literal_sm),
        "state_modifying_runtime": len(runtime_sm),
        "funnel_call_sites": len(funnel_call_sites()),
        "funnel_pairs": len(set(funnel_call_sites())),
        "funnel_state_modifying_pairs": len(pairs),
    }
    if classified is not None:
        out.update({
            "react_classified_literal": sum(bool(classified(react_label(n))) for n in literal_sm),
            "react_classified_runtime": sum(bool(classified(react_label(n))) for n in runtime_sm),
            "funnel_classified": sum(bool(classified(funnel_label(*p))) for p in pairs),
            "vocabulary_classified_runtime": sum(bool(classified(CANONICAL[n])) for n in runtime_sm),
        })
    return out


# ── the public half: always checked ──────────────────────────────────────────

def test_the_denominators_are_the_measured_ones():
    assert measure() == MEASURED


def test_the_literal_state_modifying_set_is_inside_the_literal_action_map():
    literal_sm = set(_literal_keys(DISPATCHER, "_STATE_MODIFYING_ACTIONS"))
    assert literal_sm <= set(_literal_keys(DISPATCHER, "ACTION_MAP"))
    assert set(sd._STATE_MODIFYING_ACTIONS) <= set(sd.ACTION_MAP)


def test_the_react_seam_hands_the_gate_the_action_name_itself():
    """The fact the numerators measure: no translation happens on this path."""
    assert all(react_label(n) == n for n in sd.ACTION_MAP)


# ── the vocabulary table (runtime/security/vocabulary.py) ────────────────────

def test_the_vocabulary_covers_exactly_the_dispatchable_names():
    literal = _literal_keys(VOCABULARY, "CANONICAL")
    assert len(literal) == len(set(literal)) == MEASURED["action_map_runtime"]
    assert set(CANONICAL) == set(sd.ACTION_MAP), (
        sorted(set(sd.ACTION_MAP) - set(CANONICAL)), sorted(set(CANONICAL) - set(sd.ACTION_MAP)))


def test_a_name_reads_iff_the_dispatcher_calls_it_a_read():
    wrong = sorted(n for n, verb in CANONICAL.items()
                   if (verb == READ) != (n not in sd._STATE_MODIFYING_ACTIONS))
    assert not wrong, wrong


def test_every_verb_is_one_plain_word():
    bad = sorted({v for v in CANONICAL.values() if not re.fullmatch(r"[a-z]+(_[a-z]+)?", v)})
    assert not bad, bad


def test_the_funnel_aliases_fold_in():
    """Where the funnel's alias table renames a method an ACTION_MAP name
    dispatches to, the vocabulary gives that name the alias's verb."""
    aliases = funnel_aliases()
    assert len(aliases) == 5
    folded = {n: aliases[m] for n, (_, m) in sd.ACTION_MAP.items() if m in aliases}
    assert set(folded) == {"create_payment", "send_payment", "add_liquidity", "remove_liquidity"}
    assert {n: CANONICAL[n] for n in folded} == folded
    for name in folded:
        assert CANONICAL[name] == funnel_label(*sd.ACTION_MAP[name])


VOCABULARY_MODULE = "runtime.security.vocabulary"
#: A string that names the module in pieces, as an import assembled at run
#: time would: "vocabulary", ".vocabulary" or ":vocabulary" alone, or
#: "security.vocabulary" (or "/" or ":" for the dot).
VOCABULARY_STRING = re.compile(r"^[.:]?vocabulary$|security[./:]vocabulary")


def _docstrings(tree: ast.AST) -> set[int]:
    return {id(node.body[0].value) for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)}


def vocabulary_consumers(root: Path) -> list[str]:
    """Every place outside tests/ that imports or reaches the vocabulary
    module in a form ``imports_of`` reads — every ``import``/``from`` form,
    relative ones resolved against the importing file's package;
    ``import_module``, ``__import__`` or ``pkgutil.resolve_name`` with a
    literal, under an alias too; an attribute or a literal ``getattr`` of an
    imported package, or of a name a plain assignment re-bound to one — or
    holds a string matching VOCABULARY_STRING. Docstrings are prose and are
    not read. Not seen here: the module reached through an imported package
    handed to a call or kept in a container, or by a name built at run time
    in pieces the string match does not spell; the boot test below is the
    run-time half."""
    from test_no_event_sequence_grants_authority import imports_of
    hits = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if rel.parts[0] in ("tests",) or rel.parts[0].startswith(".") or path == root / VOCABULARY.relative_to(ROOT):
            continue
        for line, name in imports_of(path, root):
            if name == VOCABULARY_MODULE or name.startswith(VOCABULARY_MODULE + "."):
                hits.append(f"{rel}:{line} imports {name}")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        prose = _docstrings(tree)
        hits += [f"{rel}:{node.lineno} names it in a string: {node.value!r}"
                 for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)
                 and id(node) not in prose and VOCABULARY_STRING.search(node.value)]
    return hits


def test_nothing_consults_the_vocabulary_yet():
    """Phase 1: the table exists to be measured, not obeyed. The phase that
    wires it into a gate site removes this test in the same change."""
    hits = vocabulary_consumers(ROOT)
    assert not hits, hits


#: One module per form the guard reads, each in a module of its own.
CONSUMER_PROBES = {
    "runtime/protocols/p_absolute.py": "import runtime.security.vocabulary\n",
    "runtime/protocols/p_from.py": "from runtime.security.vocabulary import CANONICAL\n",
    "runtime/protocols/p_name.py": "from runtime.security import vocabulary\n",
    "runtime/protocols/p_parenthesised.py": "from runtime.security import (\n    vocabulary,\n)\n",
    "runtime/protocols/p_parent_module.py": "from ..security.vocabulary import CANONICAL\n",
    "runtime/protocols/p_parent_name.py": "from ..security import vocabulary\n",
    "runtime/security/p_sibling.py": "from . import vocabulary\n",
    "runtime/protocols/p_deferred.py": "def f():\n    from runtime.security.vocabulary import READ\n    return READ\n",
    "runtime/protocols/p_importlib.py": "import importlib\nm = importlib.import_module('runtime.security.vocabulary')\n",
    "runtime/protocols/p_split.py": "import importlib\nm = importlib.import_module('runtime.security' + '.vocabulary')\n",
    "runtime/protocols/p_attribute.py": "import runtime\nT = runtime.security.vocabulary.CANONICAL\n",
    "runtime/protocols/p_getattr.py": "import runtime.security as s\nv = getattr(s, 'vocab' 'ulary')\n",
    "runtime/protocols/p_rebound.py": "import runtime.security as s\nx = s\nT = x.vocabulary.CANONICAL\n",
    "runtime/protocols/p_aliased_call.py": ("from importlib import import_module as im\n"
                                            "m = im('runtime.security.vocabulary')\n"),
    "runtime/protocols/p_resolve_name.py": "import pkgutil\nm = pkgutil.resolve_name('runtime.security:vocabulary')\n",
    "runtime/protocols/p_resolve_split.py": "import pkgutil\nm = pkgutil.resolve_name('runtime.security' + ':vocabulary')\n",
    "gateway/p_elsewhere.py": "from runtime.security.vocabulary import CANONICAL\n",
    "scripts/p_script.py": "from runtime.security.vocabulary import CANONICAL\n",
}


def test_the_guard_catches_each_form_it_reads(tmp_path):
    """The guard is only worth what it catches: each probe is found, and a
    module that merely talks about a status vocabulary is not. (A bare
    "vocabulary" string literal does count, because that is how a split import
    would spell the module.)"""
    (tmp_path / "runtime" / "protocols").mkdir(parents=True)
    (tmp_path / "runtime" / "protocols" / "talks.py").write_text(
        '"""Not runtime/security/vocabulary.py: the refusal vocabulary."""\n'
        'NOTE = "the status vocabulary"\nKEY = "vocabulary_size"\n', encoding="utf-8")
    assert vocabulary_consumers(tmp_path) == []
    for rel, source in CONSUMER_PROBES.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(source, encoding="utf-8")
    caught = {hit.split(":")[0] for hit in vocabulary_consumers(tmp_path)}
    assert caught == set(CONSUMER_PROBES), sorted(set(CONSUMER_PROBES) - caught)


_BOOT = r"""
import asyncio, json, sys
sys.path.insert(0, "tests")
from aiohttp.test_utils import TestClient, TestServer
from gateway.server import GatewayServer
from test_route_sweep import SWEEP_CONFIG
from runtime.protocols.integration import ProtocolStack

async def main():
    server = GatewayServer({**SWEEP_CONFIG, "memory_dir": sys.argv[1],
                            "database": {"path": sys.argv[1] + "/a.db"},
                            "engines": {"evidence": {"mode": "shadow"}}})
    async with TestClient(TestServer(server.create_app())) as client:
        await client.get("/health")
        stack = ProtocolStack({}, "neo")
        await stack.pre_action("platform_action", {"action": "transfer_stablecoin", "params": {}},
                               {"agent": "neo", "memory_scope": "conv:boot"})

asyncio.run(main())
print(json.dumps("runtime.security.vocabulary" in sys.modules))
"""


def test_a_booted_gateway_never_loads_the_vocabulary(tmp_path):
    """The run-time half: a gateway booted in shadow mode, answering a request
    and gating a state-modifying chat action, has not imported the module —
    which no reading of the source can promise about an import built at run
    time."""
    proc = subprocess.run(
        [sys.executable, "-c", _BOOT, str(tmp_path)], cwd=ROOT, capture_output=True, text=True,
        timeout=180, env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"})
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert json.loads(proc.stdout.strip().splitlines()[-1]) is False


# ── the numerators: need the security core ───────────────────────────────────

def test_the_numerators_are_counts_within_their_denominators():
    measured = measure(classifier())
    assert {k: measured[k] for k in MEASURED} == MEASURED
    for numerator, denominator in NUMERATORS.items():
        assert 0 <= measured[numerator] <= measured[denominator], numerator


def test_the_numerators_match_the_pin_kept_beside_the_core():
    """A silent change to the core's side of the gap is a failure here — where
    the core is installed and a pin has been written beside it."""
    classified = classifier()
    pins = os.environ.get(PINS_ENV, "").strip()
    if not pins:
        pytest.skip(f"the numerators are not pinned in this repository; set {PINS_ENV} "
                    "to a JSON file of them kept beside the security core")
    pinned = json.loads(Path(pins).read_text(encoding="utf-8"))
    measured = measure(classified)
    assert {k: measured[k] for k in NUMERATORS} == {k: pinned.get(k) for k in NUMERATORS}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=PHASE_4)
def test_every_state_modifying_action_reaches_the_gate_classified():
    classified = classifier()
    missing = [n for n in sorted(sd._STATE_MODIFYING_ACTIONS) if not classified(react_label(n))]
    assert not missing, f"{len(missing)} of {len(sd._STATE_MODIFYING_ACTIONS)} pass through unclassified"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=PHASE_4)
def test_every_state_modifying_funnel_pair_reaches_the_gate_classified():
    classified = classifier()
    pairs = funnel_state_modifying_pairs()
    missing = [p for p in pairs if not classified(funnel_label(*p))]
    assert not missing, f"{len(missing)} of {len(pairs)} pass through unclassified"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=PHASE_4)
def test_every_state_modifying_verb_of_the_vocabulary_is_classified():
    classified = classifier()
    verbs = sorted({CANONICAL[n] for n in sd._STATE_MODIFYING_ACTIONS})
    missing = [v for v in verbs if not classified(v)]
    assert not missing, f"{len(missing)} of {len(verbs)} verbs unclassified"
