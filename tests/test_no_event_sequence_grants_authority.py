"""The three constitutional negatives of the engines program (Phase 1: written down, two failing).

The program's constitution: deterministic code owns facts, authorization and
the safety invariants are decided by the layers that own them, and a judgment
may advise but never permit. Three properties say what that forbids. They are
in the suite from Phase 1 so that no later phase can close while its property
is still broken; two of them ARE broken today, and are written as
``xfail(strict=True, raises=AssertionError)`` naming the phase that must flip
them — strict, so the day one starts passing it fails loudly until the marker
comes off, and held to an assertion, so a test that breaks before its
assertion (an import that moved, a keyword that was renamed) fails instead of
counting as the expected failure.

(a) Advice can only add caution. For every action in dataset 1 and every
    GateScores vector supplied as advice — the whole type, 4^6 x 3 vectors —
    the URF outcome with the advice is never less cautious than the outcome
    without it, on the order ABORT < DEFER < ASK < PROBE < EXECUTE.
    FAILS TODAY: ``URFReasoningLoop._resolve_scores`` takes a supplied vector
    instead of the loop's own, so advice of R=0 turns the approval gate's ASK
    on a high-value transfer into EXECUTE. Nothing supplies advice on a live
    path yet, which is why the hole is latent rather than open. Phase 5.

(b) A workflow cannot certify its own success. A service that says it settled,
    with no receipt and no other evidence, must not produce the durable record
    that it happened. FAILS TODAY: ``_record_verdict`` reads the service's own
    dict and the dispatcher attests it. Phase 3 (under the evidence engine's
    enforce mode; the structural half — the only writer of a verified verdict
    is the evidence engine — lands with that engine).

(c) Evidence never schedules or authorizes. The evidence engine exports
    no public name containing one of the word stems FORBIDDEN_NAME lists for
    queuing, scheduling, retrying, dispatching, executing, allowing, denying,
    approving, granting, permitting and authorizing — in each inflection the
    stems spell out (scheduler, retries, retrier, denial, permission,
    authorization, authz, and the rest listed there) — and
    imports none of the modules FORBIDDEN_MODULE names as able to dispatch,
    schedule, sign, send or decide. It does not exist yet, so the check over
    it is skipped; the check itself runs now, against a probe package that
    breaks it once in each form listed below, so it is known to catch each of
    those forms the moment ``runtime/evidence/`` exists. It reads source, it
    does not run it. What it reads:

    * the names a module binds at module level — by ``def``, ``class``, an
      assignment of any shape (plain, annotated, augmented, tuple or starred,
      a ``for`` or ``with`` target, a walrus, an ``except ... as``, a
      ``match`` capture), an import under any alias, a ``global`` declaration
      in a function, or an ``__all__`` entry, whether assigned, extended,
      appended or added to — inside module-level ``if``/``try``/``for``/
      ``while``/``with``/``match`` blocks too; the public names every class
      in it defines, nested classes included; and a name it puts on an object
      the module binds or imports, by assignment or by ``setattr`` (or
      ``__setattr__``) with a literal name (``api.authorize = ...``,
      ``Engine.retry = ...``, ``setattr(Engine, 'grant', f)``);
    * every module it imports, anywhere in the file: ``import`` and
      ``from ... import`` (relative ones resolved); ``import_module``,
      ``__import__`` (with its ``fromlist``) and ``pkgutil.resolve_name``
      with a literal name, positional or keyword, under their own names or
      an alias ``from ... import`` gives them; and a module reached as an
      attribute or a literal ``getattr`` of a name an import bound, or of a
      name a plain assignment re-bound to one (``import runtime`` then
      ``runtime.blockchain...``, or ``r = runtime`` then ``r.blockchain...``);
    * as an offence in itself, because what it binds or reaches cannot be
      read: a star import; ``import_module``, ``__import__`` or
      ``resolve_name`` with a name built at run time, a relative
      ``__import__``, or any of the three handed on rather than called; a
      module an ``import`` statement bound, used as anything but the root of
      an attribute or of a ``getattr``/``hasattr`` with a literal name (passed
      to a call, re-bound, stored); a ``getattr`` with a name built at run
      time on an imported module; ``sys.modules`` under any alias;
      ``globals()``, a bare ``vars()`` or ``locals()``, and ``vars()`` of an
      imported module or of a name the module binds; ``__builtins__``;
      ``setattr``/``delattr`` (or ``__setattr__``/``__delattr__``, called
      either way) on an imported module, or with a name built at run time on a
      name the module binds; the ``__dict__`` of an imported module or of a
      name the module binds; an ``__all__`` entry that is not a string
      literal; ``type()`` with three arguments; a module-level ``__getattr__``
      or ``__dir__``; ``exec``/``eval``/``compile``; and the
      ``importlib``/``runpy`` loaders that run a module from a spec or a path.

    That list is what the check reads, not every way Python can bind a name
    or reach a module. It does not follow a module imported by
    ``from ... import`` and then handed to a call or kept in a container, a
    name put on an object the module neither binds nor imports, a class or
    namespace built by a call other than ``type()`` (``namedtuple``,
    ``Enum``, ``make_dataclass``), or an object handed in from outside the
    package; and it cannot judge a capability under a name that says nothing
    — a function called ``settle`` that sends, a scheduling primitive of the
    standard library such as ``asyncio``'s ``call_later`` or ``threading``'s
    ``Timer``. That half of the property belongs to review, and to the phase
    that builds the engine.
"""

from __future__ import annotations

import ast
import itertools
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "tests")

from runtime.protocols import urf  # noqa: E402
from runtime.protocols.urf import GateScores, Outcome, TimeSensitivity, URFReasoningLoop  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

#: Most cautious first.
CAUTION = {Outcome.ABORT: 0, Outcome.DEFER: 1, Outcome.ASK: 2, Outcome.PROBE: 3, Outcome.EXECUTE: 4}


