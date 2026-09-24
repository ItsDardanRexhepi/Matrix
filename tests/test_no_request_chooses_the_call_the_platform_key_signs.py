"""No request chooses the call the platform's key signs.

THE DEFECT (a security review of fix/oldq-census). Neo's ``smart_contract`` tool
had a ``send`` action. It built ``contract.functions[function_name](*args)``
against the ``contract_address`` and ``abi`` the request wrote, with the
request's ``value``, and signed it with the platform's key from the platform
wallet. Pointed at the EAS contract with EASClient's own ABI it signed an
``attest`` whose schema, recipient and data the request wrote (a platform
"agent_registration" for any name, which ``agent_identity.verify`` accepts)
and a ``revoke`` of any uid; pointed at an NFT contract, a
``transferFrom(B, A, id)``. Each of those effects is refused where it has a
name: ``eas`` attest, batch_attest and revoke, ``nft.transfer``'s
``from_address``. This one tool made all of them again, under a verb the seam
has no field to check. Its reach is ``eas``'s: Neo's tools, which the operator's
chat holds.

The second layer did not hold either. ``MeteredSigner`` consulted the
sponsorship policy only when a daily cap was set, so an operator who set
``allowed_actions`` and no cap had every capability signature signed whatever
the list said.

THE CHANGE. ``smart_contract`` writes nothing: ``send`` is answered with a
refusal before anything is built or signed, as ``deploy`` already was, and it
leaves the action enum. ``MeteredSigner`` checks a configured allowlist on every
signature, cap or no cap.

THE CLASS, AND THE CENSUS. A platform signature on a call whose function the
request chose: the platform wallet becomes the sender of a call somebody else
wrote. The walk reads every module under ``runtime/`` and ``gateway/``, finds
every ``sign_transaction(`` and ``send_transaction(`` call, and follows what is
signed back to where it is built. It fails on a transaction built from a
function looked up at run time (``functions[...]``, ``getattr``,
``get_function_by_*``), on a transaction dict whose ``data`` comes from what
the function was handed, on one it unpacks or updates from that, and wherever
it cannot read what is signed. Three kinds of site are listed by name instead,
each for a stated reason: the two signers that sign what their caller hands
them (every caller is itself a site the walk reads), the two deployments
(``tests/test_no_deployment_claims.py`` and the ``conversion.auto_deploy``
switch govern those), and ``GasSponsor.sponsor_transaction``, which signs
whatever it is handed and which nothing calls, pinned here. Every other signed
call names its function in the source. Its arguments may still come from the
request; which of them must be the caller's own is the seam's table
(``ACTION_BENEFICIARY_FIELDS``) and the gate's classification.

WHAT THIS DOES NOT COVER, stated. A call the platform's key signs to a
contract that then makes another call the request wrote: ``governance``
schedule_operation and execute_operation (a timelock's target, value and
data), ``dao`` create_proposal (a governor's targets and calldatas). The
function the platform calls is fixed there, and what the inner call can do
rests on a role the platform holds on a contract the request names, a
deployment fact this repository cannot see. Nor does it cover a message the
platform signs rather than a transaction (the paymaster's sponsorship
signature is over an operation the caller's own account executes).

CONTROL. At fix/oldq-census 420a88a the tests marked [control] fail; the
[guard] tests pass before and after.
"""

from __future__ import annotations

import ast
import asyncio
import json
import pathlib
import sys
from unittest.mock import MagicMock

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
A = "0x" + "a1" * 20      # the caller's bound identity
B = "0x" + "b2" * 20      # somebody else
EAS = "0x" + "4e" * 20
NFT = "0x" + "5f" * 20
SCHEMA = "0x" + "cd" * 32
CFG = {"blockchain": {
    "network": "base-sepolia", "rpc_url": "http://127.0.0.1:1",
    "paymaster_private_key": "0x" + "1" * 64, "platform_wallet": A,
    "eas_contract": EAS, "eas_schema": SCHEMA}}


def _eas_abi():
    from runtime.blockchain.eas_client import EAS_ATTEST_ABI
    return EAS_ATTEST_ABI


