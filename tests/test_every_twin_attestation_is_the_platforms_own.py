"""No twin tool signs an attestation whose statement or subject the request wrote.

THE CLASS (register entry::B3-ATTEST-SIBLING and entry::U-ATTEST-AXIS). Every
EAS attestation a twin tool makes goes through ``EASClient.attest``, is signed
with the platform's key, and writes on-chain ``(platform, action, agent,
timestamp)`` plus a RECIPIENT, the address the statement is about. If the
request writes the action or the agent, the platform key vouches for a sentence
somebody else composed. If the request writes the recipient, the platform key
puts its statement on an address nobody showed they control.

The first repair closed three sites (agent_identity.attest_action, the
agent_identity.register name, identity.register's address). A review then drove
the same effect through five more on the same reach: the general ``eas`` tool's
``attest`` and ``batch_attest`` (action, agent and recipient all from the
request), ``gaming.record_achievement`` (recipient = ``player_address``),
``ip_royalties.register_ip`` (recipient = ``owner``),
``securities.whitelist_investor`` (recipient = ``investor_address``) and
``crossborder_payment.send`` (recipient = ``to``, for a payment the call never
makes). ``eas.revoke`` is the same axis turned round: the platform key voided
whichever of its own attestations the request named, somebody else's included.

THE CHANGE. ``eas`` attest, batch_attest and revoke are refused. The seam binds
each attestation's subject field to the caller's own identity, as it already
did for identity.register. The cross-border record names no subject.

THE CENSUS. The walk reads the source of every module in
``runtime/blockchain/`` (the twin tools and what they import there), finds every
``.attest(`` call, traces its ``action``, ``agent`` and ``recipient`` back to the
request, and fails if a request field reaches the action or the agent, or reaches
the recipient through a field the seam does not bind for that tool and verb.

The trace: every part of each of those three values must be one of

  * a constant, or a module name bound once to a literal that cannot change;
  * a field of the request (a parameter of the tool method, read by ``.get``,
    by subscript or whole);
  * a local name, every one of whose bindings the trace reads — an assignment
    (unpacking included), an augmented or annotated one, ``:=``, a ``for`` or
    comprehension target, ``with ... as``, a ``match`` capture — and which, if
    it is read into, is handed nowhere else in the method;
  * a ``self`` attribute, every one of whose writes anywhere in the module the
    trace reads (in a method's own body: by those same forms, by a
    ``setattr`` spelled either way with a constant name, or into its content),
    read back as the request whole whenever a write draws on one; or one the
    base class sets from the configuration (``BASE_ATTRIBUTES``, pinned);
  * a call of a builtin that only converts (``str``, ``int`` ...) or of a
    string method, on such parts; or any other call handed the request, read
    as the request whole.

A field of the request is the caller's only if the request still says what the
caller wrote when it is read. So in a module with an attestation, every
function but ``__init__`` must leave what it is handed as it arrived. Reported
at each of the module's attestations: a write into a parameter, or into a name
bound to one — bound by an assignment, an annotated assignment or ``:=`` to a
plain name whose value may be the parameter itself (the name, an
``and``/``or`` operand, a conditional's branch), or by a ``match`` capture of
the whole subject (``case q``, ``case ... as q``); and a parameter, or an
``and``/``or`` or conditional over one, handed anywhere the census does not
read (a call outside the class and the module, an attribute, a container, a
``return``). Reading a field, looking a key up, testing, matching, formatting,
converting, and handing the request to a method of the class or a function of
the module are read as leaving it unchanged.

Any other part of a value is reported as a place the walk cannot follow the
request: a
module name something can write (a dict, a ContextVar), a name bound by
``except``, ``import``, ``global`` or ``nonlocal``, another object's attribute,
a ``self`` attribute written through anything but ``self`` or outside a
method's own body, a method or property of that name, an attribute nothing in
the module writes, any ``self`` attribute in a module whose classes define an
attribute hook (``__getattr__``, ``__getattribute__``, ``__setattr__`` and their
kin), a local or attribute handed elsewhere before it is read into, and what a
call not handed the request returns.

How ``attest`` is reached. Reported, each saying why:
``attest`` taken as a value; reached by its name as a string (``getattr``,
``__getattribute__``, ``operator.methodcaller``, a subscript); any attribute
reached by a name computed at run time; a namespace read or written by name
(``__dict__``, ``vars()``, ``globals()``, ``locals()``); an attribute written or
deleted by a computed name; code or a module loaded at run time (``exec``,
``eval``, ``compile``, ``__import__``, ``importlib``); a contract function
looked up by name or selector or chosen at run time; the EAS contract's attest
or revoke (or any other write it offers) built anywhere but inside
``EASClient.attest``; an attestation outside a tool method, inside a def or
lambda nested in one, behind a decorator, or with a ``*`` or ``**`` splat; and
a request ``execute`` rewrites or re-hands. Four places in the directory reach
an attribute by a computed name and no EAS client, and one looks a contract
function up to read it; each is listed by name with the reason
(``NAMED_LOOKUPS``, ``CONTRACT_LOOKUPS``). Planted shapes prove the walk reports
each of these. Two guards keep it honest about the client: ``EASClient``
reaches the contract only in ``attest`` and in ``verify``'s read, and if it
ever encodes ``details``, the census has to learn to read them. A third keeps
the directory closed: every module a twin imports under ``runtime/``, a
relative import resolved, is inside it or named and read for an attestation.
A fourth keeps inheritance closed: every class that attests inherits only
``BlockchainInterface``, which defines no attribute hook.

WHAT THIS DOES NOT COVER, stated. The services layer
(``runtime/blockchain/services/``) has its own attestation service; its three
request-facing actions are refused at every door that dispatches them
(tests/test_no_request_makes_the_attestation_service_sign.py), but the records
the services write about operations they ran are not walked here. A bound
subject is not a verified statement: an achievement, an IP claim or an
investor's whitelisting recorded for the caller's own address is still the
caller's word. The walk reads source: code replaced at run time from outside
the directory (monkeypatching by an importer, a test) is outside it. An
attestation signed through a contract call whose function the request chose
never reaches ``EASClient.attest``, so this walk cannot see one; the census of
every signing call (tests/test_no_request_chooses_the_call_the_platform_key_
signs.py) is what reads that. And the walk reads the shapes this docstring
names, and no others: a value, a request or a way of reaching ``attest``
spelled in a shape it does not name is not read, and nothing here claims the
list is every shape Python allows. Reviews have found shapes past it before
(the control history below); each is now named and planted.

CONTROL. At The Matrix ``main`` 91a89fb, and on the first repair (fix/oldq-census
faad66f), the 12 tests marked [control] before the planted-shape section fail;
the 9 marked [guard] pass before and after — they pin what must keep working
(the caller's own address, an absent field, a payment to somebody else) and
that the census can see what it looks for. At 67f3ad6 the four [control] tests
in the planted-shape section's first part fail and its [guard] passes; at
7abfa21 the two in its second part fail. At a710052 the ten [control] tests of
the last section fail (the nine shapes and an EAS write outside the client) and
three of its four [guard] tests pass; the fourth, which holds ``NAMED_LOOKUPS``
to what the walk finds, tests the listing this change adds and cannot run there.
The seventeen [control] shapes of the last section, run with the census as it
stood at this branch's signing-census commit ("The signing census reads every
form that binds a name ..."), each pass there with nothing reported, and are
reported here; the relative-import control's form was not counted by the
premise as it stood there. The last section's four guards pass here. The six
[control] shapes of a request changed before its field is read, run with the
census as it stood at the attestation-trace commit ("The attestation census
traces every value ..."), each pass there with nothing reported, and are
reported here; their guard passes. So does the attribute-hook control, and
its guard passes. The six [control] shapes of a request changed through a name
bound by ``or``, a conditional or a ``match`` capture, or handed on through
``or``, run with the census as it stood at "Both censuses report a value
changed through another name before it is read ...", each pass there with
nothing reported, and are reported here; their guard passes at both.
"""

from __future__ import annotations

import ast
import asyncio
import collections
import json
import pathlib
import sys
from typing import NamedTuple

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TWIN_DIR = ROOT / "runtime" / "blockchain"
CFG = {"blockchain": {"network": "base-sepolia"}}
ZERO = "0x" + "0" * 40
A = "0x" + "a1" * 20      # the caller's bound identity
B = "0x" + "b2" * 20      # somebody else


@pytest.fixture
def attests(monkeypatch):
    """Every call that would have reached the platform-signed EAS attest."""
    calls = []

    async def spy(self, action, agent, details, recipient=ZERO):
        calls.append({"action": action, "agent": agent, "recipient": recipient})
        return {"status": "skipped", "reason": "test spy"}

    monkeypatch.setattr("runtime.blockchain.eas_client.EASClient.attest", spy)
    return calls


def _run(coro):
    return json.loads(asyncio.run(coro))


# ── the general attestation tool ─────────────────────────────────────────

def test_eas_attest_signs_no_statement_the_request_composed(attests):
    """[control]"""
    from runtime.blockchain.eas_manager import EASManager
    out = _run(EASManager(CFG).execute(
        action="attest", recipient=B,
        data={"action": "approved_withdrawal", "agent": "morpheus"}))
    assert attests == [], f"the platform key was asked to sign {attests}"
    assert out.get("ok") is False and out.get("code") == "denied"


def test_eas_batch_attest_signs_none_either(attests):
    """[control]"""
    from runtime.blockchain.eas_manager import EASManager
    out = _run(EASManager(CFG).execute(
        action="batch_attest",
        attestations=[{"action": "approved_withdrawal", "agent": "morpheus"}] * 3))
    assert attests == [], f"the platform key was asked to sign {attests}"
    assert out.get("ok") is False and out.get("code") == "denied"


def test_eas_revoke_voids_no_attestation_a_request_names(monkeypatch):
    """[control] The platform is the attester of every record it signs, so EAS
    lets its key revoke any of them — somebody's identity registration, an
    insurance policy verified by its uid."""
    from unittest.mock import MagicMock

    from runtime.blockchain.eas_manager import EASManager
    reached = []

    async def signer_spy(self, what):
        reached.append(what)
        raise RuntimeError("stopped at the platform signer by the test")

    monkeypatch.setattr(EASManager, "_platform_signer", signer_spy)
    monkeypatch.setattr(EASManager, "web3", property(lambda self: MagicMock()))
    cfg = {"blockchain": {
        "network": "base-sepolia", "rpc_url": "http://127.0.0.1:1",
        "paymaster_private_key": "0x" + "1" * 64, "platform_wallet": A,
        "eas_contract": B, "eas_schema": "0x" + "cd" * 32}}
    out = _run(EASManager(cfg).execute(action="revoke", attestation_uid="0x" + "ef" * 32))
    assert reached == [], "a revocation the request named reached the platform signer"
    assert out.get("ok") is False and out.get("code") == "denied"


# ── the cross-border record ──────────────────────────────────────────────

def test_a_cross_border_record_names_no_subject_the_request_chose(attests):
    """[control] The call pays nobody; its attestation put a platform-signed
    "cross-border payment" on whatever address the request wrote as `to`."""
    from runtime.blockchain.crossborder import CrossBorderPayments
    out = _run(CrossBorderPayments(CFG).execute(action="send", to=B, amount="5", token="USDC"))
    assert [c["recipient"] for c in attests] == [ZERO], attests
    assert out["value_moved"] is False, "the call must still say it moved nothing"


# ── the seam: each attestation's subject field ───────────────────────────

SUBJECT_CASES = [
    ("gaming", {"action": "record_achievement", "player_address": B, "achievement": "x"},
     "player_address"),
    ("ip_royalties", {"action": "register_ip", "owner": B, "ip_name": "x"}, "owner"),
    ("securities", {"action": "whitelist_investor", "investor_address": B,
                    "contract_address": ZERO}, "investor_address"),
]