@pytest.fixture(autouse=True)
def _no_decision_sink():
    previous = urf.set_decision_sink(None)
    yield
    urf.set_decision_sink(previous)


def every_advice_vector():
    """The whole GateScores type: six gates of 0..3 and three time sensitivities."""
    for c, f, r, u, v, ce in itertools.product(range(4), repeat=6):
        for t in TimeSensitivity:
            yield GateScores(clarity=c, feasibility=f, risk=r, uncertainty=u, value=v,
                             capability_expansion=ce, time_sensitivity=t)


def dataset_1_classes():
    """Dataset 1 reduced to its classes under the loop: two actions whose
    heuristic scores, hard-rule violations, state-change reading and approval
    flags all agree are resolved identically for every supplied vector, so one
    representative per class makes the check exhaustive over the corpus.
    Classes with no hard rule and an outcome below EXECUTE come first — the
    ones advice could loosen."""
    from test_engines_baseline import corpus
    loop = URFReasoningLoop({})
    classes: dict[tuple, tuple] = {}
    for cell, name, action, ctx in corpus():
        scores = loop._resolve_scores(action, ctx, None)
        violations = tuple(loop._check_hard_rules(action, ctx, scores))
        key = (tuple(scores.to_dict().items()), violations, loop._is_state_change(action),
               loop._approved(action, ctx))
        classes.setdefault(key, (cell, name, action, ctx))
    return sorted(classes.values(), key=lambda c: (
        bool(loop._check_hard_rules(c[2], c[3], loop._resolve_scores(c[2], c[3], None))),
        CAUTION[loop.decide(c[2], c[3]).outcome]))


def test_dataset_1_has_the_classes_it_is_measured_to_have():
    classes = dataset_1_classes()
    assert len(classes) >= 5
    outcomes = {URFReasoningLoop({}).decide(a, c).outcome for _, _, a, c in classes}
    assert outcomes == {Outcome.EXECUTE, Outcome.ASK, Outcome.ABORT}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Phase 5 (Operator, advisory): urf.py _resolve_scores trusts a supplied vector "
    "outright; the phase merges advice caution-only against the fact-derived vector"))
def test_operator_output_never_moves_an_outcome_toward_execute():
    loop = URFReasoningLoop({})
    for cell, name, action, ctx in dataset_1_classes():
        facts = loop.decide(action, ctx).outcome
        for advice in every_advice_vector():
            advised = loop.decide(action, ctx, scores=advice).outcome
            assert CAUTION[advised] <= CAUTION[facts], (
                f"{cell} {name}: advice {advice.compact()} moved {facts.value} -> {advised.value}")


def test_baseline_advice_enters_by_all_three_doors_today():
    """A MEASURED BASELINE, not a requirement.

    What it pins: today ``_resolve_scores`` takes a score vector from three
    doors alike — the ``scores=`` keyword, ``urf_scores`` on the action and
    ``urf_scores`` in the context — in place of the loop's own vector, so a
    50,000 transfer, which the facts alone resolve to ASK, resolves to
    EXECUTE by every door once advice of R=0 arrives. That is the hole (a)
    names, seen from the side of how advice gets in. No live path hands the
    loop a vector by any door: the ReAct seam builds the action with fixed
    keys and the chat context carries no ``urf_scores``.

    Nothing here is required. Three open doors are the measurement, not the
    design, and a change that closes the two implicit ones ahead of Phase 5
    is a change to write down here, not a regression. Phase 5 flips this
    test: once advice is merged caution-only, every door gives ASK on this
    vector — or a door is closed and gives ASK for that reason — and this
    baseline is rewritten to the new figure, the way tests/baseline/ files
    are. Until then it fails only if a door or the outcome changes without
    being written down.
    """
    loop = URFReasoningLoop({})
    action = {"action_type": "transfer_stablecoin", "parameters": {"amount": 50000}}
    advice = {"C": 3, "F": 3, "R": 0, "U": 0, "V": 3, "CE": 3, "T": "high"}
    facts = loop.decide(dict(action), {}).outcome
    by_kwarg = loop.decide(dict(action), {}, scores=dict(advice)).outcome
    by_action = loop.decide({**action, "urf_scores": dict(advice)}, {}).outcome
    by_context = loop.decide(dict(action), {"urf_scores": dict(advice)}).outcome
    assert facts is Outcome.ASK
    assert (by_kwarg, by_action, by_context) == (Outcome.EXECUTE,) * 3


@pytest.mark.parametrize("result", [
    {"status": "success", "settled": True},
    {"status": "success", "settled": True, "value_moved": True, "tx_hash": "0x" + "33" * 32},
    {"status": "success"},
], ids=["settled-flag", "settled-with-hash", "plain-success"])
@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Phase 3 (Evidence/Outcome): service_dispatcher._record_verdict answers from the "
    "worker's own dict and the dispatcher attests it; under the evidence engine's enforce "
    "mode a worker's statement yields PENDING and nothing is attested before evidence"))
async def test_a_workflow_cannot_write_its_own_verified(result):
    from test_evidence_shadow_matches_legacy_verdict import (
        ACTOR, PARAMS, STATE_ACTION, _dispatcher,
    )
    calls: list = []
    await _dispatcher(result, calls).execute(STATE_ACTION, params=dict(PARAMS),
                                             caller_identity=ACTOR)
    attested = [c for c in calls if c[0] == "attest"]
    assert not attested, f"the worker's own {result} was attested as done"