_REVOKE_ABI = [{"inputs": [{"components": [
    {"name": "schema", "type": "bytes32"},
    {"components": [{"name": "uid", "type": "bytes32"}, {"name": "value", "type": "uint256"}],
     "name": "data", "type": "tuple"}], "name": "request", "type": "tuple"}],
    "name": "revoke", "outputs": [], "stateMutability": "payable", "type": "function"}]
_TRANSFER_FROM_ABI = [{"inputs": [{"name": "from", "type": "address"},
                                  {"name": "to", "type": "address"},
                                  {"name": "tokenId", "type": "uint256"}],
                       "name": "transferFrom", "outputs": [],
                       "stateMutability": "nonpayable", "type": "function"}]

#: The three calls the review had the platform key sign through ``send``.
SENDS = {
    "an EAS attestation the request wrote": lambda: {
        "contract_address": EAS, "abi": _eas_abi(), "function_name": "attest",
        "args": [[SCHEMA, [B, 0, True, "0x" + "00" * 32, "0x" + "ab" * 64, 0]]]},
    "a revocation of any uid": lambda: {
        "contract_address": EAS, "abi": _REVOKE_ABI, "function_name": "revoke",
        "args": [[SCHEMA, ["0x" + "ef" * 32, 0]]]},
    "an NFT moved from somebody else": lambda: {
        "contract_address": NFT, "abi": _TRANSFER_FROM_ABI,
        "function_name": "transferFrom", "args": [B, A, 1]},
}


@pytest.fixture
def signer_reached(monkeypatch):
    """Every platform signer the smart_contract tool asks for."""
    from runtime.blockchain.smart_contracts import SmartContracts
    reached = []

    async def spy(self, what):
        reached.append(what)
        raise RuntimeError("stopped at the platform signer by the test")

    monkeypatch.setattr(SmartContracts, "_platform_signer", spy)
    monkeypatch.setattr(SmartContracts, "web3", property(lambda self: MagicMock()))
    return reached


# ── the tool ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("case", sorted(SENDS))
def test_smart_contract_signs_no_call_the_request_wrote(case, signer_reached):
    """[control]"""
    from runtime.blockchain.smart_contracts import SmartContracts
    out = json.loads(asyncio.run(SmartContracts(CFG).execute(action="send", **SENDS[case]())))
    assert signer_reached == [], f"{case}: the request's call reached the platform signer"
    assert out.get("ok") is False and out.get("code") == "denied", out


async def test_through_the_seam_as_the_tool_loop_calls_it(signer_reached):
    """[control] The real pre_action, then the tool, as react_loop runs them.
    The seam has no field to check on ``send`` and the gate runs OBSERVE without
    the private package, so the tool itself has to refuse."""
    sys.path.insert(0, str(ROOT / "tests"))
    from test_twins_seam import _stack

    from runtime.blockchain.smart_contracts import SmartContracts
    args = {"action": "send", **SENDS["an EAS attestation the request wrote"]()}
    verdict = await _stack().pre_action("smart_contract", args, {"wallet": A})
    assert verdict["approved"] is True, "precondition: the seam passes it to an approving gate"
    out = json.loads(await SmartContracts(CFG).execute(**args))
    assert signer_reached == [], "the request's call reached the platform signer"
    assert out.get("ok") is False and out.get("code") == "denied", out


def test_the_tool_offers_no_write():
    """[control] A model reads the schema to choose an action; ``send`` is not
    in it, and the description does not promise writes."""
    from runtime.blockchain.smart_contracts import SmartContracts
    tool = SmartContracts(CFG)
    assert "send" not in tool.parameters["properties"]["action"]["enum"]
    assert "value" not in tool.parameters["properties"], "an ETH value is only for a write"
    assert "gas for writes" not in tool.description.lower(), tool.description


def test_a_read_still_reads_and_signs_nothing(signer_reached):
    """[guard] ``call`` is a read: an eth_call, no signature."""
    from runtime.blockchain.smart_contracts import SmartContracts
    out = json.loads(asyncio.run(SmartContracts(CFG).execute(
        action="call", contract_address=NFT, abi=_TRANSFER_FROM_ABI,
        function_name="transferFrom", args=[B, A, 1])))
    assert signer_reached == []
    assert "result" in out, out