@pytest.mark.parametrize("tool,args,field", SUBJECT_CASES)
def test_an_attestation_about_somebody_else_is_refused(tool, args, field):
    """[control]"""
    from runtime.security.action_map import beneficiary_violation
    msg = beneficiary_violation(tool, args, A)
    assert msg and "own address" in msg and field in msg, \
        f"{tool}.{args['action']} naming {B} for caller {A} was not refused: {msg!r}"


@pytest.mark.parametrize("tool,args,field", SUBJECT_CASES)
def test_with_no_bound_identity_an_attestation_naming_anyone_is_refused(tool, args, field):
    """[control]"""
    from runtime.security.action_map import beneficiary_violation
    msg = beneficiary_violation(tool, args, "")
    assert msg and "no identity is bound" in msg


@pytest.mark.parametrize("tool,args,field", SUBJECT_CASES)
def test_the_callers_own_address_and_an_absent_one_still_pass(tool, args, field):
    """[guard]"""
    from runtime.security.action_map import beneficiary_violation
    own = {**args, field: A.upper().replace("0X", "0x")}
    assert beneficiary_violation(tool, own, A) is None
    absent = {k: v for k, v in args.items() if k != field}
    assert beneficiary_violation(tool, absent, A) is None


@pytest.mark.parametrize("tool,args", [
    ("nft", {"action": "mint", "to": B, "contract_address": ZERO, "token_uri": "ipfs://x"}),
    ("gaming", {"action": "mint_item", "player_address": B, "contract_address": ZERO}),
    ("stablecoin", {"action": "transfer", "to": B, "token": "USDC", "amount": "1"}),
    ("payment", {"action": "send_eth", "to": B, "amount": "1"}),
])
def test_a_payment_or_mint_to_somebody_else_is_not_a_subject_binding(tool, args):
    """[guard] Delivering value to another address is what these actions are
    for; the gate evaluates them as value movement by their verb. Binding the
    subject of a statement must not turn into forbidding a payee."""
    from runtime.security.action_map import beneficiary_violation
    assert beneficiary_violation(tool, args, A) is None


async def test_the_seam_refuses_before_the_gate_sees_it():
    """[control] Through the real pre_action, as the tool loop calls it."""
    sys.path.insert(0, str(ROOT / "tests"))
    from test_twins_seam import _stack
    stack = _stack()
    result = await stack.pre_action(
        "gaming", {"action": "record_achievement", "player_address": B, "achievement": "x"},
        {"wallet": A})
    assert result["approved"] is False and "own address" in result["denial_reason"]
    assert stack._morpheus_security.seen == [], "refused at the seam; the gate never saw it"


# ── the census ───────────────────────────────────────────────────────────

def _tool_name(cls: ast.ClassDef) -> str | None:
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name == "name":
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Return) and isinstance(sub.value, ast.Constant)
                        and isinstance(sub.value.value, str)):
                    return sub.value.value
    return None


def _verbs(cls: ast.ClassDef) -> dict[str, str]:
    """method name -> the action verb ``execute`` dispatches to it."""
    out: dict[str, str] = {}
    for node in cls.body:
        if not (isinstance(node, ast.AsyncFunctionDef) and node.name == "execute"):
            continue
        for branch in ast.walk(node):
            if not isinstance(branch, ast.If):
                continue
            t = branch.test
            if not (isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq)
                    and isinstance(t.comparators[0], ast.Constant)):
                continue
            for stmt in branch.body:
                for c in ast.walk(stmt):
                    if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                            and isinstance(c.func.value, ast.Name) and c.func.value.id == "self"):
                        out.setdefault(c.func.attr, t.comparators[0].value)
    return out


def _fields(expr: ast.AST, roots: set[str], tainted: dict[str, set[str]],
            carried: frozenset[str] = frozenset()) -> tuple[bool, set[str]]:
    """Whether *expr* draws on the request, and through which fields ("*" = the
    request as a whole, or a field not named by a literal). *carried* names the
    ``self`` attributes some method of the class stored the request in; one
    read back here is the request, through fields the census cannot name."""
    drawn, fields, consumed = False, set(), set()
    for n in ast.walk(expr):
        if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                and n.value.id == "self" and n.attr in carried):
            drawn = True
            fields.add("*")
    for n in ast.walk(expr):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get"
                and isinstance(n.func.value, ast.Name) and n.func.value.id in roots):
            consumed.add(id(n.func.value))
            drawn = True
            key = n.args[0] if n.args else None
            fields.add(key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else "*")
        elif isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id in roots:
            consumed.add(id(n.value))
            drawn = True
            key = n.slice
            fields.add(key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else "*")
    for n in ast.walk(expr):
        if isinstance(n, ast.Name):
            if n.id in roots and id(n) not in consumed:
                drawn = True
                fields.add("*")
            elif n.id in tainted:
                drawn = True
                fields |= tainted[n.id]
    return drawn, fields


def _taint(fn: ast.AST, roots: set[str], carried: frozenset[str] = frozenset()) -> dict[str, set[str]]:
    """Local names assigned (directly or through other names) from the request."""
    tainted: dict[str, set[str]] = {}
    changed = True
    while changed:
        changed = False
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign):
                pairs = [(t, n.value) for t in n.targets]
            elif isinstance(n, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)) and n.value is not None:
                pairs = [(n.target, n.value)]
            elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
                pairs = [(n.target, n.iter)]
            elif isinstance(n, (ast.With, ast.AsyncWith)):
                pairs = [(i.optional_vars, i.context_expr) for i in n.items if i.optional_vars]
            elif isinstance(n, ast.Match):
                pairs = [pair for case in n.cases for pair in _captures(case.pattern, n.subject)]
            else:
                continue
            for target, value in pairs:
                drawn, fields = _fields(value, roots, tainted, carried)
                if not drawn:
                    continue
                for t in ast.walk(target):
                    if not isinstance(t, ast.Name):
                        continue
                    have = tainted.get(t.id)
                    if have is None or not fields <= have:
                        tainted[t.id] = (have or set()) | fields
                        changed = True
    return tainted


def _captures(pattern: ast.AST, subject: ast.AST) -> list[tuple[ast.AST, ast.AST]]:
    """(target, value) for each name a ``case`` pattern binds: a name bound
    under a literal key of a mapping pattern reads that key of the subject, any
    other capture reads the subject as a whole."""
    pairs, keyed = [], set()
    for p in ast.walk(pattern):
        if isinstance(p, ast.MatchMapping):
            for key, sub in zip(p.keys, p.patterns):
                if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                        and isinstance(sub, ast.MatchAs) and sub.pattern is None and sub.name):
                    keyed.add(id(sub))
                    read = ast.Call(func=ast.Attribute(value=subject, attr="get", ctx=ast.Load()),
                                    args=[key], keywords=[])
                    pairs.append((ast.Name(id=sub.name, ctx=ast.Store()), read))
            if p.rest:
                pairs.append((ast.Name(id=p.rest, ctx=ast.Store()), subject))
    for p in ast.walk(pattern):
        if isinstance(p, (ast.MatchAs, ast.MatchStar)) and p.name and id(p) not in keyed:
            pairs.append((ast.Name(id=p.name, ctx=ast.Store()), subject))
    return pairs


#: The one agent name a request may choose: agent_identity.register checks it
#: against the platform's own three (test_platform_key_signs_only_what_it_can_
#: stand_behind.py pins that it refuses any other).
AGENT_FROM_A_FIXED_SET = {("agent_identity", "register")}


def _seam_binds(tool: str, verb: str | None) -> set[str]:
    """The fields the seam binds to the caller for this tool and verb."""
    from runtime.security.action_map import ACTION_BENEFICIARY_FIELDS, BENEFICIARY_FIELDS
    return set(BENEFICIARY_FIELDS) | set(ACTION_BENEFICIARY_FIELDS.get((tool, verb), ()))


_MUTATORS = frozenset({"update", "setdefault", "pop", "popitem", "clear",
                       "__setitem__", "__delitem__", "__ior__"})


def _roots(fn) -> set[str]:
    roots = {a.arg for a in fn.args.args + fn.args.kwonlyargs if a.arg != "self"}
    if fn.args.kwarg:
        roots.add(fn.args.kwarg.arg)
    if fn.args.vararg:
        roots.add(fn.args.vararg.arg)
    return roots


