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
the recipient through a field the seam does not bind for that tool and verb. The
trace reads assignments, loops, comprehensions, ``with ... as`` and ``match``
patterns, and a request stored on ``self`` by assignment or by
``setattr(self, "name", ...)``.

Where it cannot follow the request it fails too, and says why: ``attest`` taken
as a value; ``attest`` reached by its name as a string (``getattr``,
``__getattribute__``, ``operator.methodcaller``); any attribute reached by a
name computed at run time; an attestation outside a tool method; a method
``execute`` hands a rewritten request; a request rewritten before it is read;
arguments passed through a ``*`` or ``**`` splat; an attestation inside a def
or lambda nested in a tool method; a decorator between ``execute``'s caller and
the method; a name bound by ``except ... as``, ``global`` or ``nonlocal``; a
request written onto ``self`` through ``self.__dict__``, ``vars(self)`` or a
``setattr`` with a computed name; and the EAS contract's attest or revoke (or
any other write it offers) built anywhere but inside ``EASClient.attest``. Four
places in the directory reach an attribute by a computed name and no EAS
client, and are listed by name with the reason (``NAMED_LOOKUPS``). Planted
shapes prove the walk reports each of these. Two guards keep it honest about
the client: ``EASClient`` reaches the contract only in ``attest`` and in
``verify``'s read, and if it ever encodes ``details``, the census has to learn
to read them.

WHAT THIS DOES NOT COVER, stated. The services layer
(``runtime/blockchain/services/``) has its own attestation service; its three
request-facing actions are refused at every door that dispatches them
(tests/test_no_request_makes_the_attestation_service_sign.py), but the records
the services write about operations they ran are not walked here. A bound
subject is not a verified statement: an achievement, an IP claim or an
investor's whitelisting recorded for the caller's own address is still the
caller's word. The walk follows the request through local names, ``self``
attributes and ``execute``'s hand-off, and reports a name another function
binds as a global; through another object's state it does not follow it, and
what another method returns counts as the request only when that method is
handed the request. It reads source, so a method replaced at run time
(monkeypatching, a metaclass) is outside it. An attestation
signed through a contract call whose function the request chose never reaches
``EASClient.attest``, so this walk cannot see one; the census of every signing
call (tests/test_no_request_chooses_the_call_the_platform_key_signs.py) is
what rules that out.

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
"""

from __future__ import annotations

import ast
import asyncio
import json
import pathlib
import sys

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
                elif (_is_setattr_on_self(n) and isinstance(n.args[1], ast.Constant)
                        and isinstance(n.args[1].value, str)):
                    stores = [(ast.Attribute(value=ast.Name(id="self", ctx=ast.Load()),
                                             attr=n.args[1].value, ctx=ast.Store()), n.args[2])]
                for target, value in stores:
                    if not _fields(value, roots, tainted, frozenset(carried))[0]:
                        continue
                    for sub in ast.walk(target):
                        if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                                and sub.value.id == "self" and sub.attr not in carried):
                            carried.add(sub.attr)
                            changed = True
    return frozenset(carried)


def _is_setattr_on_self(n: ast.AST) -> bool:
    """``setattr(self, name, value)`` or ``object.__setattr__(self, name, value)``."""
    if not (isinstance(n, ast.Call) and len(n.args) == 3
            and isinstance(n.args[0], ast.Name) and n.args[0].id == "self"):
        return False
    f = n.func
    return ((isinstance(f, ast.Name) and f.id == "setattr")
            or (isinstance(f, ast.Attribute) and f.attr == "__setattr__"))


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
            if _is_setattr_on_self(n) and not (isinstance(n.args[1], ast.Constant)
                                               and isinstance(n.args[1].value, str)):
                values = [n.args[2]]
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
                for part in ("action", "agent"):
                    if part in kw and _fields(kw[part], roots, tainted, carried)[0]:
                        if not (part == "agent" and (tool, verb) in AGENT_FROM_A_FIXED_SET):
                            problems.append(f"{part} is drawn from the request")
                if "recipient" in kw:
                    drawn, fields = _fields(kw["recipient"], roots, tainted, carried)
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


def _all_twin_sites():
    for path in sorted(TWIN_DIR.glob("*.py")):
        if path.name == "eas_client.py":        # the client itself, not a caller
            continue
        for site in _census(path.read_text(encoding="utf-8"), str(path)):
            yield (path.name, *site)


def _listed(site) -> bool:
    f, _tool, _verb, method, _line, problems = site
    return ((f, method) in NAMED_LOOKUPS and len(problems) == 1
            and problems[0].startswith(_COMPUTED_NAME))


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
    """[guard] Following ``with`` and ``match`` is reading them, not refusing
    them: a bound field through either passes."""
    for body in (
        "    async def _record(self, params):\n"
        "        with hold(params.get('player_address')) as who:\n"
        "            await client.attest(action='a', agent='neo', details={}, recipient=who)\n",
        "    async def _record(self, params):\n"
        "        match params:\n"
        "            case {'player_address': who}:\n"
        "                await client.attest(action='a', agent='neo', details={}, recipient=who)\n",
        "    @staticmethod\n"
        "    async def _unrelated(x):\n"
        "        return x\n"
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


def test_the_twins_reach_no_attestation_the_walk_does_not_read():
    """[guard] The walk reads ``runtime/blockchain/*.py``. What a twin module
    imports from anywhere else is named here, and none of it attests: so the
    walk reads every attestation these tools make."""
    outside = {}
    for path in sorted(TWIN_DIR.glob("*.py")):
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods = ([n.module] if isinstance(n, ast.ImportFrom) and n.module
                    else [a.name for a in n.names] if isinstance(n, ast.Import) else [])
            for mod in mods:
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
