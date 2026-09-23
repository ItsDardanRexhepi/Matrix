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

THE CENSUS. The walk reads the source of every twin tool, finds every
``.attest(`` call, traces its ``action``, ``agent`` and ``recipient`` back to the
request, and fails if a request field reaches the action or the agent, or reaches
the recipient through a field the seam does not bind for that tool and verb. It
also fails wherever it cannot follow the request: ``attest`` taken as a value,
an attestation outside a tool method, a method ``execute`` hands a rewritten
request, a request rewritten before it is read, and a request carried on
``self`` from one method to another. Planted violations prove the walk sees
each of those. A guard keeps the walk honest about what ``EASClient`` actually
writes on-chain: if it ever encodes ``details``, the census has to learn to
read them.

WHAT THIS DOES NOT COVER, stated. The services layer
(``runtime/blockchain/services/``) has its own attestation service; its three
request-facing actions are refused at every door that dispatches them
(tests/test_no_request_makes_the_attestation_service_sign.py), but the records
the services write about operations they ran are not walked here. A bound
subject is not a verified statement: an achievement, an IP claim or an
investor's whitelisting recorded for the caller's own address is still the
caller's word. And the walk follows the request through local names, ``self``
attributes and ``execute``'s hand-off; through another object's state, a module
global or what another method returns, it does not follow it.

CONTROL. At The Matrix ``main`` b478b51, and on the first repair (fix/oldq-census
9102bde), the 12 tests marked [control] before the planted-shape section fail;
the 9 marked [guard] pass before and after — they pin what must keep working
(the caller's own address, an absent field, a payment to somebody else) and
that the census can see what it looks for. At 083ed72 the four [control] tests
in the planted-shape section fail and its [guard] passes.
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
                for target, value in stores:
                    if not _fields(value, roots, tainted, frozenset(carried))[0]:
                        continue
                    for sub in ast.walk(target):
                        if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                                and sub.value.id == "self" and sub.attr not in carried):
                            carried.add(sub.attr)
                            changed = True
    return frozenset(carried)


def _census(source: str, filename: str, binds=_seam_binds):
    """Every ``.attest(`` call in the source: (tool, verb, method, line, problems).

    Beyond the calls it can read, it reports as a problem every place it could
    NOT follow the request to an attestation: ``attest`` taken as a value
    (``sign = client.attest``, ``getattr(client, "attest")``), an attestation
    outside a tool method, a method ``execute`` hands a rewritten request, and a
    request carried on ``self`` between methods. A census that cannot see a
    site must not pass it."""
    tree = ast.parse(source, filename=filename)
    accounted: set[int] = set()
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        tool, verbs = _tool_name(cls), _verbs(cls)
        handoffs, carried = _handoffs(cls), _carried(cls)
        for fn in cls.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            roots = _roots(fn)
            tainted = _taint(fn, roots, carried)
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
                kw = {k.arg: k.value for k in call.keywords}
                problems = list(handoffs.get(fn.name, []))
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
            yield None, None, "<outside a tool method>", ref.lineno, [
                "attest is used outside a tool method; the census cannot tie it to a request"]


def _twin_sites():
    for path in sorted(TWIN_DIR.glob("*.py")):
        if path.name == "eas_client.py":        # the client itself, not a caller
            continue
        for site in _census(path.read_text(encoding="utf-8"), str(path)):
            yield (path.name, *site)


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
# 083ed72: execute rewriting the field before the method reads it, ``attest``
# reached through an alias, and a recipient carried on ``self`` from one method
# to another. An attestation outside any tool method was not seen either. Each
# test below plants one; at 083ed72 each fails [control], because the walk
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