def _rewrites(fn, roots: set[str]) -> str | None:
    """Why *fn* changes the request before a field of it is read, or None. A
    field read after ``params["player_address"] = params.get("to")`` is not the
    field the request wrote under that name."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            targets = n.targets
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)):
            targets = [n.target]
        elif isinstance(n, ast.Delete):
            targets = n.targets
        else:
            targets = []
        for t in targets:
            if isinstance(t, ast.Name) and t.id in roots:
                return "the request is rebound before it is read"
            for sub in ast.walk(t):
                if isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name) \
                        and sub.value.id in roots:
                    return "the request is rewritten before it is read"
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in _MUTATORS and isinstance(n.func.value, ast.Name)
                and n.func.value.id in roots):
            return "the request is rewritten before it is read"
    return None


def _handoffs(cls: ast.ClassDef) -> dict[str, list[str]]:
    """method name -> why ``execute`` does not hand it the request as it
    arrived. A method is read as if its argument's fields were the request's;
    ``self._m({**kwargs, "player_address": kwargs.get("to")})`` makes that
    untrue, and so does rewriting ``kwargs`` first."""
    out: dict[str, list[str]] = {}
    for node in cls.body:
        if not (isinstance(node, ast.AsyncFunctionDef) and node.name == "execute"):
            continue
        root = node.args.kwarg.arg if node.args.kwarg else None
        rewritten = _rewrites(node, {root} if root else set())
        for c in ast.walk(node):
            if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and isinstance(c.func.value, ast.Name) and c.func.value.id == "self"):
                continue
            plain = (root is not None and len(c.args) == 1 and not c.keywords
                     and isinstance(c.args[0], ast.Name) and c.args[0].id == root)
            problems = out.setdefault(c.func.attr, [])
            if not plain:
                problems.append("execute hands it something other than the request as it "
                                "arrived; the census cannot map its fields")
            if rewritten:
                problems.append(f"in execute, {rewritten}")
    return out


def _carried(cls: ast.ClassDef) -> frozenset[str]:
    """The ``self`` attributes any method of the class stores the request in
    (``self._who = kwargs.get("to")``, ``self._seen.append(params)``), to a
    fixed point: a method that reads one back is reading the request."""
    carried: set[str] = set()
    changed = True
    while changed:
        changed = False
        for fn in cls.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            roots = _roots(fn)
            tainted = _taint(fn, roots, frozenset(carried))
            for n in ast.walk(fn):
                stores = []
                if isinstance(n, ast.Assign):
                    stores = [(t, n.value) for t in n.targets]
                elif isinstance(n, (ast.AugAssign, ast.AnnAssign)) and n.value is not None:
                    stores = [(n.target, n.value)]
                elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and isinstance(n.func.value, (ast.Attribute, ast.Subscript))):
                    stores = [(n.func.value, a) for a in [*n.args, *(k.value for k in n.keywords)]]
                elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
                    stores = [(n.target, n.iter)]
                elif isinstance(n, (ast.With, ast.AsyncWith)):
                    stores = [(i.optional_vars, i.context_expr) for i in n.items if i.optional_vars]
                elif (_is_setattr_on_self(n) and isinstance(_setattr_parts(n)[1], ast.Constant)
                        and isinstance(_setattr_parts(n)[1].value, str)):
                    _obj, name, value = _setattr_parts(n)
                    stores = [(ast.Attribute(value=ast.Name(id="self", ctx=ast.Load()),
                                             attr=name.value, ctx=ast.Store()), value)]
                for target, value in stores:
                    if not _fields(value, roots, tainted, frozenset(carried))[0]:
                        continue
                    for sub in ast.walk(target):
                        if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                                and sub.value.id == "self" and sub.attr not in carried):
                            carried.add(sub.attr)
                            changed = True
    return frozenset(carried)


def _setattr_parts(n: ast.AST):
    """(object, name, value) of an attribute write spelled as a call:
    ``setattr(obj, name, value)``, ``X.__setattr__(obj, name, value)``, or
    ``obj.__setattr__(name, value)`` (``super().__setattr__`` included, read as
    ``self``); None for anything else."""
    if not isinstance(n, ast.Call):
        return None
    f = n.func
    if isinstance(f, ast.Name) and f.id == "setattr" and len(n.args) == 3:
        return tuple(n.args)
    if isinstance(f, ast.Attribute) and f.attr == "__setattr__":
        if len(n.args) == 3:
            return tuple(n.args)
        if len(n.args) == 2:
            obj = f.value
            if (isinstance(obj, ast.Call) and isinstance(obj.func, ast.Name)
                    and obj.func.id == "super"):
                obj = ast.Name(id="self", ctx=ast.Load())
            return (obj, *n.args)
    return None


def _is_setattr_on_self(n: ast.AST) -> bool:
    """An attribute write spelled as a call, on ``self``."""
    parts = _setattr_parts(n)
    return parts is not None and isinstance(parts[0], ast.Name) and parts[0].id == "self"


def _is_self_namespace(n: ast.AST) -> bool:
    """``self.__dict__`` or ``vars(self)``: the object's attributes by a name
    the walk cannot read."""
    if isinstance(n, ast.Attribute) and n.attr == "__dict__":
        return isinstance(n.value, ast.Name) and n.value.id == "self"
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "vars"
            and len(n.args) == 1 and isinstance(n.args[0], ast.Name) and n.args[0].id == "self")


def _opaque_self_store(cls: ast.ClassDef) -> str | None:
    """Why the request may sit on ``self`` under a name the census cannot read,
    or None: ``setattr(self, <computed>, ...)``, a write into ``self.__dict__``
    or ``vars(self)``, from anything the method was handed."""
    for fn in cls.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        roots = _roots(fn)
        tainted = _taint(fn, roots)
        for n in ast.walk(fn):
            values = []
            if _is_setattr_on_self(n) and not (isinstance(_setattr_parts(n)[1], ast.Constant)
                                               and isinstance(_setattr_parts(n)[1].value, str)):
                values = [_setattr_parts(n)[2]]
            elif isinstance(n, (ast.Assign, ast.AugAssign)):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                if any(_is_self_namespace(sub) for t in targets for sub in ast.walk(t)):
                    values = [n.value]
            elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and _is_self_namespace(n.func.value)):
                values = [*n.args, *(k.value for k in n.keywords)]
            if any(_fields(v, roots, tainted)[0] for v in values):
                return (f"{fn.name} stores the request on self under a name the census "
                        f"cannot read (line {n.lineno}); it cannot follow it to an attestation")
    return None


# ── what the walk follows, and everything else it reports ───────────────
#
# The checks above read the forms the walk knows. What follows makes that
# list closed: every value that reaches an attestation's action, agent or
# recipient is traced back through the source, and any part of it that is not
# a constant, a field of the request, or something built only from those
# through a form the walk reads is reported as a place it cannot follow the
# request. So a shape nobody planted fails too.

#: Builtins that only convert what they are handed.
_CONVERTERS = frozenset({"str", "int", "float", "bool", "len", "hex", "abs",
                         "min", "max", "round", "repr"})
#: String methods that only transform the string they are called on.
_STRING_METHODS = frozenset({"lower", "upper", "strip", "lstrip", "rstrip", "casefold",
                             "replace", "startswith", "endswith", "split", "join",
                             "format"})
#: Attributes a twin reads on ``self`` that no module in the directory the walk
#: reads writes there: the base class sets them from the configuration it is
#: built with. Each with where it comes from.
BASE_ATTRIBUTES = {
    "platform_wallet": (
        "BlockchainInterface.__init__ sets it from config['blockchain']"
        "['platform_wallet'] (runtime/blockchain/interface.py); nothing a request "
        "carries reaches it (test_the_base_attributes_are_the_configurations)"),
}
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
_READ_FORMS = frozenset({"an assignment", "a loop", "a with", "a match"})


def _own(fn):
    """The nodes of *fn*'s own body: not those of a def, lambda or class in it."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _SCOPE_NODES):
            stack.extend(ast.iter_child_nodes(node))


def _stored_names(target) -> list[str]:
    return [t.id for t in ast.walk(target)
            if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)]


def _immutable(value) -> bool:
    if isinstance(value, (tuple, frozenset)):
        return all(_immutable(v) for v in value)
    return isinstance(value, (str, bytes, int, float, bool, type(None)))


def _fixed(expr) -> bool:
    """Whether *expr* is built only from literals that cannot change: a
    constant, or a tuple, an operator or an f-string over such parts."""
    if isinstance(expr, ast.Constant):
        return _immutable(expr.value)
    if isinstance(expr, ast.Tuple):
        return all(_fixed(e) for e in expr.elts)
    if isinstance(expr, ast.BinOp):
        return _fixed(expr.left) and _fixed(expr.right)
    if isinstance(expr, ast.UnaryOp):
        return _fixed(expr.operand)
    if isinstance(expr, ast.JoinedStr):
        return all(_fixed(v.value if isinstance(v, ast.FormattedValue) else v) for v in expr.values)
    return False


def _parents(tree) -> dict[int, ast.AST]:
    return {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _scope_of(node, parents) -> ast.AST | None:
    """The innermost def, lambda or class around *node*, or None at module level."""
    up = parents.get(id(node))
    while up is not None and not isinstance(up, _SCOPE_NODES):
        up = parents.get(id(up))
    return up


class _Module(NamedTuple):
    """What the trace needs to know about one module, read once."""
    tree: ast.AST
    parents: dict
    constants: frozenset      # module names bound once, to an immutable literal
    writes: dict              # attribute name -> [(readable, why, method, value)]
    escaped: frozenset        # self attributes handed somewhere as a whole


def _module_constants(tree, parents) -> frozenset:
    counts: collections.Counter = collections.Counter()
    values: dict = {}
    for node in ast.walk(tree):
        if _scope_of(node, parents) is not None:
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            counts[node.name] += 2
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                counts[(a.asname or a.name).split(".")[0]] += 2
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            counts[node.id] += 1
            parent = parents.get(id(node))
            if isinstance(parent, (ast.Assign, ast.AnnAssign)) and getattr(parent, "value", None) is not None:
                values[node.id] = parent.value
    declared = {g for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal)) for g in n.names}
    return frozenset(name for name, count in counts.items()
                     if count == 1 and name not in declared and name in values
                     and _fixed(values[name]))


def _is_self(node) -> bool:
    return isinstance(node, ast.Name) and node.id == "self"


def _self_root(node) -> str | None:
    """X when *node* is ``self.X`` or something inside it (``self.X[k]``, ``self.X.y``)."""
    while isinstance(node, (ast.Subscript, ast.Attribute)):
        if isinstance(node, ast.Attribute) and _is_self(node.value):
            return node.attr
        node = node.value
    return None


def _attribute_writes(tree, parents) -> dict:
    """Every write of an attribute anywhere in the module, by attribute name:
    (readable, why not, the method it is in, the value written)."""
    out: dict = collections.defaultdict(list)

    def method_of(node):
        scope = _scope_of(node, parents)
        if (isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef))
                and isinstance(parents.get(id(scope)), ast.ClassDef)):
            return scope
        return None

    def record(target_node, value, anchor):
        method = method_of(anchor)
        if isinstance(target_node, ast.Attribute) and _is_self(target_node.value):
            attr, how = target_node.attr, "written"
        elif isinstance(target_node, ast.Attribute):
            out[target_node.attr].append(
                (False, "written through something other than self (a class, "
                        "type(self), another object); the census does not follow it", None, None))
            return
        else:
            attr, how = _self_root(target_node), "written into"
            if attr is None:
                return
        if method is None:
            out[attr].append((False, f"{how} outside a method's own body (a nested def "
                                     "or lambda, or module level); the census does not "
                                     "follow it", None, None))
        else:
            out[attr].append((True, "", method, value))

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[stmt.name].append((False, "a method or property of that name; the "
                                                  "census does not follow what it returns",
                                           None, None))
                elif isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
                    fixed = _fixed(stmt.value)
                    for t in (stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]):
                        for name in _stored_names(t):
                            out[name].append((fixed, "a class attribute bound to something "
                                                     "other than an immutable literal", None,
                                              None))
        pairs = []
        if isinstance(node, ast.Assign):
            pairs = [(t, node.value) for t in node.targets]
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)) and node.value is not None:
            pairs = [(node.target, node.value)]
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            pairs = [(node.target, node.iter)]
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            pairs = [(i.optional_vars, i.context_expr) for i in node.items if i.optional_vars]
        for target, value in pairs:
            for sub in ast.walk(target):
                if isinstance(sub, (ast.Attribute, ast.Subscript)) and isinstance(
                        getattr(sub, "ctx", None), ast.Store):
                    record(sub, value, node)
        parts = _setattr_parts(node)
        if parts and isinstance(parts[1], ast.Constant) and isinstance(parts[1].value, str):
            record(ast.Attribute(value=parts[0], attr=parts[1].value, ctx=ast.Store()),
                   parts[2], node)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and _self_root(node.func.value) and (node.args or node.keywords)):
            record(node.func.value,
                   ast.Tuple(elts=[*node.args, *(k.value for k in node.keywords)], ctx=ast.Load()),
                   node)
    return dict(out)


def _escaped_self(tree, parents) -> frozenset:
    """Self attributes read as a whole somewhere other than as the base of a
    subscript or an attribute: handed to a call, bound to another name, put in
    a container. What is written into them there, the census does not see."""
    out = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and _is_self(node.value)
                and isinstance(node.ctx, ast.Load)):
            parent = parents.get(id(node))
            if not (isinstance(parent, (ast.Subscript, ast.Attribute)) and parent.value is node):
                out.add(node.attr)
    return frozenset(out)


def _module_facts(tree) -> _Module:
    parents = _parents(tree)
    return _Module(tree, parents, _module_constants(tree, parents),
                   _attribute_writes(tree, parents), _escaped_self(tree, parents))


def _local_bindings(fn) -> dict:
    """name -> [(how it is bound, the value)] for *fn*'s own body; the value is
    None for a form the trace does not read into."""
    out: dict = collections.defaultdict(list)

    def bind(target, how, value):
        for name in _stored_names(target):
            out[name].append((how, value))

    for n in _own(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                bind(t, "an assignment", n.value)
                for sub in ast.walk(t):
                    if (isinstance(sub, (ast.Subscript, ast.Attribute))
                            and isinstance(sub.value, ast.Name) and isinstance(sub.ctx, ast.Store)):
                        out[sub.value.id].append(("an assignment", n.value))
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)) and n.value is not None:
            bind(n.target, "an assignment", n.value)
            if isinstance(n.target, (ast.Subscript, ast.Attribute)) and isinstance(n.target.value, ast.Name):
                out[n.target.value.id].append(("an assignment", n.value))
        elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
            bind(n.target, "a loop", n.iter)
        elif isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                if item.optional_vars is not None:
                    bind(item.optional_vars, "a with", item.context_expr)
        elif isinstance(n, ast.Match):
            for case in n.cases:
                for target, value in _captures(case.pattern, n.subject):
                    bind(target, "a match", value)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out[n.name].append(("except ... as", None))
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out[(a.asname or a.name).split(".")[0]].append(("an import", None))
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[n.name].append(("a nested def or class", None))
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            for name in n.names:
                out[name].append(("global or nonlocal", None))
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and isinstance(n.func.value, ast.Name) and (n.args or n.keywords)):
            out.setdefault(n.func.value.id, [])
            out[n.func.value.id].append(("a call on it", ast.Tuple(
                elts=[*n.args, *(k.value for k in n.keywords)], ctx=ast.Load())))
    return dict(out)