#: A public name the evidence package may not export: the packet's seven
#: (14 §1.3: enqueue|schedule|retry|dispatch|allow|deny|authorize) and four
#: more words for the same acts (execute, approve, grant, permit), matched as
#: word stems so that every inflection counts — scheduler, retries, retrier,
#: retrial, retriable, denial, denier, deniable, permission, permissive,
#: permissible, authorization, authz, queuing, executor, approval, grantor,
#: allowance — and spelled so that a name that only shares letters with one
#: and says nothing of the act (retrieve, denominator, permutation, author,
#: quorum, approach) is left alone. SAYS_THE_ACT and SAYS_NOTHING_OF_IT below
#: hold both edges. A name that means one of the acts without containing a
#: stem is what the module docstring leaves to review.
FORBIDDEN_NAME = re.compile(
    r"queu|schedul|retry|retri(?:e[sdr]|a[lb])|dispatch|execut|allow"
    r"|den(?:y|ie[sdr]|ia[lb])|approv|grant|permi(?:t|ss)|authori[sz]|authz", re.IGNORECASE)
#: A module the evidence package may not import (packet ES-EV-05: no
#: dispatcher, registry, signer or scheduler), matched on its dotted path:
#: any part named for a dispatcher, a registry, a signer, a scheduler, a queue
#: or an executor; the stock scheduling, queueing and signing libraries; and the
#: platform's own packages that dispatch, sign, send or decide — the gateway,
#: ``runtime.blockchain`` (whose package exports the chain manager that signs
#: and sends, so importing any module in it reaches that), the security gate
#: and its seam, the access policy, the ReAct loop, the framework's deciders,
#: the security core and the Oracle Server.
FORBIDDEN_MODULE = re.compile(
    r"(^|\.)\w*(dispatch|registry|signer|signing|schedul|queue|executor)\w*($|\.)"
    r"|(^|\.)(sched|celery|apscheduler|rq|dramatiq|huey|eth_account|web3)($|\.)"
    r"|^(gateway|runtime\.blockchain|runtime\.security|runtime\.access_policy|runtime\.react_loop"
    r"|runtime\.protocols\.(urf|rexhepi_gate|integration)|morpheus_security|oracle_server)($|\.)",
    re.IGNORECASE)
#: Calls that run or load code the check cannot read.
UNREADABLE_CALLS = {"exec", "eval", "compile", "exec_module", "load_module",
                    "spec_from_file_location", "spec_from_loader", "module_from_spec",
                    "run_module", "run_path"}
#: The calls that import a module by its name, and the modules that export them.
IMPORT_CALLS = {"import_module", "__import__", "resolve_name"}
IMPORT_SOURCES = {"importlib", "builtins", "pkgutil"}
#: The calls that put an attribute on, or take one off, the object they are handed.
ATTRIBUTE_WRITES = {"setattr", "delattr", "__setattr__", "__delattr__"}


def module_name(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _package_of(path: Path, root: Path) -> str:
    module = module_name(path, root)
    return module if path.name == "__init__.py" else module.rpartition(".")[0]


def _resolve(name: str, package: str) -> str:
    """*name* as an absolute module path; a leading dot is relative to *package*."""
    level = len(name) - len(name.lstrip("."))
    if not level:
        return name
    base = package.split(".") if package else []
    base = base[:len(base) - (level - 1)]
    return ".".join(p for p in (*base, name[level:]) if p)


def _called(node: ast.Call) -> str:
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""


def _literal(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def import_callees(tree: ast.AST) -> dict[str, str]:
    """Each name a call in *tree* imports a module by, to the import call it
    is: IMPORT_CALLS under their own names, and the alias a
    ``from importlib import import_module as im`` (or ``builtins``'s
    ``__import__``, or ``pkgutil``'s ``resolve_name``) gives one."""
    callees = {name: name for name in IMPORT_CALLS}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in IMPORT_SOURCES and not node.level:
            callees.update({a.asname: a.name for a in node.names if a.name in IMPORT_CALLS and a.asname})
    return callees


def _argument(node: ast.Call, position: int, keyword: str):
    if len(node.args) > position:
        return node.args[position]
    return next((k.value for k in node.keywords if k.arg == keyword), None)


def import_call_targets(node: ast.Call, callees: dict[str, str] | None = None
                        ) -> tuple[bool, list[str] | None]:
    """For a call that imports by name (see import_callees): (is one, the
    module paths it names, or None when they are built at run time).
    ``import_module`` resolves a relative name against a literal ``package``;
    ``__import__`` names its ``fromlist`` entries as submodules and is
    unreadable when relative; ``resolve_name`` reads ``pkg.mod:attr`` as the
    path it spells."""
    kind = (callees or {name: name for name in IMPORT_CALLS}).get(_called(node))
    if kind is None:
        return False, None
    name = _literal(_argument(node, 0, "name"))
    if name is None:
        return True, None
    if kind == "resolve_name":
        return True, [name.replace(":", ".")]
    if kind == "__import__":
        level = _argument(node, 4, "level")
        if level is not None and not (isinstance(level, ast.Constant) and level.value == 0):
            return True, None
        fromlist = _argument(node, 3, "fromlist")
        if fromlist is None or (isinstance(fromlist, ast.Constant) and fromlist.value is None):
            return True, [name]
        if not isinstance(fromlist, (ast.List, ast.Tuple)) or any(_literal(e) is None for e in fromlist.elts):
            return True, None
        return True, [name, *(f"{name}.{_literal(e)}" for e in fromlist.elts)]
    if name.startswith("."):
        package = _argument(node, 1, "package")
        base = _literal(package) if package is not None else None
        return True, ([_resolve(name, base)] if base is not None else None)
    return True, [name]


def _dotted(node: ast.AST) -> tuple[str, list[str]] | None:
    """``a.b.c`` as ("a", ["b", "c"]); None for anything not a plain chain."""
    attrs = []
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    return (node.id, attrs[::-1]) if isinstance(node, ast.Name) else None


def _root(node: ast.AST) -> str | None:
    chain = _dotted(node)
    return chain[0] if chain else None


def _assignments(tree: ast.AST) -> list[tuple[ast.AST, ast.AST]]:
    """(target, value) for every plain, annotated or walrus assignment, a
    tuple assigned from a tuple of the same length taken element by element."""
    pairs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            pairs += [(t, node.value) for t in node.targets]
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            pairs.append((node.target, node.value))
    flat = []
    for target, value in pairs:
        if (isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List))
                and len(target.elts) == len(value.elts)):
            flat += list(zip(target.elts, value.elts))
        else:
            flat.append((target, value))
    return flat