# ── the second layer: the allowlist with no cap ──────────────────────────

class _Account:
    address = A

    def sign_transaction(self, tx):
        return "signed"


_TX = {"to": NFT, "value": 0, "gas": 21000, "gasPrice": 10**9, "nonce": 0, "chainId": 84532}


def test_a_configured_allowlist_binds_with_no_cap(tmp_path):
    """[control]"""
    from runtime.blockchain.sponsorship import (
        MeteredSigner, SponsorshipDenied, SponsorshipPolicy)
    policy = SponsorshipPolicy(allowed_actions=["nfts.transfer"], daily_cap_usd=None,
                               db_path=tmp_path / "spend.db")
    signer = MeteredSigner(_Account(), policy, "smart_contracts.send", A, None)
    with pytest.raises(SponsorshipDenied) as refused:
        signer.sign_transaction(_TX)
    assert refused.value.decision.code == "action_not_allowed"


async def test_the_signer_a_capability_gets_reads_the_allowlist(tmp_path, monkeypatch):
    """[control] Built from configuration, as every capability's
    ``_platform_signer`` builds it."""
    from runtime.blockchain.sponsorship import SponsorshipDenied, platform_signer
    monkeypatch.setattr("eth_account.Account.from_key", staticmethod(lambda _k: _Account()))
    cfg = {"blockchain": {**CFG["blockchain"],
                          "paymaster": {"policy": {"allowed_actions": ["nfts.transfer"]}}},
           "database": {"path": str(tmp_path / "x.db")}}
    signer = await platform_signer(cfg, "smart_contracts.send")
    with pytest.raises(SponsorshipDenied):
        signer.sign_transaction(_TX)


def test_a_listed_action_with_no_cap_still_signs(tmp_path):
    """[guard]"""
    from runtime.blockchain.sponsorship import MeteredSigner, SponsorshipPolicy
    policy = SponsorshipPolicy(allowed_actions=["nfts.transfer"], daily_cap_usd=None,
                               db_path=tmp_path / "spend.db")
    assert MeteredSigner(_Account(), policy, "nfts.transfer", A, None).sign_transaction(_TX) == "signed"


def test_no_policy_at_all_still_signs(tmp_path):
    """[guard] An operator who configured nothing sees no new refusal."""
    from runtime.blockchain.sponsorship import MeteredSigner, SponsorshipPolicy
    policy = SponsorshipPolicy(allowed_actions=None, daily_cap_usd=None,
                               db_path=tmp_path / "spend.db")
    assert MeteredSigner(_Account(), policy, "anything.at_all", "", None).sign_transaction(_TX) == "signed"


# ── the census ───────────────────────────────────────────────────────────

SIGNING_CALLS = frozenset({"sign_transaction", "send_transaction"})
DATA_KEYS = frozenset({"data", "input"})
LOOKUPS = frozenset({"get_function_by_name", "get_function_by_selector",
                     "get_function_by_signature", "get_function_by_identifier",
                     "find_functions_by_name", "find_functions_by_identifier"})
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

#: The signers that sign what their caller hands them. Every caller of theirs
#: calls ``sign_transaction(`` or ``send_transaction(`` itself, so the walk
#: reads each one at its own site.
PASS_THROUGH = {
    ("runtime/blockchain/sponsorship.py", "MeteredSigner.sign_transaction"),
    ("runtime/blockchain/web3_manager.py", "Web3Manager.send_transaction"),
}
#: Deployments. The twin's is unreferenced (its ``deploy`` is refused,
#: tests/test_no_deployment_claims.py); the conversion pipeline's runs only with
#: ``conversion.auto_deploy`` set, which the README documents.
DEPLOYMENTS = {
    ("runtime/blockchain/smart_contracts.py", "SmartContracts._deploy_disabled_implementation"),
    ("runtime/blockchain/services/contract_conversion/service.py",
     "ContractConversionService._compile_and_deploy"),
}
#: Signs a transaction whose to, value and data it is handed. Nothing calls it
#: (test_nothing_calls_the_signer_that_signs_what_it_is_handed).
UNCALLED = {("runtime/blockchain/gas_sponsor.py", "GasSponsor.sponsor_transaction")}