def _escaped_locals(fn, parents) -> frozenset:
    """Local names read as a whole anywhere but as the base of a subscript or
    an attribute (handed to a call, bound to another name, captured by a
    nested def): what is written into them there, the census does not see."""
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            parent = parents.get(id(node))
            if not (isinstance(parent, (ast.Subscript, ast.Attribute)) and parent.value is node):
                out.add(node.id)
    return frozenset(out)


class _Walk(NamedTuple):
    module: _Module
    fn: ast.AST
    roots: frozenset
    bindings: dict
    escaped: frozenset


def _walk_for(fn, module: _Module) -> _Walk:
    return _Walk(module, fn, frozenset(_roots(fn)), _local_bindings(fn),
                 _escaped_locals(fn, module.parents))


def _key_field(key) -> str:
    return key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else "*"


def _trace(expr, w: _Walk, seen=frozenset()) -> tuple[list[str], set[str]]:
    """(what the walk cannot follow in *expr*, the request fields it reads).
    A field is "*" when the request is read whole or under a name the census
    cannot name."""
    problems: list[str] = []
    fields: set[str] = set()

    def add(result):
        problems.extend(result[0])
        fields.update(result[1])

    if expr is None or isinstance(expr, ast.Constant):
        return problems, fields
    if isinstance(expr, ast.Name):
        return _trace_name(expr.id, w, seen, content=False)
    if isinstance(expr, ast.Attribute):
        if _is_self(expr.value):
            return _trace_self(expr.attr, w, seen, content=False)
        return _trace_content(expr.value, w, seen)
    if isinstance(expr, ast.Subscript):
        base = expr.value
        if isinstance(base, ast.Name) and base.id in w.roots:
            fields.add(_key_field(expr.slice))
        else:
            add(_trace_content(base, w, seen))
        add(_trace(expr.slice, w, seen))
        return problems, fields
    if isinstance(expr, ast.Call):
        return _trace_call(expr, w, seen)
    if isinstance(expr, (ast.Lambda, ast.Yield, ast.YieldFrom)):
        return [f"a {type(expr).__name__.lower()} reaches it; the census does not follow it"], fields
    if isinstance(expr, ast.comprehension):
        add(_trace(expr.iter, w, seen))
        for cond in expr.ifs:
            add(_trace(cond, w, seen))
        return problems, fields
    for child in ast.iter_child_nodes(expr):
        if isinstance(child, (ast.expr, ast.comprehension)) and not (
                isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)):
            add(_trace(child, w, seen))
    return problems, fields


def _trace_name(name, w: _Walk, seen, content) -> tuple[list[str], set[str]]:
    if name in w.roots:
        return [], {"*"}
    if name in w.bindings:
        if name in seen:
            return [], set()
        problems: list[str] = []
        fields: set[str] = set()
        for how, value in w.bindings[name]:
            if value is None:
                problems.append(f"{name} is bound by {how}; the census does not follow what it holds")
                continue
            p, f = _trace(value, w, seen | {name})
            problems += p
            fields |= f
        if content and name in w.escaped:
            problems.append(f"{name} is handed elsewhere before it is read; the census does not "
                            "follow what is written into it there")
        return problems, fields
    if name in w.module.constants:
        return [], set()
    return [f"{name} is neither bound in this method nor an immutable constant of the module; "
            "the census does not follow what it holds"], set()


#: Hooks that make an attribute read or write run code of the class's own:
#: with one in the module, what ``self.x`` reads is not what the source wrote.
_ATTRIBUTE_HOOKS = frozenset({"__getattr__", "__getattribute__", "__setattr__", "__delattr__",
                              "__init_subclass__", "__set_name__", "__get__", "__set__"})


def _trace_self(attr, w: _Walk, seen, content) -> tuple[list[str], set[str]]:
    key = f"self.{attr}"
    if key in seen:
        return [], set()
    hooks = sorted(h for h in _ATTRIBUTE_HOOKS if h in w.module.writes)
    if hooks:
        return [f"{key}: the module defines {', '.join(hooks)}, so an attribute read runs "
                "code the census does not follow"], set()
    writes = w.module.writes.get(attr, [])
    if not writes:
        if attr in BASE_ATTRIBUTES:
            return [], set()
        return [f"{key} is never written in this module; the census does not follow where "
                "it comes from"], set()
    problems: list[str] = []
    fields: set[str] = set()
    for readable, why, method, value in writes:
        if not readable:
            problems.append(f"{key}: {why}")
            continue
        if value is None:
            continue
        p, f = _trace(value, _walk_for(method, w.module), seen | {key})
        problems += p
        if f:
            fields.add("*")         # the request stored on self: its fields cannot be named
    if content and attr in w.module.escaped:
        problems.append(f"{key} is handed elsewhere; the census does not follow what is "
                        "written into it there")
    return problems, fields


def _trace_content(base, w: _Walk, seen) -> tuple[list[str], set[str]]:
    """What reading into *base* (a subscript, an attribute, ``.get``) yields."""
    if isinstance(base, ast.Name):
        if base.id in w.roots:
            return [], {"*"}
        return _trace_name(base.id, w, seen, content=True)
    if isinstance(base, ast.Attribute) and _is_self(base.value):
        return _trace_self(base.attr, w, seen, content=True)
    return _trace(base, w, seen)


def _trace_call(call, w: _Walk, seen) -> tuple[list[str], set[str]]:
    problems: list[str] = []
    fields: set[str] = set()
    f = call.func
    arguments = [*call.args, *(k.value for k in call.keywords)]
    if isinstance(f, ast.Attribute) and f.attr == "get":
        if isinstance(f.value, ast.Name) and f.value.id in w.roots:
            if call.args:
                fields.add(_key_field(call.args[0]))
            for a in arguments[1:]:
                p, fs = _trace(a, w, seen)
                problems += p
                fields |= fs
            return problems, fields
        p, fs = _trace_content(f.value, w, seen)
        problems += p
        fields |= fs
        for a in arguments:
            p, fs = _trace(a, w, seen)
            problems += p
            fields |= fs
        return problems, fields
    pure = ((isinstance(f, ast.Name) and f.id in _CONVERTERS)
            or (isinstance(f, ast.Attribute) and f.attr in _STRING_METHODS))
    parts = list(arguments)
    if isinstance(f, ast.Attribute) and not (
            _is_self(f.value) or (isinstance(f.value, ast.Name) and f.value.id not in w.roots
                                  and f.value.id not in w.bindings)):
        parts.append(f.value)
    for a in parts:
        p, fs = _trace(a, w, seen)
        problems += p
        fields |= fs
    if pure:
        return problems, fields
    if fields:
        return problems, {"*"}      # a call handed the request is read as the request itself
    return problems + [f"what {ast.unparse(f)[:60]} returns; the census does not follow it"], fields


# ── the request itself must reach the attestation as it arrived ─────────
#
# A field read from the request is taken to be what the request wrote. That
# holds only while nothing in the module can change the request object before
# it is read: a method or function that writes into a parameter, directly or
# through a name bound to it, and a parameter handed anywhere the census does
# not read (another object's method, a function outside the module, a
# container, an attribute) can each put a different value under a field the
# seam binds. Reported at every attestation of a module where one appears.

#: Methods of a mapping that read it and change nothing.
_READS = frozenset({"get", "keys", "values", "items", "copy", "__contains__", "__getitem__"})


def _may_be(value, names: set[str]) -> bool:
    """Whether *value* can evaluate to one of *names* itself: the name, an
    ``and``/``or`` operand, a conditional's branch, or a ``:=`` of one."""
    if isinstance(value, ast.Name):
        return value.id in names
    if isinstance(value, ast.BoolOp):
        return any(_may_be(v, names) for v in value.values)
    if isinstance(value, ast.IfExp):
        return _may_be(value.body, names) or _may_be(value.orelse, names)
    if isinstance(value, ast.NamedExpr):
        return _may_be(value.value, names)
    return False


def _whole_captures(pattern) -> list[str]:
    """Names a ``case`` pattern binds to the whole subject: ``case q``,
    ``case <pattern> as q``, and either as an alternative of ``|``."""
    if isinstance(pattern, ast.MatchAs):
        return [pattern.name] if pattern.name else []
    if isinstance(pattern, ast.MatchOr):
        return [name for p in pattern.patterns for name in _whole_captures(p)]
    return []


def _aliases(fn, params: set[str]) -> set[str]:
    """The parameters, and every local name bound to one of them as a whole:
    by an assignment, an annotated assignment or ``:=`` to a plain name whose
    value may be one (``q = params``, ``q = params or {}``, ``q = params if
    c else {}``), and by a ``match`` on one that captures its whole subject."""
    names = set(params)
    changed = True
    while changed:
        changed = False
        for n in _own(fn):
            bound: list[str] = []
            if isinstance(n, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and _may_be(
                    getattr(n, "value", None), names):
                bound = [t.id for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
                         if isinstance(t, ast.Name)]
            elif isinstance(n, ast.Match) and _may_be(n.subject, names):
                bound = [name for case in n.cases for name in _whole_captures(case.pattern)]
            for name in bound:
                if name not in names:
                    names.add(name)
                    changed = True
    return names


def _lands(node, parents):
    """(child, parent) where *node*'s value lands, past every ``and``/``or``
    operand and conditional branch it is."""
    child, parent = node, parents.get(id(node))
    while isinstance(parent, ast.BoolOp) or (isinstance(parent, ast.IfExp) and child is not parent.test):
        child, parent = parent, parents.get(id(parent))
    return child, parent


def _request_handling(tree) -> list[tuple[str, int, str]]:
    """(function, line, why) for every place in *tree* where a parameter a
    function is handed may be changed, or leaves for somewhere the census does
    not read. ``__init__`` is left out: what it is handed is the configuration."""
    parents = _parents(tree)
    local_defs = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name == "__init__":
            continue
        params = {a.arg for a in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
                  if a.arg not in ("self", "cls")}
        params |= {a.arg for a in (fn.args.vararg, fn.args.kwarg) if a is not None}
        names = _aliases(fn, params)
        rewritten = _rewrites(fn, names)
        if rewritten:
            out.append((fn.name, fn.lineno, f"{rewritten} (through a name bound to it)"
                        if not _rewrites(fn, params) else rewritten))
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Name) and node.id in names and isinstance(node.ctx, ast.Load)):
                continue
            # Where the value lands: past an and/or operand or a conditional's
            # branch (``params or {}``), the rules below read what it lands in.
            child, parent = _lands(node, parents)
            via = "" if child is node else f" through {ast.unparse(child)[:40]!s}"
            if isinstance(parent, ast.Subscript) and parent.value is child:
                continue                                   # a field read, or a key looked up
                                                           # (a write into it is a rewrite)
            if isinstance(parent, ast.Attribute) and parent.value is child:
                called = parents.get(id(parent))
                if not (isinstance(called, ast.Call) and called.func is parent) or parent.attr in _READS:
                    continue                               # an attribute read, or .get()
                out.append((fn.name, node.lineno,
                            f"{node.id}{via}.{parent.attr}() may change the request"))
                continue
            if isinstance(parent, (ast.If, ast.While, ast.Assert, ast.IfExp)) and child is parent.test:
                continue                                   # tested
            if isinstance(parent, ast.comprehension) and child in parent.ifs:
                continue
            if isinstance(parent, (ast.Compare, ast.UnaryOp, ast.FormattedValue, ast.comprehension,
                                   ast.For, ast.AsyncFor, ast.Match, ast.BinOp)):
                continue                                   # tested, matched, formatted, iterated,
                                                           # or an operand of a new value
            if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and all(
                    isinstance(t, ast.Name) for t in (parent.targets if isinstance(parent, ast.Assign)
                                                      else [parent.target])):
                continue                                   # bound to another name, which is followed
            if isinstance(parent, ast.Call) and child in parent.args:
                f = parent.func
                if isinstance(f, ast.Attribute) and _is_self(f.value):
                    continue                               # a method of this class: read by the census
                if isinstance(f, ast.Name) and f.id in local_defs:
                    continue                               # a function of this module: read too
                if isinstance(f, ast.Name) and f.id in _CONVERTERS:
                    continue
                if isinstance(f, ast.Attribute) and f.attr in ("get", "__contains__", "__getitem__"):
                    continue                               # a key looked up in another mapping
            out.append((fn.name, node.lineno, (
                f"{node.id} is handed{via} to {ast.unparse(parent)[:50]!s}, which the census does not "
                "read; it may come back changed")))
    return out