def _import_bindings(tree: ast.AST, package: str) -> dict[str, set[str]]:
    """Each local name an import binds, to the module paths it stands for —
    and each name a plain assignment re-binds to one of those, or to an
    attribute reached from one (``r = runtime``, ``b = runtime.blockchain``)."""
    bound: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                bound.setdefault(local, set()).add(alias.name if alias.asname else local)
        elif isinstance(node, ast.ImportFrom):
            source = _resolve("." * node.level + (node.module or ""), package)
            for alias in node.names:
                if alias.name != "*":
                    bound.setdefault(alias.asname or alias.name, set()).add(
                        f"{source}.{alias.name}" if source else alias.name)
    pairs = [(t.id, _dotted(v)) for t, v in _assignments(tree) if isinstance(t, ast.Name) and _dotted(v)]
    for _ in range(len(pairs)):  # a chain of re-bindings is no longer than the assignments
        grew = False
        for name, (source, attrs) in pairs:
            paths = {".".join((m, *attrs)) for m in bound.get(source, ())}
            if not paths <= bound.get(name, set()):
                bound.setdefault(name, set()).update(paths)
                grew = True
        if not grew:
            break
    return bound


def _module_names(tree: ast.AST) -> set[str]:
    """The names an ``import`` statement binds: each one is a module."""
    return {alias.asname or alias.name.split(".")[0]
            for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    return {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def imports_of(path: Path, root: Path) -> list[tuple[int, str]]:
    """Every module path *path* imports or reaches, anywhere in the file:
    ``import a.b`` gives ``a.b``; ``from a import b`` gives ``a`` and ``a.b``,
    a relative ``from`` resolved against the file's own package; a call that
    imports by a literal name (import_call_targets) gives what it names; and
    an attribute chain or a literal ``getattr`` rooted at a name an import
    bound, or that an assignment re-bound to one, gives the dotted path it
    spells (``import runtime`` then ``runtime.blockchain.web3_manager`` gives
    that path)."""
    package = _package_of(path, root)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bound = _import_bindings(tree, package)
    callees = import_callees(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            source = _resolve("." * node.level + (node.module or ""), package)
            found.append((node.lineno, source))
            found += [(node.lineno, f"{source}.{alias.name}" if source else alias.name)
                      for alias in node.names if alias.name != "*"]
        elif isinstance(node, ast.Call):
            is_import, targets = import_call_targets(node, callees)
            if is_import:
                found += [(node.lineno, target) for target in targets or ()]
            elif (_called(node) == "getattr" and len(node.args) >= 2
                  and _root(node.args[0]) in bound and _literal(node.args[1])):
                source, attrs = _dotted(node.args[0])
                found += [(node.lineno, ".".join((m, *attrs, _literal(node.args[1]))))
                          for m in bound[source]]
        elif isinstance(node, ast.Attribute):
            chain = _dotted(node)
            if chain and chain[0] in bound:
                found += [(node.lineno, ".".join((m, *chain[1]))) for m in bound[chain[0]]]
    return found


def _module_level_names(path: Path) -> set[str]:
    return {name for _, name in exported_names(path) if "." not in name and name != "*"}


def _attribute_write(node: ast.Call, owners: set[str]) -> tuple[ast.AST | None, ast.AST | None] | None:
    """For a call in ATTRIBUTE_WRITES: (the object it writes to, the node that
    names the attribute). ``X.__setattr__(name, v)`` writes to X when X is a
    name in *owners*; ``setattr(X, name, v)`` and ``object.__setattr__(X,
    name, v)`` write to their first argument."""
    if _called(node) not in ATTRIBUTE_WRITES:
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr.startswith("__") and _root(func.value) in owners:
        return func.value, (node.args[0] if node.args else None)
    return (node.args[0] if node.args else None), (node.args[1] if len(node.args) > 1 else None)


def _all_is_literal(node: ast.AST | None) -> bool:
    return (isinstance(node, (ast.List, ast.Tuple))
            and all(_literal(e) is not None for e in node.elts))


def _unreadable_all(tree: ast.AST, parents: dict[int, ast.AST]) -> list[tuple[int, str]]:
    """Each place ``__all__`` is given an entry that is not a string literal."""
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Name) and node.id == "__all__"):
            continue
        parent = parents.get(id(node))
        if isinstance(node.ctx, ast.Store):
            value = parent.value if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.AugAssign)) else None
            if value is not None and _all_is_literal(value):
                continue
            if isinstance(parent, ast.AnnAssign) and value is None:
                continue
            found.append((node.lineno, "__all__ is given a value that is not a list of string literals"))
        elif isinstance(parent, ast.Subscript) and not isinstance(parent.ctx, ast.Load):
            found.append((node.lineno, "__all__ is written by index"))
        elif isinstance(parent, ast.Attribute) and parent.attr in (
                "append", "extend", "insert", "__iadd__", "__setitem__"):
            call = parents.get(id(parent))
            if not (isinstance(call, ast.Call) and call.func is parent):
                found.append((node.lineno, f"__all__.{parent.attr} is handed on"))
                continue
            args = call.args[1:] if parent.attr in ("insert", "__setitem__") else call.args
            if call.keywords or not all(_literal(a) is not None or _all_is_literal(a) for a in args):
                found.append((node.lineno, f"__all__.{parent.attr} with an entry that is not a string literal"))
    return found