def _own_nodes(fn):
    """The nodes of *fn*'s own body, not of a def, lambda or class inside it."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _functions(tree):
    """(qualified name, function) for every def at any depth."""
    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield prefix + child.name, child
                yield from walk(child, prefix + child.name + ".")
            elif isinstance(child, ast.ClassDef):
                yield from walk(child, prefix + child.name + ".")
            else:
                yield from walk(child, prefix)
    yield from walk(tree, "")


def _params(fn) -> set[str]:
    a = fn.args
    names = {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
    names |= {x.arg for x in (a.vararg, a.kwarg) if x is not None}
    return names - {"self", "cls"}


def _bindings(fn) -> dict[str, list[ast.AST]]:
    out: dict[str, list[ast.AST]] = {}
    for n in _own_nodes(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, []).append(n.value)
        elif (isinstance(n, (ast.AnnAssign, ast.NamedExpr)) and n.value is not None
              and isinstance(n.target, ast.Name)):
            out.setdefault(n.target.id, []).append(n.value)
    return out


def _draws(expr, params, bindings, seen=frozenset()) -> bool:
    """Whether *expr* reads a parameter, directly or through local names."""
    for n in ast.walk(expr):
        if isinstance(n, ast.Name):
            if n.id in params:
                return True
            if n.id in bindings and n.id not in seen and any(
                    _draws(v, params, bindings, seen | {n.id}) for v in bindings[n.id]):
                return True
    return False


def _callee_problem(f, bindings, seen=frozenset()) -> str | None:
    """None when *f*, the function a transaction is built from, is named in
    the source (``contract.functions.transfer``) or is a constructor."""
    unread = "the census cannot read which function it calls"
    if isinstance(f, ast.Name):
        if f.id in bindings and f.id not in seen:
            return next((w for w in (_callee_problem(v, bindings, seen | {f.id})
                                     for v in bindings[f.id]) if w), None)
        return unread
    if isinstance(f, ast.Attribute):
        if f.attr in LOOKUPS:
            return "the function is looked up by a name or selector at run time"
        if f.attr == "constructor" or (isinstance(f.value, ast.Attribute)
                                       and f.value.attr == "functions"):
            return None
        return unread
    if isinstance(f, ast.Subscript):
        return "the function is chosen at run time (functions[...])"
    if isinstance(f, ast.Call):
        if isinstance(f.func, ast.Name) and f.func.id == "getattr":
            return "the function is chosen at run time (getattr)"
        if isinstance(f.func, ast.Attribute) and f.func.attr in LOOKUPS:
            return "the function is looked up by a name or selector at run time"
    return unread


def _unnamed_function(recv, bindings, seen=frozenset()) -> str | None:
    """None when *recv*, what ``build_transaction`` is called on, is a call of
    a function named in the source (or of a constructor); otherwise why not."""
    if isinstance(recv, ast.Name) and recv.id in bindings and recv.id not in seen:
        return next((w for w in (_unnamed_function(v, bindings, seen | {recv.id})
                                 for v in bindings[recv.id]) if w), None)
    if isinstance(recv, ast.Call):
        return _callee_problem(recv.func, bindings)
    return "the census cannot read which function it calls"


def _deploys(recv, bindings, seen=frozenset()) -> bool:
    if isinstance(recv, ast.Name) and recv.id in bindings and recv.id not in seen:
        return any(_deploys(v, bindings, seen | {recv.id}) for v in bindings[recv.id])
    return (isinstance(recv, ast.Call) and isinstance(recv.func, ast.Attribute)
            and recv.func.attr == "constructor")


def _mutated(name, fn, params, bindings) -> str | None:
    for n in _own_nodes(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                        and t.value.id == name and _draws(n.value, params, bindings)
                        and not (isinstance(t.slice, ast.Constant)
                                 and t.slice.value not in DATA_KEYS)):
                    return "the transaction's data is replaced by what the function was handed"
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name) and n.func.value.id == name):
            continue
        if n.func.attr in ("setdefault", "__setitem__") and len(n.args) == 2:
            key, value = n.args
            if (_draws(value, params, bindings)
                    and not (isinstance(key, ast.Constant) and key.value not in DATA_KEYS)):
                return "the transaction's data is replaced by what the function was handed"
        elif n.func.attr == "update":
            parts = [*n.args, *(k.value for k in n.keywords if k.arg is None)]
            named = {k.arg: k.value for k in n.keywords if k.arg is not None}
            if (any(_draws(a, params, bindings) for a in parts if not isinstance(a, ast.Dict))
                    or any(_signs(a, fn, params, bindings)[1] for a in parts if isinstance(a, ast.Dict))
                    or any(k in DATA_KEYS and _draws(v, params, bindings) for k, v in named.items())):
                return "the transaction is updated from what the function was handed"
    return None


def _signs(arg, fn, params, bindings, seen=frozenset()) -> tuple[str, str | None]:
    """(kind, problem) for what one signing call signs: kind is 'built',
    'deployment' or 'handed'."""
    unread = "the census cannot read what is signed"
    if isinstance(arg, ast.Dict):
        for k, v in zip(arg.keys, arg.values):
            if k is None and _draws(v, params, bindings):
                return "built", "the transaction is unpacked from what the function was handed"
            if (isinstance(k, ast.Constant) and k.value in DATA_KEYS
                    and _draws(v, params, bindings)):
                return "built", f"the transaction's '{k.value}' is what the function was handed"
        return "built", None
    if isinstance(arg, ast.Call):
        f = arg.func
        if isinstance(f, ast.Attribute) and f.attr == "build_transaction":
            if _deploys(f.value, bindings):
                return "deployment", None
            return "built", _unnamed_function(f.value, bindings)
        if isinstance(f, ast.Name) and f.id == "dict" and len(arg.args) == 1:
            return _signs(arg.args[0], fn, params, bindings, seen)
        return "built", unread
    if isinstance(arg, ast.Name):
        if arg.id in params:
            return "handed", None
        if arg.id in bindings and arg.id not in seen:
            found = [_signs(v, fn, params, bindings, seen | {arg.id}) for v in bindings[arg.id]]
            kinds = {k for k, _p in found}
            kind = next(k for k in ("handed", "deployment", "built") if k in kinds)
            problem = next((p for _k, p in found if p), None)
            return kind, problem or _mutated(arg.id, fn, params, bindings)
    return "built", unread


def _census(source: str, filename: str):
    """Every signing call in the source: (function, line, kind, problem)."""
    tree = ast.parse(source, filename=filename)
    for qual, fn in _functions(tree):
        params, bindings = _params(fn), _bindings(fn)
        for n in _own_nodes(fn):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in SIGNING_CALLS):
                continue
            arg = n.args[0] if n.args else next(
                (k.value for k in n.keywords if k.arg in ("tx", "transaction_dict")), None)
            if arg is None:
                yield qual, n.lineno, "built", "the census cannot read what is signed"
                continue
            yield (qual, n.lineno, *_signs(arg, fn, params, bindings))


def _sites():
    for top in ("runtime", "gateway"):
        for path in sorted((ROOT / top).rglob("*.py")):
            rel = str(path.relative_to(ROOT))
            for qual, line, kind, problem in _census(path.read_text(encoding="utf-8"), rel):
                yield rel, qual, line, kind, problem


def test_every_call_the_platform_key_signs_names_its_function_in_the_source():
    """[control]"""
    sites = list(_sites())
    assert len(sites) >= 60, f"the walk read {len(sites)} signing calls; it is not reading the tree"
    bad, handed, deployed = [], set(), set()
    for rel, qual, line, kind, problem in sites:
        if kind == "handed":
            handed.add((rel, qual))
        elif kind == "deployment":
            deployed.add((rel, qual))
        elif problem and (rel, qual) not in UNCALLED:
            bad.append(f"{rel}:{line} {qual}: {problem}")
    assert bad == [], "the platform key signs a call the request chose:\n  " + "\n  ".join(bad)
    assert handed == PASS_THROUGH, handed ^ PASS_THROUGH
    assert deployed == DEPLOYMENTS, deployed ^ DEPLOYMENTS
    flagged = {(rel, qual) for rel, qual, _l, _k, problem in sites if problem}
    assert flagged == UNCALLED, flagged ^ UNCALLED


def test_nothing_calls_the_signer_that_signs_what_it_is_handed():
    """[guard] Its listing above rests on this."""
    callers = []
    for top in ("runtime", "gateway", "sdk", "scripts", "examples"):
        for path in sorted((ROOT / top).rglob("*.py")) if (ROOT / top).is_dir() else ():
            if str(path.relative_to(ROOT)) == "runtime/blockchain/gas_sponsor.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            callers += [f"{path.relative_to(ROOT)}:{n.lineno}" for n in ast.walk(tree)
                        if isinstance(n, ast.Attribute) and n.attr == "sponsor_transaction"]
    assert callers == [], callers


_PLANTED = {
    "a function chosen by name": (
        "async def go(self, params):\n"
        "    c = self.web3.eth.contract(address=params['to'], abi=params['abi'])\n"
        "    tx = c.functions[params['fn']](*params['args']).build_transaction({})\n"
        "    account.sign_transaction(tx)\n", "run time (functions"),
    "a function reached through getattr": (
        "async def go(self, params):\n"
        "    fn = getattr(contract.functions, params['fn'])\n"
        "    tx = fn(1).build_transaction({})\n"
        "    await self._web3.send_transaction(tx)\n", "run time (getattr)"),
    "a function looked up by name": (
        "async def go(self, params):\n"
        "    tx = contract.get_function_by_name(params['fn'])(1).build_transaction({})\n"
        "    account.sign_transaction(tx)\n", "looked up"),
    "calldata the request wrote": (
        "async def go(self, params):\n"
        "    await self._web3.send_transaction({'to': params['to'], 'data': params['data']})\n",
        "'data' is what"),
    "calldata put in afterwards": (
        "async def go(self, params):\n"
        "    tx = contract.functions.ping().build_transaction({})\n"
        "    tx['data'] = params['data']\n"
        "    account.sign_transaction(tx)\n", "replaced"),
    "a transaction updated from the request": (
        "async def go(self, params):\n"
        "    tx = contract.functions.ping().build_transaction({})\n"
        "    tx.update(params)\n"
        "    account.sign_transaction(tx)\n", "updated"),
    "a transaction unpacked from the request": (
        "async def go(self, params):\n"
        "    account.sign_transaction({**params, 'nonce': 1})\n", "unpacked"),
    "something the walk cannot read": (
        "async def go(self, params):\n"
        "    account.sign_transaction(self._pending)\n", "cannot read"),
}


@pytest.mark.parametrize("shape", sorted(_PLANTED))
def test_the_census_sees_a_planted_shape(shape):
    """[guard] Each way of letting a request choose the call is reported."""
    source, expected = _PLANTED[shape]
    problems = [p for *_s, p in _census(source, "<planted>") if p]
    assert any(expected in p for p in problems), (shape, problems)


def test_the_census_passes_the_shape_every_signer_uses():
    """[guard] A named function whose arguments come from the request is not
    this class; which argument must be the caller's is the seam's."""
    clean = (
        "async def go(self, params):\n"
        "    c = self.web3.eth.contract(address=params['contract'], abi=ABI)\n"
        "    call = c.functions.transferFrom(self.wallet, params['to'], 1)\n"
        "    tx = call.build_transaction({'from': self.wallet, 'nonce': 0})\n"
        "    signed = account.sign_transaction(tx)\n"
        "    await self._web3.send_transaction({'to': params['to'], 'value': 1, 'gas': 21000})\n"
    )
    assert [p for *_s, p in _census(clean, "<clean>") if p] == []