#: Decorators that hand a method what its caller passed, unchanged.
_TRANSPARENT_DECORATORS = frozenset({"property", "staticmethod", "classmethod", "abstractmethod"})


def _rewrapped(fn) -> bool:
    """Whether a decorator stands between *fn* and its caller: it may hand the
    method something other than the request."""
    for d in fn.decorator_list:
        name = d.attr if isinstance(d, ast.Attribute) else d.id if isinstance(d, ast.Name) else None
        if name not in _TRANSPARENT_DECORATORS:
            return True
    return False


def _unread_bindings(tree: ast.AST, fn) -> set[str]:
    """Names *fn* sees bound by a form the taint walk does not read: an
    ``except ... as`` name (what the exception carries), and a name any function
    of the module declares ``global`` or ``nonlocal`` (what another function
    stored there)."""
    names = {h.name for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler) and h.name}
    for n in ast.walk(tree):
        if isinstance(n, (ast.Global, ast.Nonlocal)):
            names |= set(n.names)
    return names


#: What the EAS contract offers that writes: any of these, called anywhere but
#: in EASClient.attest, is an attestation or a revocation the census cannot read.
EAS_WRITES = frozenset({
    "attest", "multiAttest", "attestByDelegation", "multiAttestByDelegation",
    "revoke", "multiRevoke", "revokeByDelegation", "multiRevokeByDelegation",
    "revokeOffchain", "multiRevokeOffchain", "timestamp", "multiTimestamp",
})


def _qualnames(tree: ast.AST) -> dict[int, str]:
    """node id -> the qualified name of the def it sits in ("" at module level)."""
    out: dict[int, str] = {}

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            name = prefix
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}.{child.name}" if prefix else child.name
            for sub in ast.walk(child):
                out[id(sub)] = name
            visit(child, name)

    visit(tree, "")
    return out


def _named_lookups(tree: ast.AST, accounted: set[int]):
    """Every place a method is reached by a name the census cannot read, or by
    the name ``attest`` spelled as a string, or an EAS write is built outside
    the client: (qualname, line, problem)."""
    where = _qualnames(tree)
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or id(n) in accounted:
            continue
        f = n.func
        by_name = ((isinstance(f, ast.Name) and f.id == "getattr")
                   or (isinstance(f, ast.Attribute) and f.attr == "__getattribute__"))
        name_arg = n.args[1] if (isinstance(f, ast.Name) and len(n.args) >= 2) else (
            n.args[0] if (isinstance(f, ast.Attribute) and n.args) else None)
        if by_name and not (isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str)):
            yield where.get(id(n), ""), n.lineno, (
                "a method is reached by a name computed at run time; the census cannot "
                "tell it is not attest")
            continue
        spelled = [a for a in [*n.args, *(k.value for k in n.keywords)]
                   if isinstance(a, ast.Constant) and a.value == "attest"]
        if spelled:
            yield where.get(id(n), ""), n.lineno, (
                "attest is reached by its name as a string; the census cannot read its arguments")
            continue
        parts = _setattr_parts(n)
        deleting = ((isinstance(f, ast.Name) and f.id == "delattr")
                    or (isinstance(f, ast.Attribute) and f.attr == "__delattr__"))
        if (parts and not (isinstance(parts[1], ast.Constant) and isinstance(parts[1].value, str))) \
                or (deleting and not any(isinstance(a, ast.Constant) for a in n.args[1:2])):
            yield where.get(id(n), ""), n.lineno, (
                "an attribute is written by a name computed at run time; the census cannot "
                "tell which")
            continue
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
        loads = (isinstance(f, ast.Name) and name in ("exec", "eval", "compile", "__import__")) \
            or name == "import_module"
        if loads:
            yield where.get(id(n), ""), n.lineno, (
                f"code or a module is loaded at run time ({name}); the census cannot read it")
        elif name in ("vars", "globals", "locals"):
            yield where.get(id(n), ""), n.lineno, (
                f"a namespace is read or written by name ({name}); the census cannot tell which "
                "name")
        elif name.startswith(("get_function_by_", "find_functions_by_")):
            yield where.get(id(n), ""), n.lineno, (
                f"{_CONTRACT_LOOKUP} ({name}); the census cannot tell it is not an EAS write")
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and n.attr == "__dict__":
            yield where.get(id(n), ""), n.lineno, (
                "a namespace is read or written by name (__dict__); the census cannot tell "
                "which name")
        elif (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
              and n.slice.value == "attest"):
            yield where.get(id(n), ""), n.lineno, (
                "attest is reached by its name as a string; the census cannot read its arguments")
        elif (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Attribute)
              and n.value.attr == "functions" and not isinstance(n.slice, ast.Constant)):
            yield where.get(id(n), ""), n.lineno, (
                f"{_CONTRACT_LOOKUP} (functions[...]); the census cannot tell it is not an EAS "
                "write")
        elif isinstance(n, (ast.Import, ast.ImportFrom)) and any(
                (a.name or "").split(".")[0] == "importlib" for a in n.names) or (
                isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "importlib"):
            yield where.get(id(n), ""), n.lineno, (
                "code or a module is loaded at run time (importlib); the census cannot read it")
    for n in ast.walk(tree):
        write = None
        if isinstance(n, ast.Attribute) and n.attr in EAS_WRITES and isinstance(n.value, ast.Attribute) \
                and n.value.attr == "functions":
            write = n.attr
        elif (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Attribute)
              and n.value.attr == "functions" and isinstance(n.slice, ast.Constant)
              and n.slice.value in EAS_WRITES):
            write = n.slice.value
        if write:
            yield where.get(id(n), ""), n.lineno, (
                f"the EAS contract's {write} is built here, not through EASClient.attest; "
                "the census cannot read what it signs")


_CONTRACT_LOOKUP = "a contract function is looked up or chosen at run time"


def _nested(fn) -> set[int]:
    """The nodes inside a def or lambda nested in *fn*. Its parameters are
    bound by whatever calls it, so a field read through them is the request's
    under a name the walk does not know."""
    inner = set()
    for n in ast.walk(fn):
        if n is not fn and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            inner |= {id(sub) for sub in ast.walk(n)}
    return inner


def _census(source: str, filename: str, binds=_seam_binds):
    """Every ``.attest(`` call in the source: (tool, verb, method, line, problems).

    Beyond the calls it can read, it reports as a problem every place it could
    NOT follow the request to an attestation, as the module docstring lists
    them: ``attest`` taken as a value or reached by its name, an attribute
    reached by a computed name, an attestation outside a tool method, a
    rewritten or re-handed request, a splat, a nested function, a decorator, a
    name bound by ``except ... as``, ``global`` or ``nonlocal``, a request
    written onto ``self`` under a name it cannot read, and an EAS write built
    outside the client. A census that cannot see a site must not pass it."""
    tree = ast.parse(source, filename=filename)
    module = _module_facts(tree)
    handling = [f"the request may not arrive as it was written: {name} (line {line}): {why}"
                for name, line, why in _request_handling(tree)]
    accounted: set[int] = set()
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        tool, verbs = _tool_name(cls), _verbs(cls)
        handoffs, carried = _handoffs(cls), _carried(cls)
        opaque_store = _opaque_self_store(cls)
        execute_rewrapped = any(
            isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name == "execute"
            and _rewrapped(f) for f in cls.body)
        for fn in cls.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            roots = _roots(fn)
            tainted = _taint(fn, roots, carried)
            nested = _nested(fn)
            unread = _unread_bindings(tree, fn)
            called = {id(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call)}
            for ref in ast.walk(fn):
                aliased = (isinstance(ref, ast.Attribute) and ref.attr == "attest"
                           and id(ref) not in called)
                looked_up = (isinstance(ref, ast.Call) and isinstance(ref.func, ast.Name)
                             and ref.func.id == "getattr" and len(ref.args) >= 2
                             and isinstance(ref.args[1], ast.Constant)
                             and ref.args[1].value == "attest")
                if aliased or looked_up:
                    accounted.add(id(ref))
                    yield tool, verbs.get(fn.name), fn.name, ref.lineno, [
                        "attest is reached through an alias; the census cannot read its arguments"]
            for call in ast.walk(fn):
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "attest"):
                    continue
                accounted.add(id(call.func))
                verb = verbs.get(fn.name)
                kw = {k.arg: k.value for k in call.keywords if k.arg is not None}
                problems = list(handoffs.get(fn.name, []))
                if any(k.arg is None for k in call.keywords):
                    problems.append("arguments passed through ** splat; the census cannot "
                                    "read which of them is the recipient")
                if id(call) in nested:
                    problems.append("attest is called inside a function nested in a tool "
                                    "method; the census cannot follow the request into it")
                if _rewrapped(fn) or execute_rewrapped:
                    problems.append("a decorator stands between execute's caller and this "
                                    "method; the census cannot tell what it is handed")
                read = {n.id for part in ("action", "agent", "recipient") if part in kw
                        for n in ast.walk(kw[part]) if isinstance(n, ast.Name)}
                if read & unread:
                    problems.append(f"{sorted(read & unread)} bound by except-as, global or "
                                    "nonlocal; the census cannot follow what it holds")
                reads_self = any(isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                                 and n.value.id == "self"
                                 for part in ("action", "agent", "recipient") if part in kw
                                 for n in ast.walk(kw[part]))
                if opaque_store and reads_self:
                    problems.append(opaque_store)
                rewritten = _rewrites(fn, roots)
                if rewritten:
                    problems.append(rewritten)
                if call.args or not {"action", "agent"} <= set(kw):
                    problems.append("action/agent not passed by keyword; the census cannot read it")
                problems += handling
                walk = _walk_for(fn, module)
                traced = {}
                for part in ("action", "agent", "recipient"):
                    if part in kw:
                        untraced, traced[part] = _trace(kw[part], walk)
                        problems += [f"{part}: {p}" for p in dict.fromkeys(untraced)]
                for part in ("action", "agent"):
                    if part in kw and (_fields(kw[part], roots, tainted, carried)[0] or traced[part]):
                        if not (part == "agent" and (tool, verb) in AGENT_FROM_A_FIXED_SET):
                            problems.append(f"{part} is drawn from the request")
                if "recipient" in kw:
                    drawn, fields = _fields(kw["recipient"], roots, tainted, carried)
                    drawn, fields = drawn or bool(traced["recipient"]), fields | traced["recipient"]
                    bound = binds(tool, verb)
                    if drawn and (verb is None or "*" in fields or not fields <= bound):
                        problems.append(f"recipient is drawn from request field(s) "
                                        f"{sorted(fields - bound) or sorted(fields)} the seam does not bind")
                yield tool, verb, fn.name, call.lineno, problems
    for ref in ast.walk(tree):
        if (isinstance(ref, ast.Attribute) and ref.attr == "attest"
                and id(ref) not in accounted):
            accounted.add(id(ref))
            yield None, None, "<outside a tool method>", ref.lineno, [
                "attest is used outside a tool method; the census cannot tie it to a request"]
    for qualname, line, problem in _named_lookups(tree, accounted):
        yield None, None, qualname or "<module>", line, [problem]