def unreadable(path: Path, root: Path) -> list[tuple[int, str]]:
    """The places *path* binds a name or reaches a module in one of the forms
    the module docstring lists as offences in themselves."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bound = _import_bindings(tree, _package_of(path, root))
    modules = _module_names(tree)
    owners = set(bound) | _module_level_names(path)
    callees = import_callees(tree)
    parents = _parents(tree)
    called_funcs = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}

    def reached(name: ast.Name) -> bool:
        """The name is only the root of an attribute or a literal getattr."""
        parent = parents.get(id(name))
        if isinstance(parent, ast.Attribute) and parent.value is name:
            return True
        return (isinstance(parent, ast.Call) and _called(parent) in ("getattr", "hasattr")
                and parent.args[:1] == [name] and len(parent.args) >= 2
                and _literal(parent.args[1]) is not None)

    found: list[tuple[int, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in ("__getattr__", "__dir__"):
            found.append((node.lineno, f"a module-level {node.name} exports names at run time"))
    for line, name in imports_of(path, root):
        if name == "sys.modules" or name.startswith("sys.modules."):
            found.append((line, "sys.modules reaches a module by a run-time name"))
        elif name.endswith(".__dict__") or ".__dict__." in name:
            found.append((line, f"{name} binds or reads a module's names at run time"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            found.append((node.lineno, "star import: its exports cannot be checked"))
        elif isinstance(node, ast.Call):
            called = _called(node)
            is_import, targets = import_call_targets(node, callees)
            write = _attribute_write(node, owners)
            if is_import and targets is None:
                found.append((node.lineno, f"{called} with a name built at run time"))
            elif write is not None:
                target, attribute = write
                owner = _root(target) if target is not None else None
                if owner in bound:
                    found.append((node.lineno, f"{called} on the imported module {owner}"))
                elif owner in owners and _literal(attribute) is None:
                    found.append((node.lineno, f"{called} on {owner} with a name built at run time"))
            elif called == "globals" and isinstance(node.func, ast.Name):
                found.append((node.lineno, "globals() binds or reads names at run time"))
            elif called in ("vars", "locals") and isinstance(node.func, ast.Name) and not node.args:
                found.append((node.lineno, f"{called}() binds or reads names at run time"))
            elif called == "vars" and isinstance(node.func, ast.Name) and _root(node.args[0]) in owners:
                found.append((node.lineno, f"vars({_root(node.args[0])}) binds or reads its names at run time"))
            elif (called == "getattr" and isinstance(node.func, ast.Name) and len(node.args) >= 2
                  and _root(node.args[0]) in bound and _literal(node.args[1]) is None):
                found.append((node.lineno, f"getattr on the imported {_root(node.args[0])} "
                                           "with a name built at run time"))
            elif called == "type" and isinstance(node.func, ast.Name) and len(node.args) + len(node.keywords) >= 3:
                found.append((node.lineno, "type() with three arguments builds a class at run time"))
            elif called in UNREADABLE_CALLS:
                found.append((node.lineno, f"{called} runs or loads code the check cannot read"))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id == "__builtins__":
                found.append((node.lineno, "__builtins__ reaches any builtin by a run-time name"))
            elif node.id in modules and not reached(node):
                found.append((node.lineno, f"the imported module {node.id} is handed on: "
                                           "what is reached through it cannot be read"))
            elif node.id in callees and id(node) not in called_funcs:
                found.append((node.lineno, f"{node.id} is handed on: what it imports cannot be read"))
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            if node.attr in IMPORT_CALLS and id(node) not in called_funcs:
                found.append((node.lineno, f"{node.attr} is handed on: what it imports cannot be read"))
            elif node.attr == "__dict__" and _root(node.value) in owners - set(bound):
                found.append((node.lineno, f"{_root(node.value)}.__dict__ binds or reads names at run time"))
    return found + _unreadable_all(tree, parents)


def names_bound_on_objects(path: Path, root: Path) -> list[tuple[int, str]]:
    """Each attribute *path* puts on, or takes off, an object it imported or
    binds at module level — by assignment or ``del`` (``from . import api``
    then ``api.authorize = ...``; ``Engine.retry = ...``) or by a write call
    with a literal name (``setattr(Engine, 'grant', f)``) — as
    ``module.name`` for an imported module and ``Name.name`` otherwise: a name
    that object then exports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bound = _import_bindings(tree, _package_of(path, root))
    owners = set(bound) | _module_level_names(path)

    def spelled(line: int, chain: tuple[str, list[str]], *attrs: str) -> list[tuple[int, str]]:
        source, rest = chain
        roots = sorted(bound[source]) if source in bound else [source]
        return [(line, ".".join((r, *rest, *attrs))) for r in roots]

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            chain = _dotted(node)
            if chain and chain[0] in owners:
                found += spelled(node.lineno, chain)
        elif isinstance(node, ast.Call):
            write = _attribute_write(node, owners)
            if write is not None and write[0] is not None and _literal(write[1]) is not None:
                chain = _dotted(write[0])
                if chain and chain[0] in owners:
                    found += spelled(node.lineno, chain, _literal(write[1]))
    return found


def _bound(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for elt in target.elts for n in _bound(elt)]
    if isinstance(target, ast.Starred):
        return _bound(target.value)
    return []