#: The places in the twin directory that reach an attribute by a name computed
#: at run time, listed by name, each with why it reaches no EAS client. The walk
#: reports every such place; one not listed here fails the census, and a listed
#: one that no longer exists fails test_the_named_lookup_listing_is_exact.
NAMED_LOOKUPS = {
    ("sponsorship.py", "PlatformAddress.__getattr__"):
        "delegates attribute reads to the eth_account account it wraps; an "
        "account has no attest, and the handle's own sign_transaction refuses",
    ("sponsorship.py", "MeteredSigner.__getattr__"):
        "delegates attribute reads to the eth_account account it meters; an "
        "account has no attest",
    ("web3_manager.py", "Web3Manager.get_shared"):
        "reads rpc_url and chain_id, from a fixed two-entry table, to compare "
        "the live connection with a config; it calls nothing it reads (two sites)",
    ("web3_manager.py", "_receipt_field"):
        "reads a field of a transaction receipt; it calls nothing it reads",
}
_COMPUTED_NAME = "a method is reached by a name computed at run time"
#: The places in the twin directory that look a contract function up at run
#: time, each with why it signs nothing. The walk reports every such place.
CONTRACT_LOOKUPS = {
    ("smart_contracts.py", "SmartContracts._call"):
        "the read action: contract.functions[fn](*args).call(), an eth_call that "
        "signs and writes nothing (test_the_contract_lookup_listing_is_exact)",
}


def _all_twin_sites():
    for path in sorted(TWIN_DIR.glob("*.py")):
        if path.name == "eas_client.py":        # the client itself, not a caller
            continue
        for site in _census(path.read_text(encoding="utf-8"), str(path)):
            yield (path.name, *site)


def _listed(site) -> bool:
    f, _tool, _verb, method, _line, problems = site
    if len(problems) != 1:
        return False
    return (((f, method) in NAMED_LOOKUPS and problems[0].startswith(_COMPUTED_NAME))
            or ((f, method) in CONTRACT_LOOKUPS and problems[0].startswith(_CONTRACT_LOOKUP)))


def _twin_sites():
    for site in _all_twin_sites():
        if not _listed(site):
            yield site


def test_every_twin_attestation_is_the_platforms_own_statement():
    """[control] No action or agent from the request; no recipient but a bound one."""
    bad = [f"{f}:{line} {tool}.{verb} ({method}): {'; '.join(p)}"
           for f, tool, verb, method, line, p in _twin_sites() if p]
    assert bad == [], "twin attestations the request composes:\n  " + "\n  ".join(bad)
    found = {(tool, verb) for _f, tool, verb, *_ in _twin_sites()}
    # The walk must see the sites it vouches for — a census that finds nothing
    # passes everything. A new attestation site lands here by name.
    assert found == {
        ("agent_identity", "register"), ("identity", "register"),
        ("gaming", "record_achievement"), ("ip_royalties", "register_ip"),
        ("securities", "whitelist_investor"), ("crossborder_payment", "send"),
        ("insurance", "create_policy"), ("insurance", "file_claim"),
        ("supply_chain", "create_record"), ("supply_chain", "update_status"),
    }, found


def test_the_census_sees_a_planted_violation():
    """[guard] The walk is not vacuous: a request-written action and an unbound
    recipient, one hop through local names, are both caught; a request field
    that reaches only ``details`` (never written on-chain) is not flagged."""
    planted = (
        "class Planted:\n"
        "    @property\n"
        "    def name(self):\n"
        "        return 'planted'\n"
        "    async def execute(self, **kwargs):\n"
        "        action = kwargs.get('action')\n"
        "        if action == 'go':\n"
        "            return await self._go(kwargs)\n"
        "        elif action == 'fine':\n"
        "            return await self._fine(kwargs)\n"
        "    async def _go(self, params):\n"
        "        data = params.get('data', {})\n"
        "        who = params.get('to')\n"
        "        await client.attest(action=data.get('action', 'x'), agent='neo',\n"
        "                            details={}, recipient=who)\n"
        "    async def _fine(self, params):\n"
        "        await client.attest(action='fixed', agent='neo',\n"
        "                            details={'to': params.get('to')})\n"
    )
    sites = {verb: problems for _t, verb, _m, _l, problems
             in _census(planted, "<planted>", binds=lambda _tool, _verb: set())}
    assert any("action is drawn" in p for p in sites["go"]), sites
    assert any("recipient is drawn" in p and "'to'" in p for p in sites["go"]), sites
    assert sites["fine"] == [], sites


def test_the_census_reads_what_the_client_writes_on_chain():
    """[guard] EASClient.attest encodes (platform, action, agent, timestamp) and
    the recipient; ``details`` is accepted and not encoded. If that changes, the
    census above must learn to read ``details`` before this passes again."""
    tree = ast.parse((TWIN_DIR / "eas_client.py").read_text(encoding="utf-8"))
    encoded = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "encode" and len(node.args) == 2
                and isinstance(node.args[1], ast.List)):
            encoded = {e.slice.value for e in node.args[1].elts
                       if isinstance(e, ast.Subscript) and isinstance(e.slice, ast.Constant)}
            assert len(encoded) == len(node.args[1].elts), "an encoded value the census cannot name"
    assert encoded == {"platform", "action", "agent", "timestamp"}, encoded


# ── what a review planted that the walk above did not see ────────────────
#
# Three shapes re-opened the class and passed the census at fix/oldq-census
# 67f3ad6: execute rewriting the field before the method reads it, ``attest``
# reached through an alias, and a recipient carried on ``self`` from one method
# to another. An attestation outside any tool method was not seen either. Each
# test below plants one; at 67f3ad6 each fails [control], because the walk
# reports no problem.

_PLANTED_HEAD = (
    "class Planted:\n"
    "    @property\n"
    "    def name(self):\n"
    "        return 'gaming'\n"
)


def _problems(body: str, binds=lambda tool, verb: {"player_address"}) -> list[str]:
    return [p for *_site, problems in _census(_PLANTED_HEAD + body, "<planted>", binds=binds)
            for p in problems]


def test_the_census_sees_execute_rewrite_the_field():
    """[control] The field the method reads is bound; execute put the request's
    `to` under that name first."""
    rewritten_call = (
        "    async def execute(self, **kwargs):\n"
        "        if kwargs.get('action') == 'record_achievement':\n"
        "            return await self._record(\n"
        "                {**kwargs, 'player_address': kwargs.get('to')})\n"
        "    async def _record(self, params):\n"
        "        await client.attest(action='achievement', agent='neo', details={},\n"
        "                            recipient=params.get('player_address'))\n"
    )
    assert any("other than the request as it arrived" in p for p in _problems(rewritten_call))
    rewritten_first = (
        "    async def execute(self, **kwargs):\n"
        "        kwargs['player_address'] = kwargs.get('to')\n"
        "        if kwargs.get('action') == 'record_achievement':\n"
        "            return await self._record(kwargs)\n"
        "    async def _record(self, params):\n"
        "        await client.attest(action='achievement', agent='neo', details={},\n"
        "                            recipient=params.get('player_address'))\n"
    )
    assert any("rewritten" in p for p in _problems(rewritten_first))
    in_the_method = (
        "    async def execute(self, **kwargs):\n"
        "        if kwargs.get('action') == 'record_achievement':\n"
        "            return await self._record(kwargs)\n"
        "    async def _record(self, params):\n"
        "        params.update(player_address=params.get('to'))\n"
        "        await client.attest(action='achievement', agent='neo', details={},\n"
        "                            recipient=params.get('player_address'))\n"
    )
    assert any("rewritten" in p for p in _problems(in_the_method))


def test_the_census_sees_attest_through_an_alias():
    """[control]"""
    for alias in ("        sign = client.attest\n"
                  "        await sign(action=params.get('what'), agent='neo', details={})\n",
                  "        await getattr(client, 'attest')(action=params.get('what'), agent='neo', details={})\n"):
        planted = (
            "    async def execute(self, **kwargs):\n"
            "        if kwargs.get('action') == 'go':\n"
            "            return await self._go(kwargs)\n"
            "    async def _go(self, params):\n" + alias)
        assert any("through an alias" in p for p in _problems(planted)), alias


def test_the_census_sees_a_recipient_carried_on_self():
    """[control]"""
    planted = (
        "    async def execute(self, **kwargs):\n"
        "        self._who = kwargs.get('to')\n"
        "        if kwargs.get('action') == 'record_achievement':\n"
        "            return await self._record(kwargs)\n"
        "    async def _record(self, params):\n"
        "        await client.attest(action='achievement', agent='neo', details={},\n"
        "                            recipient=self._who)\n"
    )
    assert any("recipient is drawn" in p for p in _problems(planted))


def test_the_census_sees_an_attestation_outside_a_tool_method():
    """[control]"""
    source = (
        "async def _sign_for(params):\n"
        "    await client.attest(action=params.get('what'), agent='neo', details={})\n"
    )
    sites = list(_census(source, "<planted>"))
    assert sites and any("outside a tool method" in p for *_s, problems in sites for p in problems)


def test_the_hardened_census_still_passes_a_clean_site():
    """[guard] Stricter, not blind: the shape every twin uses passes."""
    clean = (
        "    async def execute(self, **kwargs):\n"
        "        if kwargs.get('action') == 'record_achievement':\n"
        "            return await self._record(kwargs)\n"
        "    async def _record(self, params):\n"
        "        who = params.get('player_address')\n"
        "        await client.attest(action='achievement', agent='neo', details={'x': 1},\n"
        "                            recipient=who)\n"
    )
    assert _problems(clean) == []


# ── two more shapes a later review planted past the walk ─────────────────
#
# At fix/oldq-census 7abfa21 both of these passed the census with no problem
# reported, although the commit before it said the walk reported every place
# it could not follow the request.

def test_the_census_sees_a_recipient_passed_through_a_keyword_splat():
    """[control]"""
    planted = (
        "    async def execute(self, **kwargs):\n"
        "        if kwargs.get('action') == 'record_achievement':\n"
        "            return await self._record(kwargs)\n"
        "    async def _record(self, params):\n"
        "        await client.attest(action='achievement', agent='neo', details={},\n"
        "                            **{'recipient': params.get('to')})\n"
    )
    assert any("splat" in p for p in _problems(planted)), _problems(planted)


def test_the_census_sees_an_attestation_inside_a_nested_function():
    """[control] The nested function's parameter is the request under a name the
    walk does not know."""
    for inner in (
        "        async def sign(p):\n"
        "            await client.attest(action='achievement', agent='neo', details={},\n"
        "                                recipient=p.get('to'))\n"
        "        await sign(params)\n",
        "        sign = lambda p: client.attest(action='achievement', agent='neo',\n"
        "                                       details={}, recipient=p.get('to'))\n"
        "        await sign(params)\n",
    ):
        planted = (
            "    async def execute(self, **kwargs):\n"
            "        if kwargs.get('action') == 'record_achievement':\n"
            "            return await self._record(kwargs)\n"
            "    async def _record(self, params):\n" + inner)
        assert any("nested" in p for p in _problems(planted)), (inner, _problems(planted))


# ── nine more places the walk could not follow the request ───────────────
#
# At fix/oldq-census a710052 each shape below passed the census with no problem
# reported: a name bound by ``with ... as``, by a ``match`` pattern or by
# ``except ... as``; the request stored on ``self`` by ``setattr`` or through
# ``self.__dict__``; ``attest`` reached by ``__getattribute__``, by a name built
# at run time or by ``operator.methodcaller``; and a decorator between
# ``execute`` and the method. The walk now follows the two it can read (``with``
# and ``match`` bind from what they are given) and reports the others.

_RECORD = (
    "    async def execute(self, **kwargs):\n"
    "        if kwargs.get('action') == 'record_achievement':\n"
    "            return await self._record(kwargs)\n"
)