def _captures(pattern: ast.AST) -> list[str]:
    """The names a ``match`` pattern binds."""
    names = []
    for node in ast.walk(pattern):
        if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.append(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.append(node.rest)
    return names


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _walrus_targets(node: ast.AST) -> list[tuple[int, str]]:
    """Walrus targets in *node* that bind in its own scope — not inside a
    function, class or lambda nested in it."""
    found, stack = [], [node]
    while stack:
        current = stack.pop()
        if isinstance(current, ast.NamedExpr):
            found.append((current.lineno, current.target.id))
        stack += [c for c in ast.iter_child_nodes(current) if not isinstance(c, _SCOPES)]
    return found


def _all_entries(node: ast.AST) -> list[str]:
    """The string literals an ``__all__`` value lists."""
    return [e.value for e in getattr(node, "elts", []) if _literal(e) is not None]


def exported_names(path: Path) -> list[tuple[int, str]]:
    """Every name the module binds at module level, in every form the module
    docstring lists (walking into module-level blocks, not into functions),
    the ``__all__`` entries however they are added, the names functions declare
    ``global``, and, as ``Class.member``, the names every class defines in its
    own body (nested classes included). A star import is reported as ``*``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []

    def is_all(node) -> bool:
        return isinstance(node, ast.Name) and node.id == "__all__"

    def members(cls: ast.ClassDef, prefix: str):
        for node in cls.body:
            names = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names = [node.name]
            elif isinstance(node, ast.Assign):
                names = [n for t in node.targets for n in _bound(t)]
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                names = _bound(node.target)
            found.extend((node.lineno, f"{prefix}.{n}") for n in names)
            if isinstance(node, ast.ClassDef):
                members(node, f"{prefix}.{node.name}")

    def visit(statements):
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.append((node.lineno, node.name))
                if isinstance(node, ast.ClassDef):
                    members(node, node.name)
                continue
            if isinstance(node, ast.Assign):
                found.extend((node.lineno, n) for t in node.targets for n in _bound(t))
                if any(is_all(t) for t in node.targets):
                    found.extend((node.lineno, e) for e in _all_entries(node.value))
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                found.extend((node.lineno, n) for n in _bound(node.target))
                if is_all(node.target) and node.value is not None:
                    found.extend((node.lineno, e) for e in _all_entries(node.value))
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                found.extend((node.lineno, n) for n in _bound(node.target))
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                found.extend((node.lineno, n) for item in node.items if item.optional_vars
                             for n in _bound(item.optional_vars))
            elif isinstance(node, ast.Import):
                found.extend((node.lineno, a.asname or a.name.split(".")[0]) for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                found.extend((node.lineno, a.asname or a.name) for a in node.names)
            elif isinstance(node, ast.Match):
                found.extend((node.lineno, n) for case in node.cases for n in _captures(case.pattern))
            elif (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                  and isinstance(node.value.func, ast.Attribute) and is_all(node.value.func.value)):
                # __all__.append("x") / .extend([...]) / .insert(i, "x")
                for arg in node.value.args:
                    found.extend((node.lineno, e) for e in ([_literal(arg)] if _literal(arg) else _all_entries(arg)))
            # a walrus anywhere in the statement's own expressions binds here
            if not isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With,
                                     ast.AsyncWith, ast.Try, ast.Match)):
                found.extend(_walrus_targets(node))
            else:
                for field in ("test", "iter", "items", "subject"):
                    value = getattr(node, field, None)
                    for part in (value if isinstance(value, list) else [value]):
                        if part is not None:
                            found.extend(_walrus_targets(part))
            for handler in getattr(node, "handlers", []) or []:
                if handler.name:
                    found.append((handler.lineno, handler.name))
                visit(handler.body)
            for block in ("body", "orelse", "finalbody"):
                inner = getattr(node, block, None)
                if isinstance(inner, list):
                    visit(inner)
            for case in getattr(node, "cases", []) or []:
                visit(case.body)

    visit(tree.body)
    found += [(node.lineno, name) for node in ast.walk(tree) if isinstance(node, ast.Global)
              for name in node.names]
    found += [(node.lineno, "*") for node in tree.body
              if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names)]
    return found


def authority_offences(package: Path, root: Path) -> list[str]:
    """What (c) forbids, in every module of *package*."""
    offences = []
    for path in sorted(package.rglob("*.py")):
        where = path.relative_to(root)
        for line, name in exported_names(path) + names_bound_on_objects(path, root):
            last = name.rsplit(".", 1)[-1]
            if name != "*" and not last.startswith("_") and FORBIDDEN_NAME.search(last):
                offences.append(f"{where}:{line} exports {name}")
        for line, name in imports_of(path, root):
            if FORBIDDEN_MODULE.search(name):
                offences.append(f"{where}:{line} imports {name}")
        offences += [f"{where}:{line} {what}" for line, what in unreadable(path, root)]
    return offences


def test_evidence_never_schedules_or_authorizes():
    package = ROOT / "runtime" / "evidence"
    if not package.is_dir():
        pytest.skip("runtime/evidence/ does not exist until Phase 3; "
                    "test_the_authority_check_binds_on_a_probe_package shows the check binds")
    offences = authority_offences(package, ROOT)
    assert not offences, offences


#: One module per form the check reads, each breaking (c) in that form alone.
PROBES = {
    # names bound at module level
    "defines.py": "def schedule_retry():\n    pass\n",
    "defines_class.py": "class Scheduler:\n    pass\n",
    "reexports.py": "from .worker import _impl as authorize\n",
    "import_alias.py": "import json as schedule\n",
    "annotated.py": "dispatch: object = None\n",
    "augmented.py": "retry = 0\nretry += 1\n",
    "unpacked.py": "allow, _x = 1, 2\n",
    "starred_target.py": "_a, *permitted = (1, 2, 3)\n",
    "for_target.py": "for authorize in (print,):\n    pass\n",
    "with_target.py": "import contextlib\nwith contextlib.nullcontext(print) as dispatch:\n    pass\n",
    "walrus.py": "(retry := print)\n",
    "walrus_in_test.py": "if (approve := print):\n    pass\n",
    "except_as.py": "try:\n    pass\nexcept Exception as deny:\n    pass\n",
    "match_capture.py": "match 1:\n    case grant:\n        pass\n",
    "conditional.py": "try:\n    from .worker import enqueue\nexcept ImportError:\n    pass\n",
    "while_block.py": "while False:\n    execute = print\n",
    "if_block.py": "if True:\n    schedule = print\n",
    "for_block.py": "for _ in ():\n    dispatch = print\n",
    "with_block.py": "import contextlib\nwith contextlib.nullcontext():\n    grant = print\n",
    "match_block.py": "match 1:\n    case _:\n        permit = print\n",
    "declared.py": "def f():\n    global retry_later\n    retry_later = 1\n",
    "listed.py": "__all__ = ['deny']\n",
    "listed_augmented.py": "__all__ = []\n__all__ += ['permit']\n",
    "listed_appended.py": "__all__ = []\n__all__.append('allow')\n",
    "listed_extended.py": "__all__ = []\n__all__.extend(['grant'])\n",
    # names a class defines
    "method_on_class.py": "class EvidenceEngine:\n    def authorize(self, run):\n        return True\n",
    "attribute_on_class.py": "class EvidenceEngine:\n    retry = staticmethod(print)\n",
    "nested_class.py": "class EvidenceEngine:\n    class Jobs:\n        def enqueue(self):\n            pass\n",
    # names put on an object the module binds
    "assigns_on_class.py": "class EvidenceEngine:\n    pass\nEvidenceEngine.authorize = print\n",
    "assigns_on_function.py": "def run():\n    pass\nrun.retry = print\n",
    "setattr_on_class.py": "class EvidenceEngine:\n    pass\nsetattr(EvidenceEngine, 'approve', print)\n",
    "dunder_setattr_on_class.py": ("class EvidenceEngine:\n    pass\n"
                                   "type.__setattr__(EvidenceEngine, 'dispatch', print)\n"),
    # the words, inflected, and their synonyms
    "authorization.py": "def authorization_for(run):\n    return 'yes'\n",
    "approve.py": "def approve(run):\n    return True\n",
    "grant.py": "def grant(run):\n    return True\n",
    "permit.py": "def permit(run):\n    return True\n",
    "execute.py": "def execute(action):\n    pass\n",
    "queue.py": "def queue_job(job):\n    pass\n",
    "denied.py": "DENIED = 'denied'\n",
    "retrier.py": "class Retrier:\n    pass\n",
    "denial.py": "def make_denial(run):\n    return None\n",
    "permission.py": "def issue_permission(run):\n    return True\n",
    "authz.py": "AUTHZ = None\n",
    "queuing.py": "def queuing(job):\n    pass\n",
    # imports
    "imports_dispatcher.py": "from ..blockchain.services import service_dispatcher as sd\n",
    "imports_registry.py": "def f():\n    import runtime.blockchain.registry\n",
    "imports_signer.py": "import eth_account\n",
    "imports_web3.py": "from runtime.blockchain.web3_manager import Web3Manager\n",
    "imports_services_pkg.py": "from runtime.blockchain import services\n",
    "imports_gate.py": "from runtime.security import get_morpheus_security\n",
    "imports_security_gate.py": "from gateway import security_gate\n",
    "imports_urf.py": "from runtime.protocols.urf import URFReasoningLoop\n",
    "imports_core.py": "import morpheus_security\n",
    "imports_oracle.py": "import oracle_server\n",
    "imports_scheduler.py": "import importlib\nm = importlib.import_module('apscheduler.schedulers')\n",
    "imports_kw.py": ("import importlib\n"
                      "m = importlib.import_module(name='runtime.blockchain.services.service_dispatcher')\n"),
    "imports_relative_kw.py": ("import importlib\n"
                               "m = importlib.import_module('.web3_manager', package='runtime.blockchain')\n"),
    "imports_dunder.py": "m = __import__('celery')\n",
    "imports_fromlist.py": "m = __import__('runtime', fromlist=['blockchain'])\n",
    "imports_aliased_call.py": "from importlib import import_module as im\nm = im('celery')\n",
    "imports_resolve_name.py": "import pkgutil\nm = pkgutil.resolve_name('runtime.blockchain:web3_manager')\n",
    "reaches_attribute.py": "import runtime\nW = runtime.blockchain.web3_manager.Web3Manager\n",
    "reaches_getattr.py": "import runtime\nB = getattr(runtime, 'blockchain')\n",
    "reaches_rebound.py": "from runtime import protocols\np = protocols\nU = p.urf\n",
    "imports_queue.py": "import queue\n",
    # forms that cannot be read
    "starred.py": "from .worker import *\n",
    "split_import.py": "import importlib\nm = importlib.import_module('runtime.blockchain.' + 'web3_manager')\n",
    "dunder_split.py": "m = __import__('cel' + 'ery')\n",
    "dunder_relative.py": "m = __import__('blockchain', None, None, ['web3_manager'], 2)\n",
    "resolve_name_split.py": "import pkgutil\nm = pkgutil.resolve_name('runtime.' + 'blockchain')\n",
    "import_function_handed_on.py": "import importlib\nim = importlib.import_module\n",
    "module_handed_on.py": ("import operator\nimport runtime\n"
                            "W = operator.attrgetter('blockchain.web3_manager')(runtime)\n"),
    "module_rebound.py": "import runtime\nr = runtime\n",
    "getattr_split.py": "import runtime\nB = getattr(runtime, 'block' + 'chain')\n",
    "sys_modules.py": "import sys\nD = sys.modules['runtime.blockchain.services.service_dispatcher']\n",
    "globals_set.py": "globals()['schedule'] = print\n",
    "vars_set.py": "vars()['schedule'] = print\n",
    "locals_set.py": "locals()['schedule'] = print\n",
    "setattr_module.py": "import runtime.evidence as me\nsetattr(me, 'authorize', print)\n",
    "object_setattr.py": "import runtime.evidence as me\nobject.__setattr__(me, 'x', print)\n",
    "method_setattr.py": "import runtime.evidence as me\nme.__setattr__('x', print)\n",
    "delattr_module.py": "import runtime.evidence as me\ndelattr(me, 'x')\n",
    "object_delattr.py": "import runtime.evidence as me\nobject.__delattr__(me, 'x')\n",
    "method_delattr.py": "import runtime.evidence as me\nme.__delattr__('x')\n",
    "setattr_split.py": "NAME = 'x'\nclass EvidenceEngine:\n    pass\nsetattr(EvidenceEngine, NAME, print)\n",
    "vars_of_module.py": "import runtime.evidence as me\nvars(me)['x'] = print\n",
    "vars_of_function.py": "def run():\n    pass\nvars(run)['x'] = print\n",
    "function_dict.py": "def run():\n    pass\nrun.__dict__['x'] = print\n",
    "builtins_mapping.py": "f = __builtins__['__import__']\n",
    "listed_split.py": "__all__ = ['de' + 'ny']\n",
    "listed_appended_split.py": "NAME = 'x'\n__all__ = []\n__all__.append(NAME)\n",
    "type_built_class.py": "X = type('X', (), {'x': print})\n",
    "module_dict.py": "import runtime.evidence as me\nme.__dict__['authorize'] = print\n",
    "aliased_sys.py": "import sys as s\nD = s.modules\n",
    "assigns_on_module.py": "from . import worker\nworker.authorize = print\n",
    "module_getattr.py": "def __getattr__(name):\n    return print\n",
    "module_dir.py": "def __dir__():\n    return ['x']\n",
    "exec_code.py": "exec('x = 1')\n",
    "eval_code.py": "x = eval('1')\n",
    "compile_code.py": "c = compile('x = 1', 'm', 'exec')\n",
    "spec_loader.py": ("import importlib.util\n"
                       "spec = importlib.util.spec_from_file_location('m', '/tmp/m.py')\n"),
    "spec_from_loader.py": ("import importlib.util\n"
                            "def load(loader):\n    return importlib.util.spec_from_loader('m', loader)\n"),
    "module_from_spec.py": ("import importlib.util\n"
                            "def load(spec):\n    return importlib.util.module_from_spec(spec)\n"),
    "exec_module.py": "def load(spec, m):\n    spec.loader.exec_module(m)\n",
    "load_module.py": "def load(loader):\n    return loader.load_module('m')\n",
    "run_module.py": "import runpy\ndef load():\n    return runpy.run_module('m')\n",
    "run_path.py": "import runpy\ndef load():\n    return runpy.run_path('/tmp/m.py')\n",
}
BENIGN = ("from __future__ import annotations\nimport json\nfrom dataclasses import dataclass, field\n"
          "from .verdict import reconcile as _reconcile\n\nKINDS = ('receipt', 'webhook')\n"
          "for kind in KINDS:\n    pass\n\n\n@dataclass\nclass Verdict:\n    word: str\n"
          "    sources: list = field(default_factory=list)\n\n    def basis(self):\n"
          "        return vars(self)\n\n    def _authorize_nothing(self):\n        return None\n\n\n"
          "def reconcile(rows):\n    if (n := len(rows)):\n        return _reconcile(rows)\n"
          "    return json.dumps({'rows': n})\n")


def test_the_authority_check_binds_on_a_probe_package(tmp_path):
    """Every form above is caught, each in its own module, and a package that
    only reads rows and returns a word is clean."""
    package = tmp_path / "runtime" / "evidence"
    package.mkdir(parents=True)
    (package / "clean.py").write_text(BENIGN, encoding="utf-8")
    assert authority_offences(package, tmp_path) == []
    for name, source in PROBES.items():
        (package / name).write_text(source, encoding="utf-8")
    offences = authority_offences(package, tmp_path)
    caught = {o.split(":")[0].rsplit("/", 1)[-1] for o in offences}
    assert caught == set(PROBES), sorted(set(PROBES) - caught)


@pytest.mark.parametrize("name", sorted(PROBES))
def test_each_probe_is_caught_on_its_own(tmp_path, name):
    """No probe is caught only because another one sits beside it."""
    package = tmp_path / "runtime" / "evidence"
    package.mkdir(parents=True)
    (package / name).write_text(PROBES[name], encoding="utf-8")
    assert authority_offences(package, tmp_path), f"{name} breaks (c) and was not caught"


#: Names that say one of the eleven acts in a derived form: the stems must
#: match every one of them.
SAYS_THE_ACT = (
    "Retrier", "retrial", "retriable", "retries", "retried", "retrying", "retryable",
    "denial", "make_denial", "denier", "undeniable", "denies", "denied", "denying",
    "issue_permission", "permissive", "permissible", "permitted", "permits",
    "authz", "AuthZ", "authorisation", "authorization", "authorizer",
    "queuing", "queued", "requeue", "enqueue", "dequeue",
    "Scheduler", "scheduling", "rescheduled", "executor", "execution", "approval", "approver",
    "grantor", "granted", "allowlist", "allowance", "dispatched", "dispatcher",
)
#: Names that share letters with a stem and say nothing of the act: the stems
#: must leave every one of them alone.
SAYS_NOTHING_OF_IT = (
    "retrieve", "retrieval", "retrieved", "dense", "denominator", "denote", "permanent",
    "permutation", "author", "authentic", "authenticate", "quorum", "approach", "grand",
    "schema", "settle", "reconcile", "receipt", "verdict", "sources", "outcome",
)


@pytest.mark.parametrize("name", SAYS_THE_ACT)
def test_the_stems_match_each_inflection_of_the_eleven_acts(name):
    assert FORBIDDEN_NAME.search(name), f"{name} says the act and the stems miss it"


@pytest.mark.parametrize("name", SAYS_NOTHING_OF_IT)
def test_the_stems_leave_a_name_that_says_nothing_of_them(name):
    assert not FORBIDDEN_NAME.search(name), f"{name} says nothing of the acts and the stems match it"