NINE_SHAPES = {
    "with-as": (
        "    async def _record(self, params):\n"
        "        with hold(params.get('to')) as who:\n"
        "            await client.attest(action='a', agent='neo', details={}, recipient=who)\n",
        "recipient is drawn"),
    "match": (
        "    async def _record(self, params):\n"
        "        match params:\n"
        "            case {'to': who}:\n"
        "                await client.attest(action='a', agent='neo', details={}, recipient=who)\n",
        "recipient is drawn"),
    "except-as": (
        "    async def _record(self, params):\n"
        "        try:\n"
        "            raise Carry(params.get('to'))\n"
        "        except Carry as held:\n"
        "            await client.attest(action='a', agent='neo', details={},\n"
        "                                recipient=held.args[0])\n",
        "except-as"),
    "setattr": (
        "    async def _record(self, params):\n"
        "        setattr(self, 'who', params.get('to'))\n"
        "        await self._sign()\n"
        "    async def _sign(self):\n"
        "        await client.attest(action='a', agent='neo', details={}, recipient=self.who)\n",
        "recipient is drawn"),
    "__dict__": (
        "    async def _record(self, params):\n"
        "        self.__dict__['who'] = params.get('to')\n"
        "        await self._sign()\n"
        "    async def _sign(self):\n"
        "        await client.attest(action='a', agent='neo', details={}, recipient=self.who)\n",
        "stores the request on self"),
    "__getattribute__": (
        "    async def _record(self, params):\n"
        "        await client.__getattribute__('attest')(action='a', agent='neo', details={},\n"
        "                                                recipient=params.get('to'))\n",
        "by its name as a string"),
    "computed-name": (
        "    async def _record(self, params):\n"
        "        await getattr(client, 'att' + 'est')(action='a', agent='neo', details={},\n"
        "                                             recipient=params.get('to'))\n",
        "computed at run time"),
    "methodcaller": (
        "    async def _record(self, params):\n"
        "        await operator.methodcaller('attest', action='a', agent='neo', details={},\n"
        "                                    recipient=params.get('to'))(client)\n",
        "by its name as a string"),
    "decorator": (
        "    @moves('to', 'player_address')\n"
        "    async def _record(self, params):\n"
        "        await client.attest(action='a', agent='neo', details={},\n"
        "                            recipient=params.get('player_address'))\n",
        "decorator"),
}


@pytest.mark.parametrize("shape", sorted(NINE_SHAPES))
def test_the_census_reports_a_place_it_could_not_follow(shape):
    """[control]"""
    body, expected = NINE_SHAPES[shape]
    problems = _problems(_RECORD + body)
    assert any(expected in p for p in problems), (shape, problems)


def test_what_the_walk_now_follows_it_still_passes_when_bound():
    """[guard] Following ``match`` is reading it, not refusing it: a bound
    field through a capture passes, and so does a staticmethod beside the tool
    method. (A ``with ... as`` target is what the context manager's
    ``__enter__`` returns, which the census cannot name: handed the request, it
    is read as the request whole, and reported unless the seam binds all of it;
    test_a_with_target_is_the_request_whole.)"""
    for body in (
        "    async def _record(self, params):\n"
        "        match params:\n"
        "            case {'player_address': who}:\n"
        "                await client.attest(action='a', agent='neo', details={}, recipient=who)\n",
        "    @staticmethod\n"
        "    async def _unrelated(x):\n"
        "        return str(x)\n"
        "    async def _record(self, params):\n"
        "        await client.attest(action='a', agent='neo', details={},\n"
        "                            recipient=params.get('player_address'))\n",
    ):
        assert _problems(_RECORD + body) == [], (body, _problems(_RECORD + body))


def test_an_eas_write_outside_the_client_is_reported():
    """[control] The census reads ``EASClient.attest`` calls; an attestation or a
    revocation built on the contract directly never makes one."""
    body = (
        "    async def _record(self, params):\n"
        "        tx = eas.functions.multiRevoke([(SCHEMA, [(params['uid'], 0)])])\n"
        "        tx2 = eas.functions['attest']((SCHEMA, (ZERO, 0, True, b'', b'', 0)))\n"
    )
    problems = _problems(_RECORD + body)
    assert sum("not through EASClient.attest" in p for p in problems) == 2, problems


def test_the_only_eas_write_in_the_client_is_its_attest():
    """[guard] The premise the census rests on: the client the twins call
    reaches the EAS contract in two places, its ``attest`` (the one write, whose
    every call the walk reads) and its ``verify`` (a read). A new function of
    the contract lands here by name."""
    tree = ast.parse((TWIN_DIR / "eas_client.py").read_text(encoding="utf-8"))
    reached = sorted(
        (f"{cls.name}.{fn.name}", n.attr)
        for cls in tree.body if isinstance(cls, ast.ClassDef)
        for fn in cls.body if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
        for n in ast.walk(fn)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute)
        and n.value.attr == "functions")
    everywhere = [n for n in ast.walk(tree) if isinstance(n, (ast.Attribute, ast.Subscript))
                  and isinstance(n.value, ast.Attribute) and n.value.attr == "functions"]
    assert reached == [("EASClient.attest", "attest"), ("EASClient.verify", "getAttestation")], reached
    assert len(everywhere) == len(reached), "the contract is reached outside a method, or by subscript"


def test_the_named_lookup_listing_is_exact():
    """[guard, of the listing] Each listed place still reaches an attribute by a computed name,
    and nothing else in the twin directory does."""
    seen = [(f, method) for f, _t, _v, method, _l, problems in _all_twin_sites()
            for p in problems if p.startswith(_COMPUTED_NAME)]
    assert sorted(set(seen)) == sorted(NAMED_LOOKUPS), seen
    assert seen.count(("web3_manager.py", "Web3Manager.get_shared")) == 2, seen


def _imported(tree, package: str = "runtime.blockchain") -> set[str]:
    """Every module a twin module imports, a relative import resolved against
    *package* (``from . import x`` and ``from .x import y`` are
    runtime.blockchain.x; ``from .. import y`` is runtime.y)."""
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                base = ".".join(package.split(".")[: len(package.split(".")) - (n.level - 1)])
                if n.module:
                    out.add(f"{base}.{n.module}")
                else:
                    out |= {f"{base}.{a.name}" for a in n.names}
            elif n.module:
                out.add(n.module)
    return out


def test_a_relative_import_is_resolved():
    """[control] The premise below counted only names that start with
    ``runtime.``, so a relative import was never counted at all."""
    tree = ast.parse("from ..security import audit\nfrom . import eas_client\n"
                     "from .services.attestation import AttestationService\n")
    assert _imported(tree) == {"runtime.security", "runtime.blockchain.eas_client",
                               "runtime.blockchain.services.attestation"}, _imported(tree)


def test_the_twins_reach_no_attestation_the_walk_does_not_read():
    """[guard] The walk reads ``runtime/blockchain/*.py``. What a twin module
    imports from anywhere else under ``runtime/`` is named here, and none of it
    attests; a module loaded at run time is reported by the walk itself."""
    outside = {}
    for path in sorted(TWIN_DIR.glob("*.py")):
        for mod in _imported(ast.parse(path.read_text(encoding="utf-8"))):
            if mod.startswith("runtime.") and not (
                    mod.startswith("runtime.blockchain.") and mod.count(".") == 2):
                outside.setdefault(mod, set()).add(path.name)
    assert set(outside) <= {"runtime.access_policy", "runtime.protocols.outcome_truth",
                            "runtime.security.audit"}, outside
    for mod in outside:
        source = (ROOT / (mod.replace(".", "/") + ".py")).read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert not any(isinstance(n, ast.Attribute) and n.attr in ("attest", "EASClient")
                       for n in ast.walk(tree)), mod
        assert not any(isinstance(n, ast.Name) and n.id == "EASClient" for n in ast.walk(tree)), mod



# ── the fifth review's shapes, and the trace that closes the list ───────
#
# At this branch's signing-census commit ("The signing census reads every form
# that binds a name ...") each shape below passed the census with no problem
# reported, although the README said the walk reported every place it could
# not follow the request: a constant ``setattr`` spelled as a method call; a
# ``for`` or ``with`` target that is an attribute of ``self``; ``attest`` or a
# contract's attest reached through a class's ``__dict__``, ``vars()`` or a
# selector; a module dict, a ContextVar, a class attribute or ``exec`` carrying
# the request between methods; ``eval``; an attribute written inside a nested
# def; a local container handed elsewhere; a property; an attribute nothing
# writes. The walk now traces every value that reaches action, agent and
# recipient, and whatever it cannot trace it reports.

_TWO_METHODS = (
    "    async def _record(self, params):\n"
    "        {store}\n"
    "        await self._sign()\n"
    "    async def _sign(self):\n"
    "        await client.attest(action='a', agent='neo', details={{}}, recipient={read})\n"
)

FIFTH_REVIEW_SHAPES = {
    "setattr as a method call": ("", _TWO_METHODS.format(
        store="self.__setattr__('who', params.get('to'))", read="self.who"),
        "recipient is drawn"),
    "a for target on self": ("", _TWO_METHODS.format(
        store="for self.who in [params.get('to')]: pass", read="self.who"),
        "recipient is drawn"),
    "a with target on self": ("", _TWO_METHODS.format(
        store="with hold(params.get('to')) as self.who: pass", read="self.who"),
        "recipient is drawn"),
    "attest through a class's __dict__": ("",
        "    async def _record(self, params):\n"
        "        await EASClient.__dict__['attest'](client, action='a', agent='neo',\n"
        "                                           details={}, recipient=params.get('to'))\n",
        "(__dict__)"),
    "an EAS attest looked up by selector": ("",
        "    async def _record(self, params):\n"
        "        tx = eas.get_function_by_selector('0xf17325e7')(\n"
        "            (SCHEMA, (params.get('to'), 0, True, b'', b'', 0)))\n",
        "looked up or chosen at run time"),
    "a module dict between methods": ("_HELD = {}\n", _TWO_METHODS.format(
        store="_HELD['who'] = params.get('to')", read="_HELD['who']"),
        "_HELD is neither bound in this method nor an immutable constant"),
    "a ContextVar between methods": ("WHO = ContextVar('who')\n", _TWO_METHODS.format(
        store="WHO.set(params.get('to'))", read="WHO.get()"),
        "WHO is neither bound in this method nor an immutable constant"),
    "a class attribute written through type(self)": ("", _TWO_METHODS.format(
        store="type(self).who = params.get('to')", read="self.who"),
        "written through something other than self"),
    "exec of a string": ("", _TWO_METHODS.format(
        store="exec(\"self.who = params.get('to')\")", read="self.who"),
        "loaded at run time (exec)"),
    "eval of a string": ("",
        "    async def _record(self, params):\n"
        "        await client.attest(action='a', agent='neo', details={},\n"
        "                            recipient=eval(\"params.get('to')\"))\n",
        "loaded at run time (eval)"),
    "attest through type(client).__dict__": ("",
        "    async def _record(self, params):\n"
        "        await type(client).__dict__['attest'](client, action='a', agent='neo',\n"
        "                                              details={}, recipient=params.get('to'))\n",
        "(__dict__)"),
    "attest through vars()": ("",
        "    async def _record(self, params):\n"
        "        await vars(EASClient)['attest'](client, action='a', agent='neo',\n"
        "                                        details={}, recipient=params.get('to'))\n",
        "(vars)"),
    "an attribute written in a nested def": ("", _TWO_METHODS.format(
        store="stash = lambda p: setattr(self, 'who', p.get('to')); stash(params)",
        read="self.who"),
        "outside a method's own body"),
    "a local container handed elsewhere": ("",
        "    async def _record(self, params):\n"
        "        held = {}\n"
        "        stash(held, params)\n"
        "        await client.attest(action='a', agent='neo', details={}, recipient=held['to'])\n",
        "handed elsewhere"),
    "a property": ("_HELD = {}\n",
        "    @property\n"
        "    def who(self):\n"
        "        return _HELD['who']\n"
        "    async def _record(self, params):\n"
        "        await client.attest(action='a', agent='neo', details={}, recipient=self.who)\n",
        "a method or property"),
    "an attribute nothing writes": ("",
        "    async def _record(self, params):\n"
        "        await client.attest(action='a', agent='neo', details={}, recipient=self.target)\n",
        "never written in this module"),
    "an attribute written by a computed name": ("",
        "    async def _record(self, params):\n"
        "        setattr(holder, params.get('field'), params.get('to'))\n"
        "        await client.attest(action='a', agent='neo', details={}, recipient=holder.to)\n",
        "written by a name computed at run time"),
}


def _problems_with(prelude: str, body: str) -> list[str]:
    source = prelude + _PLANTED_HEAD + _RECORD + body
    return [p for *_site, problems in _census(source, "<planted>", binds=lambda t, v: {"player_address"})
            for p in problems]


@pytest.mark.parametrize("shape", sorted(FIFTH_REVIEW_SHAPES))
def test_the_census_reports_every_value_it_cannot_trace(shape):
    """[control]"""
    prelude, body, expected = FIFTH_REVIEW_SHAPES[shape]
    problems = _problems_with(prelude, body)
    assert any(expected in p for p in problems), (shape, problems)


def test_a_with_target_is_the_request_whole():
    """[guard] ``with hold(x) as who`` binds what ``hold(x).__enter__()``
    returns. Handed the request, it is read as the request whole, so even a
    bound field through it is reported."""
    body = ("    async def _record(self, params):\n"
            "        with hold(params.get('player_address')) as who:\n"
            "            await client.attest(action='a', agent='neo', details={}, recipient=who)\n")
    assert any("recipient is drawn from request field(s) ['*']" in p
               for p in _problems_with("", body)), _problems_with("", body)


def test_the_trace_still_passes_what_the_twins_write():
    """[guard] Stricter, not blind: the shapes the real sites use pass — a
    constant, a bound field with a constant default, a local bound from one and
    read through a conditional, a module constant, a converted string."""
    body = ("    async def _record(self, params):\n"
            "        who = params.get('player_address', ZERO)\n"
            "        name = str(params.get('player_address') or '').strip().lower()\n"
            "        await client.attest(action=ACTION, agent='neo', details={},\n"
            "                            recipient=who if who else name)\n")
    assert _problems_with("ZERO = '0x' + '0' * 40\nACTION = 'achievement'\n", body) == [], \
        _problems_with("ZERO = '0x' + '0' * 40\nACTION = 'achievement'\n", body)


def test_the_base_attributes_are_the_configurations():
    """[guard] Each attribute the trace takes from the base class is written,
    anywhere in the directory, only in an ``__init__`` and only from the
    configuration's blockchain section."""
    for attr in BASE_ATTRIBUTES:
        writes = []
        for path in sorted(TWIN_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for n in ast.walk(fn):
                    if isinstance(n, ast.Assign) and any(
                            isinstance(t, ast.Attribute) and t.attr == attr for t in n.targets):
                        writes.append((path.name, fn.name, ast.unparse(n.value)))
        assert writes and all(fn == "__init__" and value == f"bc.get('{attr}', '')"
                              for _f, fn, value in writes), writes
        assert "interface.py" in {f for f, _fn, _v in writes}, writes


def test_the_contract_lookup_listing_is_exact():
    """[guard, of the listing] The one place in the directory that looks a
    contract function up at run time calls it as a read and nothing else."""
    seen = {(f, method) for f, _t, _v, method, _l, problems in _all_twin_sites()
            for p in problems if p.startswith(_CONTRACT_LOOKUP)}
    assert seen == set(CONTRACT_LOOKUPS), seen
    tree = ast.parse((TWIN_DIR / "smart_contracts.py").read_text(encoding="utf-8"))
    parents = _parents(tree)
    for n in ast.walk(tree):
        if (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Attribute)
                and n.value.attr == "functions"):
            called = parents[id(n)]
            used = parents[id(called)]
            assert isinstance(called, ast.Call) and called.func is n, ast.unparse(called)
            assert isinstance(used, ast.Attribute) and used.attr == "call", ast.unparse(used)
            assert isinstance(parents[id(used)], ast.Call), "a read, called"



# ── the request changed before its field is read ────────────────────────
#
# A field the seam binds is only the caller's if the request still says what
# the caller wrote when the field is read. At the attestation-trace commit
# ("The attestation census traces every value ...") each shape below passed:
# the request rewritten by another method, through a local name bound to it,
# through an attribute or a container it was put in, by a function outside
# the module, or by the caller of a method that returned it.

_READS_BOUND = ("        await client.attest(action='a', agent='neo', details={},\n"
                "                            recipient=params.get('player_address'))\n")

REQUEST_CHANGED_SHAPES = {
    "another method rewrites it": (
        "    async def execute(self, **kwargs):\n"
        "        self._stash(kwargs)\n"
        "        if kwargs.get('action') == 'record_achievement':\n"
        "            return await self._record(kwargs)\n"
        "    def _stash(self, p):\n"
        "        p['player_address'] = p.get('to')\n"
        "    async def _record(self, params):\n" + _READS_BOUND),
    "a name bound to it": (
        _RECORD +
        "    async def _record(self, params):\n"
        "        alias = params\n"
        "        alias['player_address'] = params.get('to')\n" + _READS_BOUND),
    "an attribute it is stored in": (
        _RECORD +
        "    async def _record(self, params):\n"
        "        self._held = params\n"
        "        self._swap()\n" + _READS_BOUND +
        "    def _swap(self):\n"
        "        self._held['player_address'] = self._held.get('to')\n"),
    "a function outside the module": (
        _RECORD +
        "    async def _record(self, params):\n"
        "        normalize(params)\n" + _READS_BOUND),
    "a container it is put in": (
        _RECORD +
        "    async def _record(self, params):\n"
        "        box = [params]\n"
        "        box[0]['player_address'] = params.get('to')\n" + _READS_BOUND),
    "the caller of a method that returns it": (
        _RECORD +
        "    def _same(self, p):\n"
        "        return p\n"
        "    async def _record(self, params):\n"
        "        q = self._same(params)\n"
        "        q['player_address'] = params.get('to')\n" + _READS_BOUND),
}


@pytest.mark.parametrize("shape", sorted(REQUEST_CHANGED_SHAPES))
def test_the_census_reports_a_request_that_may_have_changed(shape):
    """[control]"""
    problems = _problems(REQUEST_CHANGED_SHAPES[shape])
    assert any("may not arrive as it was written" in p for p in problems), (shape, problems)


# At the commit that added the shapes above ("Both censuses report a value
# changed through another name ...") each of these passed with nothing
# reported: the walk followed a name bound to the request only by a plain
# assignment of the name itself, and read an ``and``/``or``, a conditional and
# a ``match`` over it as a test.

REQUEST_ALIASED_SHAPES = {
    "a name bound through or": (
        _RECORD +
        "    async def _record(self, params):\n"
        "        q = params or {}\n"
        "        q['player_address'] = params.get('to')\n" + _READS_BOUND),
    "a name bound through a conditional": (
        _RECORD +
        "    async def _record(self, params):\n"
        "        q = params if params else {}\n"
        "        q['player_address'] = params.get('to')\n" + _READS_BOUND),
    "a match capture with as": (
        _RECORD +
        "    async def _record(self, params):\n"
        "        match params:\n"
        "            case dict() as q:\n"
        "                q['player_address'] = params.get('to')\n" + _READS_BOUND),
    "a bare match capture": (
        _RECORD +
        "    async def _record(self, params):\n"
        "        match params:\n"
        "            case q:\n"
        "                q['player_address'] = params.get('to')\n" + _READS_BOUND),
    "a module function through a conditional": (
        _RECORD +
        "    async def _record(self, params):\n"
        "        fill(params)\n" + _READS_BOUND +
        "def fill(p):\n"
        "    q = p if p else {}\n"
        "    q['player_address'] = p.get('to')\n"),
    "a request handed on through or": (
        _RECORD +
        "    async def _record(self, params):\n"
        "        normalize(params or {})\n" + _READS_BOUND),
}


@pytest.mark.parametrize("shape", sorted(REQUEST_ALIASED_SHAPES))
def test_the_census_reports_a_request_changed_through_an_alias(shape):
    """[control]"""
    problems = _problems(REQUEST_ALIASED_SHAPES[shape])
    assert any("may not arrive as it was written" in p for p in problems), (shape, problems)


def test_a_request_tested_through_and_or_still_passes():
    """[guard] An and/or or a conditional that only tests the request or
    converts it, and a match that only reads it, change nothing and pass."""
    body = (_RECORD +
        "    async def _record(self, params):\n"
        "        kind = 'x' if params and params.get('kind') else 'y'\n"
        "        label = str(params or '')\n"
        "        match params:\n"
        "            case {'kind': k}:\n"
        "                kind = k\n"
        "        await client.attest(action='a', agent='neo', details={'k': kind, 'l': label},\n"
        "                            recipient=params.get('player_address'))\n")
    assert _problems(body) == [], _problems(body)


def test_a_request_only_read_still_passes():
    """[guard] Reading a field, looking a key up, testing, matching and
    handing the request to a method of the class or a function of the module
    change nothing, and pass."""
    body = (
        "    async def execute(self, **kwargs):\n"
        "        if kwargs.get('action') == 'record_achievement':\n"
        "            if 'player_address' in kwargs:\n"
        "                return await self._record(kwargs)\n"
        "    async def _record(self, params):\n"
        "        kind = TABLE.get(params.get('kind'), 'x')\n"
        "        label = f\"{params}\"\n"
        "        await client.attest(action='a', agent='neo', details={'k': kind, 'l': label},\n"
        "                            recipient=params.get('player_address'))\n")
    assert _problems(body) == [], _problems(body)



def test_an_attribute_hook_in_the_module_is_reported():
    """[control] With ``__getattr__`` or ``__getattribute__`` in the class, a
    ``self`` attribute the source writes from a bound field is not what a read
    returns. At the attestation-trace commit this passed with nothing reported."""
    body = (_RECORD +
            "    def __init__(self, config):\n"
            "        self.who = '0x' + '0' * 40\n"
            "    def __getattribute__(self, name):\n"
            "        return HELD.get(name)\n"
            "    async def _record(self, params):\n"
            "        HELD['who'] = params.get('to')\n"
            "        await client.attest(action='a', agent='neo', details={}, recipient=self.who)\n")
    assert any("the module defines __getattribute__" in p for p in _problems(body)), _problems(body)


def test_no_class_a_twin_inherits_from_hooks_its_attributes():
    """[guard] The trace reads a twin's own module. What a twin inherits comes
    from BlockchainInterface (runtime/blockchain/interface.py), whose attribute
    reads and writes run no hook of its own, and from ABC."""
    tree = ast.parse((TWIN_DIR / "interface.py").read_text(encoding="utf-8"))
    (base,) = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BlockchainInterface"]
    assert [ast.unparse(b) for b in base.bases] == ["ABC"] and not base.keywords
    defined = {n.name for n in base.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert not defined & _ATTRIBUTE_HOOKS, defined & _ATTRIBUTE_HOOKS
    for path in sorted(TWIN_DIR.glob("*.py")):
        if path.name == "eas_client.py":        # the client itself, not a caller
            continue
        source = path.read_text(encoding="utf-8")
        for cls in (n for n in ast.parse(source).body if isinstance(n, ast.ClassDef)):
            if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                   and c.func.attr == "attest" for c in ast.walk(cls)):
                assert [ast.unparse(b) for b in cls.bases] == ["BlockchainInterface"], (
                    path.name, cls.name, [ast.unparse(b) for b in cls.bases])
