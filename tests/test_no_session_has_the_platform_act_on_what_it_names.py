"""No user session has the platform's wallet or a platform credential act on a
payee, an account, an asset, a key, a digest or content the request names.

THE DEFECT (pre-existing on The Matrix ``main``). The services layer signs with
the platform's wallet and acts with credentials the operator configured, and a
user session reached it through capability invoke, ``/bridge/v1/action`` and
chat (Trinity's ``request_execution``, which hands the request to Neo). Among
what a session could have the platform do:

  * sign, from the platform's wallet, a call whose payee or asset the request
    named: ``claim_compute_reward`` signed ``claimRewards(recipient)`` with the
    request's recipient; ``bridge_token_ccip`` sent the platform's tokens to
    the request's receiver; ``borrow_against_nft`` borrowed on behalf of the
    request's account. Twenty-four addresses a request supplies to a call the
    services layer signs are listed by the signing census, and two more travel
    encoded as bytes;
  * have the operator's MPC cluster sign a digest the request wrote, under the
    key id the request named, authorised by the platform's API key alone
    (``mpc_sign``), although the catalog marks it unavailable: the invoke
    route did not read ``available``;
  * publish content under the platform's publishing account (``publish_mirror_
    post``, ``publish_paragraph_post``), cast through a Farcaster signer the
    platform's API key reaches (``publish_cast``, falling back to the
    platform's own signer), write the platform's storage node or database
    (``ceramic_stream_create``, ``orbit_db_write``, ``store_filecoin``), spend
    the platform's provider account (``submit_compute_job``, ``rent_device``),
    pay from its payment node (``route_payment``), open a KYC applicant or read
    one's result with its KYC credential (``start_kyc``, ``check_aml_risk``);
  * have the platform's server send an HTTP request to the URL, with the
    method, headers and body, the request wrote (the oracle's ``custom``
    type), or read its sports provider with its key at a path the request
    wrote.

THE CHANGE. ``runtime/access_policy.py`` refuses a session each of those
(``REFUSED_TO_A_SESSION``), at every door a session reaches: capability
invoke, ``/bridge/v1/action``, and the tool dispatcher for
``request_execution`` and ``platform_action``. Where the one address a request
names is the one the platform acts for and the platform spends only gas on it,
the action is kept and bound: a Lens profile, a social or creator token, a
Push subscription name the session's own address or are refused
(``BOUND_TO_THE_CALLER``). The oracle keeps a price, a weather reading and a
randomness request for a session (``HELD_FOR_A_SESSION``). The operator's key,
and a dispatch with no HTTP caller, keep every one. The capability invoke
route refuses a capability the catalog marks unavailable, whoever asks.

THE CENSUS. The list is derived, not only written. Two walks of the source say
which (service, method) pairs a request dispatches can have the platform act
in this way:

  * the signing census's listing of every address a request supplies to a
    call the services layer signs (``SERVICE_ADDRESSES``, each a payee or an
    asset), and its two payees encoded as bytes;
  * a walk of every HTTP request a method under ``runtime/blockchain/
    services/`` sends. It reads a client bound by ``with`` (``async with
    httpx.AsyncClient(...) as client``, ``aiohttp.ClientSession()`` and any
    factory whose name ends in ``Client``, ``ClientSession`` or ``Session``)
    and called by a verb (``get``, ``post``, ``put``, ``patch``, ``delete``,
    ``head``, ``options``; ``request``, ``stream`` or ``send`` with the verb
    as a constant first argument, and otherwise as a verb it cannot read), and
    a verb called on ``httpx``, ``requests`` or ``aiohttp`` itself. It reports
    a client factory used any other way, a client name used other than by a
    verb, and an import of another network library (``urllib``, ``http``,
    ``socket``, ``websockets``, ``websocket``).

A method reaches what it names through ``self`` or ``cls`` (a call, or a
reference such as a dispatch table of bound methods) and what it calls by
name in its own module, followed to a fixed point. Every method a dispatch can
run, the ``service`` override included, is read. Each pair either walk finds
must be refused to a session, bound, or held, or already refused (to every
caller, or to a session because its route is the operator's), or listed here
with the reason it is not the class. An entry in those tables that no walk
finds fails too, so neither side can drift.

WHAT THIS DOES NOT READ, stated. A payee or an asset the address walk does not
read (see its own docstring); an amount; a send made by an object a service
holds and calls through an attribute (the weather oracle's is listed below by
name); an HTTP client made by code outside the service and handed in; a
request sent by any shape not named above; code replaced at run time. A
dedicated ``/api/v1`` route a session reaches runs what its handler pins
(checked below against the routes the gateway builds), not what a request
names.

CONTROL. Of this file's 29 tests, 14 are marked [control] and 15 [guard].
Laid over this branch's census-wording commit ("The signing and attestation
censuses name the shapes they read and claim no more, ...") all 14 controls
fail there: the two table controls because neither table exists, the others
because the dispatcher ran for a session, the MPC cluster was asked to sign,
the invoke route ran an unavailable capability or the registry offered a
refused action. 13 guards pass there; the other two read the tables this
change adds (the oracle types a session may send, and the route check) and
cannot pass there. All 29 pass here.
"""

from __future__ import annotations

import ast
import asyncio
import json
import pathlib
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import test_no_request_chooses_the_call_the_platform_key_signs as signing  # noqa: E402

A = "0x" + "a1" * 20      # the session's own address
B = "0x" + "b2" * 20      # somebody else
SERVICES = ROOT / "runtime" / "blockchain" / "services"


# ── the walk of HTTP requests a service sends ───────────────────────────

CLIENT_FACTORIES = ("Client", "ClientSession", "Session")
HTTP_VERBS = frozenset({"get", "head", "options", "post", "put", "patch", "delete"})
VERB_ARGUMENT = frozenset({"request", "stream", "send"})
HTTP_MODULES = frozenset({"httpx", "requests", "aiohttp"})
UNREAD_LIBRARIES = frozenset({"urllib", "http", "socket", "websockets", "websocket"})
READ_VERBS = frozenset({"get", "head", "options"})
#: What an HTTP library offers besides a client and a verb: a timeout, errors.
_HTTP_NON_SENDERS = frozenset({"ClientTimeout", "Timeout", "HTTPStatusError", "RequestError",
                               "TimeoutException", "ClientError", "ConnectError"})


def _is_factory(func) -> bool:
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    return isinstance(name, str) and name.endswith(CLIENT_FACTORIES)


def _clients(fn) -> set[str]:
    """Names *fn* binds to an HTTP client with ``with ... as``."""
    names = set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                ctx = item.context_expr
                if (isinstance(ctx, ast.Call) and _is_factory(ctx.func)
                        and isinstance(item.optional_vars, ast.Name)):
                    names.add(item.optional_vars.id)
    return names


def _verb(call) -> str | None:
    """The HTTP verb of *call*, '?' when it cannot be read, None if not a send."""
    attr = call.func.attr
    if attr in HTTP_VERBS:
        return attr
    if attr in VERB_ARGUMENT:
        first = call.args[0] if call.args else None
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value.lower()
        return "?"
    return None


def http_sends(fn) -> list[tuple[int, str]]:
    """(line, verb) of each HTTP request *fn* sends, nested defs included."""
    clients = _clients(fn)
    out = []
    for n in ast.walk(fn):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)):
            continue
        if n.func.value.id in clients or n.func.value.id in HTTP_MODULES:
            verb = _verb(n)
            if verb is not None:
                out.append((n.lineno, verb))
    return out


def http_unread(tree) -> list[tuple[int, str]]:
    """(line, why) for each network use in *tree* the walk does not read."""
    out = []
    factories_read = {id(item.context_expr.func)
                      for n in ast.walk(tree) if isinstance(n, (ast.With, ast.AsyncWith))
                      for item in n.items if isinstance(item.context_expr, ast.Call)}
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
            for name in names:
                if name.split(".")[0] in UNREAD_LIBRARIES:
                    out.append((n.lineno, f"a network library the walk does not read ({name})"))
        elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in HTTP_MODULES:
            if n.attr in _HTTP_NON_SENDERS or n.attr in HTTP_VERBS | VERB_ARGUMENT:
                continue
            if _is_factory(n) and id(n) in factories_read:
                continue
            out.append((n.lineno, f"{n.value.id}.{n.attr} used where the walk does not read it"))
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        clients = _clients(fn)
        parents = {id(c): p for p in ast.walk(fn) for c in ast.iter_child_nodes(p)}
        for n in ast.walk(fn):
            if not (isinstance(n, ast.Name) and n.id in clients and isinstance(n.ctx, ast.Load)):
                continue
            parent = parents.get(id(n))
            called = parents.get(id(parent)) if isinstance(parent, ast.Attribute) else None
            if isinstance(called, ast.Call) and called.func is parent and _verb(called) is not None:
                continue
            out.append((n.lineno, f"the client {n.id} is used where the walk does not read it"))
    return out


# ── what a dispatch can run, and what each method reaches ───────────────

def _service_classes() -> dict:
    """service name -> (file, class node, module tree)."""
    from runtime.blockchain.services.registry import _SERVICE_MAP
    out = {}
    for service, (module, cls) in _SERVICE_MAP.items():
        package = SERVICES / module.lstrip(".")
        for path in sorted(package.rglob("*.py")) if package.is_dir() else [package.with_suffix(".py")]:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and node.name == cls:
                    out[service] = (str(path.relative_to(ROOT)), node, tree)
    return out


def _methods(cls) -> dict:
    return {n.name: n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def dispatchable_pairs(classes) -> set[tuple[str, str]]:
    """Every (service, method) a dispatch can run: an ACTION_MAP method name on
    any service that defines it (a platform_action ``service`` override moves
    an action's method onto another service)."""
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    names = {method for _service, method in ACTION_MAP.values()}
    return {(service, name) for service, (_f, cls, _t) in classes.items()
            for name in names & set(_methods(cls))}


def reach(classes, service: str, method: str) -> set[tuple[str, str]]:
    """(file, qualified name) of every function *method* reaches through
    ``self``/``cls`` and through names of its own module, to a fixed point."""
    rel, cls, tree = classes[service]
    own = _methods(cls)
    module = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    seen, stack = set(), [method]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        fn = own.get(name) or module.get(name)
        if fn is None:
            continue
        for n in ast.walk(fn):
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id in ("self", "cls") and n.attr in own):
                stack.append(n.attr)
            elif isinstance(n, ast.Name) and n.id in module:
                stack.append(n.id)
    return {(rel, f"{cls.name}.{name}" if name in own else name) for name in seen}


def all_http_sends() -> dict:
    """(file, qualified name) -> [(line, verb)] for every top-level function or
    method under the services directory that sends."""
    out = {}
    for path in sorted(SERVICES.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for qual, fn, _cls, outer in signing._functions(tree):
            sends = http_sends(fn)
            if sends and not outer:
                out[(str(path.relative_to(ROOT)), qual)] = sends
    return out


_PAYEE_BYTES = {(signing._CCIP, "CrossChainMessagingService.bridge_token_ccip"),
                (signing._CCIP, "CrossChainMessagingService.bridge_stargate")}


def derive():
    """(pairs that reach a platform-signed payee or asset, pairs that reach an
    HTTP send with their verbs, sends no pair reaches)."""
    classes = _service_classes()
    pairs = dispatchable_pairs(classes)
    reached = {pair: reach(classes, *pair) for pair in pairs}
    payee_sites = {(f, q) for (f, q, _fn, _path), kind in signing.SERVICE_ADDRESSES.items()
                   if kind in (signing.PAYEE, signing.ASSET)} | _PAYEE_BYTES
    onchain = {pair for pair, funcs in reached.items() if funcs & payee_sites}
    unreached_payees = payee_sites - set().union(*reached.values())
    sends = all_http_sends()
    http = {}
    for pair, funcs in reached.items():
        verbs = sorted({v for site in funcs & set(sends) for _line, v in sends[site]})
        if verbs:
            http[pair] = verbs
    unreached_sends = set(sends) - set().union(*reached.values())
    return onchain, http, unreached_payees, unreached_sends


#: A pair the HTTP walk finds that is not the class, each with the reason.
_FIXED_ORACLE_TYPE = ("calls request with a fixed oracle type ({}), which a session may send "
                      "(HELD_FOR_A_SESSION); the walk reaches every handler through the "
                      "dispatch table, the call reaches one")
OFF_CHAIN_READS = {
    ("advanced_governance", "quadratic_vote"): (
        "relays to the configured Snapshot hub an envelope the voter's own wallet "
        "signed; the hub checks that signature, and no platform credential rides "
        "with it (without one it returns the unsigned payload)"),
    ("ccip", "query_remote_chain"): (
        "a GET of a cross-chain message's public status from the configured tracker; "
        "the optional tracker key meters it"),
    ("oracles_plus", "pyth_pull"): (
        "a GET of public price updates from Pyth's Hermes; no credential is sent"),
    ("oracles_plus", "redstone_request"): (
        "a GET of a public data package from the configured RedStone gateway; the "
        "optional key meters it"),
    ("oracle_gateway", "query_price"): _FIXED_ORACLE_TYPE.format("price_feed"),
    ("oracle_gateway", "query_weather"): _FIXED_ORACLE_TYPE.format("weather"),
    ("oracle_gateway", "request_vrf"): _FIXED_ORACLE_TYPE.format("random_vrf"),
}
#: Sends the walk finds that no dispatch reaches through self or its module.
UNREACHED_SENDS = {
    ("runtime/blockchain/services/oracle_gateway/weather_oracle.py", "WeatherOracle._http_get"): (
        "the weather oracle's GET of the configured provider, with the platform's key "
        "and a location; reached through OracleGateway's weather component, which a "
        "session asks only for a reading"),
}


def _already_refused(pair) -> bool:
    """Refused to every caller, or to a session because its route is the operator's."""
    from gateway.session_routes import SERVICE_METHODS_OFF_ALLOWLIST
    from runtime.access_policy import REFUSED_ON_REQUEST
    return pair in REFUSED_ON_REQUEST or f"{pair[0]}.{pair[1]}" in SERVICE_METHODS_OFF_ALLOWLIST


def test_every_pair_the_walks_find_is_refused_bound_held_or_read():
    """[control] At the census-wording commit neither table existed: every pair
    below was dispatched for a session."""
    from runtime.access_policy import (
        BOUND_TO_THE_CALLER, HELD_FOR_A_SESSION, REFUSED_TO_A_SESSION)
    onchain, http, _up, _us = derive()
    assert len(onchain) >= 15 and len(http) >= 15, (len(onchain), len(http))
    decided = set(REFUSED_TO_A_SESSION) | set(BOUND_TO_THE_CALLER) | set(HELD_FOR_A_SESSION)
    open_ = sorted(f"{s}.{m} ({'signed payee or asset' if (s, m) in onchain else 'HTTP ' + ','.join(http[(s, m)])})"
                   for s, m in onchain | set(http)
                   if (s, m) not in decided and (s, m) not in OFF_CHAIN_READS
                   and not _already_refused((s, m)))
    assert open_ == [], ("a session can have the platform act on what the request names:\n  "
                         + "\n  ".join(open_))


def test_every_table_entry_is_one_the_walks_find():
    """[control] A refusal, a binding, a hold or a listed read the walks do not
    find is a table drifting from the code."""
    from runtime.access_policy import (
        BOUND_TO_THE_CALLER, HELD_FOR_A_SESSION, REFUSED_TO_A_SESSION)
    onchain, http, _up, _us = derive()
    found = onchain | set(http)
    stale = sorted(f"{s}.{m}" for s, m in (set(REFUSED_TO_A_SESSION) | set(BOUND_TO_THE_CALLER)
                                          | set(HELD_FOR_A_SESSION) | set(OFF_CHAIN_READS))
                   - found)
    assert stale == [], stale
    for pair in OFF_CHAIN_READS:
        assert pair not in onchain, pair


def test_every_payee_and_send_is_reached_or_listed():
    """[guard] A payee the address walk lists, or a send, that no dispatchable
    method reaches would be outside the derivation; each is reached, or listed."""
    _on, _http, unreached_payees, unreached_sends = derive()
    assert unreached_payees == set(), unreached_payees
    assert unreached_sends == set(UNREACHED_SENDS), unreached_sends ^ set(UNREACHED_SENDS)


def test_the_listed_reads_send_only_reads_or_a_signed_relay():
    """[guard] A listed read sends GET only, except the relay named, and the
    oracle wrappers pin a type a session may send."""
    from runtime.access_policy import HELD_FOR_A_SESSION
    _on, http, _up, _us = derive()
    for pair in OFF_CHAIN_READS:
        if pair[0] == "oracle_gateway":
            continue
        verbs = set(http[pair])
        assert verbs <= READ_VERBS or pair == ("advanced_governance", "quadratic_vote"), (pair, verbs)
    _field, allowed = HELD_FOR_A_SESSION[("oracle_gateway", "request")]
    classes = _service_classes()
    methods = _methods(classes["oracle_gateway"][1])
    for (_s, name) in (p for p in OFF_CHAIN_READS if p[0] == "oracle_gateway"):
        calls = [n for n in ast.walk(methods[name]) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr in ("request", "request_safe")]
        assert len(calls) == 1 and isinstance(calls[0].args[0], ast.Constant), name
        assert calls[0].args[0].value in allowed, (name, calls[0].args[0].value)


def test_no_network_use_in_the_services_is_one_the_walk_does_not_read():
    """[guard] Fail closed: a client or a library the walk does not read is reported."""
    unread = [f"{path.relative_to(ROOT)}:{line} {why}"
              for path in sorted(SERVICES.rglob("*.py"))
              for line, why in http_unread(ast.parse(path.read_text(encoding="utf-8")))]
    assert unread == [], unread


_PLANTED_SENDS = {
    "an httpx client's post": (
        "async def go(self, p):\n"
        "    async with httpx.AsyncClient() as c:\n"
        "        await c.post(URL, json=p)\n", [(3, "post")]),
    "an aiohttp session's get": (
        "async def go(self, p):\n"
        "    async with aiohttp.ClientSession() as s:\n"
        "        async with s.get(URL) as r:\n"
        "            pass\n", [(3, "get")]),
    "a verb handed as a value": (
        "async def go(self, method, p):\n"
        "    async with httpx.AsyncClient() as c:\n"
        "        await c.request(method, URL)\n", [(3, "?")]),
    "a module-level send": (
        "def go(p):\n"
        "    return requests.put(URL, json=p)\n", [(2, "put")]),
}


@pytest.mark.parametrize("shape", sorted(_PLANTED_SENDS))
def test_the_walk_sees_a_planted_send(shape):
    """[guard]"""
    source, expected = _PLANTED_SENDS[shape]
    (fn,) = [n for n in ast.parse(source).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert http_sends(fn) == expected, http_sends(fn)


@pytest.mark.parametrize("source,expected", [
    ("import urllib.request\n", "network library"),
    ("def go():\n    c = httpx.AsyncClient()\n", "httpx.AsyncClient used"),
    ("async def go(h):\n    async with httpx.AsyncClient() as c:\n        h(c)\n", "the client c"),
])
def test_the_walk_reports_a_network_use_it_does_not_read(source, expected):
    """[guard]"""
    assert any(expected in why for _line, why in http_unread(ast.parse(source))), http_unread(ast.parse(source))


def test_a_dispatch_table_of_bound_methods_is_followed():
    """[guard] The oracle reaches its handlers through a dict of bound methods."""
    classes = _service_classes()
    funcs = {q for _f, q in reach(classes, "oracle_gateway", "request")}
    assert "OracleGateway._handle_custom" in funcs, funcs


# ── the doors ───────────────────────────────────────────────────────────

def _actions_for(pair) -> list[str]:
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    return sorted(a for a, p in ACTION_MAP.items() if p == pair)


@pytest.fixture
def dispatched(monkeypatch):
    """Every action that reached ServiceDispatcher.execute, under a gate that
    allows everything, so a refusal can only be the door's."""
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    calls: list[str] = []

    class _Allow:
        async def initialize(self):
            return None

        async def evaluate(self, action, context):
            return {"allow": True}

    async def execute(self, action, service=None, params=None, **kwargs):
        calls.append(action if not service else f"{action}@{service}")
        return json.dumps({"status": "ok", "result": {"status": "recorded by the test"}})

    monkeypatch.setattr(ServiceDispatcher, "execute", execute)
    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda *a, **k: _Allow())
    return calls


async def _session(server, token: str = "0xTEST_SESSION", address: str = "apple:sub"):
    now = time.time()
    await server.wallet_sessions.add(token=token, address=address,
                                     issued_at=now, expires_at=now + 3600)


SESSION = {"Authorization": "Bearer 0xTEST_SESSION"}
OWN = {"Authorization": "Bearer 0xOWN_SESSION"}
OPERATOR = {"Authorization": "Bearer k"}


def _refused_actions():
    from runtime.access_policy import REFUSED_TO_A_SESSION
    out = {}
    for pair in sorted(REFUSED_TO_A_SESSION):
        actions = _actions_for(pair)
        assert actions, f"{pair}: no action resolves to it"
        out[actions[0]] = pair
    return out


async def test_no_session_door_dispatches_them(dispatched, tmp_path):
    """[control] Capability invoke and /bridge/v1/action answer a session 403
    for every refused pair before the dispatcher runs."""
    from aiohttp.test_utils import TestClient, TestServer

    from runtime.access_policy import REFUSED_TO_A_SESSION, dispatch_pair
    from runtime.capabilities import catalog
    server = signing._server(tmp_path)
    answered = {}
    async with TestClient(TestServer(server.create_app())) as client:
        await _session(server)
        for action in _refused_actions():
            resp = await client.post("/bridge/v1/action", headers=SESSION,
                                     json={"action": action, "params": {"to": B}, "session_id": "s1"})
            answered[f"bridge {action}"] = resp.status
        for cap in catalog.CAPABILITIES:
            if dispatch_pair(cap["action"]) in REFUSED_TO_A_SESSION:
                resp = await client.post(f"/api/v1/capabilities/{cap['id']}/invoke",
                                         headers=SESSION, json={"params": {"to": B}})
                answered[f"invoke {cap['id']}"] = resp.status
    assert dispatched == [], f"a session's doors ran {dispatched}"
    assert len(answered) > 50 and set(answered.values()) == {403}, answered


@pytest.mark.parametrize("tool", ["request_execution", "platform_action"])
async def test_no_session_chat_dispatches_them(dispatched, tool):
    """[control] Chat acting for a session: Trinity's hand-off to Neo, and her
    own platform_action, with the session's credential."""
    from runtime.tools.dispatcher import ToolDispatcher
    for action in _refused_actions():
        out = await ToolDispatcher({"workspace": "."}).dispatch(
            tool, {"action": action, "params": {"to": B}},
            agent_name="trinity", caller_identity=A, caller_kind="session")
        assert out.ok is False and "[DENIED]" in out.model_text, (action, out.model_text)
    assert dispatched == [], f"{tool} ran {dispatched}"


def _walked_actions():
    """An action for every pair the walks find, but those every door refuses
    and those listed as reads: what the operator's key must still reach."""
    from runtime.access_policy import REFUSED_ON_REQUEST
    onchain, http, _up, _us = derive()
    out = {}
    for pair in sorted(onchain | set(http)):
        if pair in REFUSED_ON_REQUEST or pair in OFF_CHAIN_READS:
            continue
        actions = _actions_for(pair)
        if actions:
            out[actions[0]] = pair
    return out


async def test_the_operator_keeps_them(dispatched, tmp_path):
    """[guard] The operator's key reaches every pair the walks find (those
    every door refuses and the listed reads aside) through /bridge/v1/action
    and through Neo's platform_action; read from the walks, not the tables."""
    from aiohttp.test_utils import TestClient, TestServer

    from runtime.tools.dispatcher import ToolDispatcher
    actions = _walked_actions()
    assert len(actions) > 30, len(actions)
    server = signing._server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        for action in actions:
            resp = await client.post("/bridge/v1/action", headers=OPERATOR,
                                     json={"action": action, "params": {"to": B}, "session_id": "s1"})
            assert resp.status == 200, (action, resp.status, await resp.text())
    for action in actions:
        out = await ToolDispatcher({"workspace": "."}).dispatch(
            "platform_action", {"action": action, "params": {"to": B}},
            agent_name="neo", caller_identity="", caller_kind="operator")
        assert "[DENIED]" not in out.model_text, (action, out.model_text)
    assert sorted(dispatched) == sorted(list(actions) * 2), dispatched


# ── the review's reproduction: mpc_sign, driven to the outgoing request ──

class _Captured:
    """httpx.AsyncClient with the network replaced: every request recorded."""
    sent: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None, **k):
        _Captured.sent.append({"url": url, "json": json, "headers": headers})

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"signature": "0x" + "5a" * 65}
        return _Resp()


MPC = {"endpoint": "https://mpc.invalid", "api_key": "platform-mpc-key"}
SIGN = {"key_id": "somebody-elses-key", "digest": "0x" + "d1" * 32}


@pytest.fixture
def captured(monkeypatch):
    import httpx
    _Captured.sent = []
    monkeypatch.setattr(httpx, "AsyncClient", _Captured)
    return _Captured.sent


def _mpc_server(tmp_path):
    from gateway.server import GatewayServer
    from test_route_sweep import SWEEP_CONFIG
    return GatewayServer({**SWEEP_CONFIG, "memory_dir": str(tmp_path / "m"),
                          "rexhepi": {"rate_limit_max_actions": 100_000},
                          "database": {"path": str(tmp_path / "s.db")},
                          "services": {"mpc": MPC},
                          "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": "k"}})


async def test_a_session_has_the_mpc_cluster_sign_nothing(captured, tmp_path):
    """[control] The review's drive: a session over capability invoke and
    /bridge/v1/action, the gate OBSERVE, the outgoing request captured. At the
    census-wording commit both answered 200 and the platform's API key asked
    the cluster to sign the request's digest under the request's key id."""
    from aiohttp.test_utils import TestClient, TestServer

    server = _mpc_server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        await _session(server)
        invoke = await client.post("/api/v1/capabilities/mpc_sign/invoke",
                                   headers=SESSION, json={"params": SIGN})
        bridge = await client.post("/bridge/v1/action", headers=SESSION,
                                   json={"action": "mpc_sign", "params": SIGN, "session_id": "s1"})
    assert captured == [], f"HTTP {invoke.status}/{bridge.status}: sent {captured}"
    assert (invoke.status, bridge.status) == (403, 403)


async def test_a_session_chat_has_the_mpc_cluster_sign_nothing(captured):
    """[control] request_execution for a session, as the review drove it."""
    from runtime.tools.dispatcher import ToolDispatcher
    out = await ToolDispatcher({"workspace": ".", "services": {"mpc": MPC}}).dispatch(
        "request_execution", {"action": "mpc_sign", "params": SIGN},
        agent_name="trinity", caller_identity=A, caller_kind="session")
    assert captured == [], captured
    assert out.ok is False and "[DENIED]" in out.model_text, out.model_text


async def test_the_operator_still_has_the_cluster_sign(captured):
    """[guard] Neo's platform_action with the operator's key still reaches the
    cluster, so the controls above see a request when there is one."""
    from runtime.tools.dispatcher import ToolDispatcher
    await ToolDispatcher({"workspace": ".", "services": {"mpc": MPC}}).dispatch(
        "platform_action", {"action": "mpc_sign", "params": SIGN},
        agent_name="neo", caller_identity="", caller_kind="operator")
    assert [c["json"] for c in captured] == [SIGN], captured
    assert captured[0]["headers"] == {"Authorization": "Bearer platform-mpc-key"}


# ── what the catalog marks unavailable ──────────────────────────────────

async def test_the_invoke_route_runs_no_unavailable_capability(dispatched, tmp_path):
    """[control] available=False was metadata the listing filtered on and the
    invoke route never read. The operator's key is refused too."""
    from aiohttp.test_utils import TestClient, TestServer

    from runtime.capabilities import catalog
    unavailable = [c["id"] for c in catalog.CAPABILITIES if c["available"] is False]
    assert len(unavailable) > 40, len(unavailable)
    server = signing._server(tmp_path)
    answered = {}
    async with TestClient(TestServer(server.create_app())) as client:
        for cap_id in unavailable:
            resp = await client.post(f"/api/v1/capabilities/{cap_id}/invoke",
                                     headers=OPERATOR, json={"params": {}})
            answered[cap_id] = resp.status
    assert dispatched == [], dispatched
    assert set(answered.values()) <= {403, 503}, answered


async def test_an_available_capability_still_runs(dispatched, tmp_path):
    """[guard]"""
    from aiohttp.test_utils import TestClient, TestServer

    server = signing._server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post("/api/v1/capabilities/oracle_price_query/invoke",
                                 headers=OPERATOR, json={"params": {"pair": "ETH/USD"}})
    assert resp.status == 200 and dispatched == ["oracle_price_query"], (resp.status, dispatched)


# ── what is kept for a session, bound to its own address ────────────────

BOUND_CASES = {
    "create_lens_profile": "to",
    "launch_social_token": "owner",
    "launch_creator_coin": "creator",
    "push_subscribe": "subscriber",
}


@pytest.mark.parametrize("action", sorted(BOUND_CASES))
async def test_a_session_names_only_its_own_address(dispatched, tmp_path, action):
    """[control] Somebody else's address, no address, an alias naming
    somebody else, and a session bound to no wallet are refused; the session's
    own address is dispatched, on the bridge and through chat."""
    from aiohttp.test_utils import TestClient, TestServer

    from runtime.tools.dispatcher import ToolDispatcher
    field = BOUND_CASES[action]
    refused = [{field: B}, {}, {field: A, "creator": B, "owner": B, "address": B}]
    server = signing._server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        await _session(server, "0xOWN_SESSION", A)
        await _session(server)                       # apple:sub, no wallet linked
        for params in refused:
            resp = await client.post("/bridge/v1/action", headers=OWN,
                                     json={"action": action, "params": params, "session_id": "s1"})
            assert resp.status == 403, (params, resp.status)
        resp = await client.post("/bridge/v1/action", headers=SESSION,
                                 json={"action": action, "params": {field: A}, "session_id": "s1"})
        assert resp.status == 403, "a session bound to no wallet"
        assert dispatched == [], dispatched
        resp = await client.post("/bridge/v1/action", headers=OWN,
                                 json={"action": action, "params": {field: A}, "session_id": "s1"})
        assert resp.status == 200, (resp.status, await resp.text())
    assert dispatched == [action]
    chat = ToolDispatcher({"workspace": "."})
    out = await chat.dispatch("request_execution", {"action": action, "params": {field: A}, field: B},
                              agent_name="trinity", caller_identity=A, caller_kind="session")
    assert out.ok is False and "[DENIED]" in out.model_text, "an extra argument naming somebody else"
    out = await chat.dispatch("request_execution", {"action": action, "params": {field: A}},
                              agent_name="trinity", caller_identity=A, caller_kind="session")
    assert "[DENIED]" not in out.model_text, out.model_text
    assert dispatched == [action, action]


async def test_the_oracle_answers_a_session_a_price_and_not_a_custom_request(dispatched, tmp_path):
    """[control] The custom type had the platform's server send what the
    request wrote to the address it named; a session keeps the price."""
    from aiohttp.test_utils import TestClient, TestServer

    server = signing._server(tmp_path)
    statuses = {}
    async with TestClient(TestServer(server.create_app())) as client:
        await _session(server)
        for kind in ("custom", "sports", None, "price_feed"):
            params = {"params": {"url": "http://169.254.169.254/latest/meta-data/", "pair": "ETH/USD"}}
            if kind:
                params["oracle_type"] = kind
            resp = await client.post("/bridge/v1/action", headers=SESSION,
                                     json={"action": "oracle_request", "params": params,
                                           "session_id": "s1"})
            statuses[kind] = resp.status
    assert statuses == {"custom": 403, "sports": 403, None: 403, "price_feed": 200}, statuses
    assert dispatched == ["oracle_request"]


# ── the other surfaces follow ───────────────────────────────────────────

def test_the_registry_offers_a_session_nothing_it_refuses():
    """[control] extensions/registry.json is what the app reads and caches;
    every component in it is marked available."""
    from runtime.access_policy import REFUSED_TO_A_SESSION, dispatch_pair
    data = json.loads((ROOT / "extensions" / "registry.json").read_text(encoding="utf-8"))
    offered = [f"{c['id']}: {a}" for c in data["components"] for a in c.get("gateway_actions", [])
               if dispatch_pair(a) in REFUSED_TO_A_SESSION]
    assert offered == [], offered
    for component in data["components"]:
        assert component["capability_count"] == len(component["gateway_actions"]), component["id"]
    assert data["total_capabilities"] == sum(c["capability_count"] for c in data["components"])


def test_no_route_a_session_reaches_runs_what_it_is_refused():
    """[guard] A dedicated /api/v1 route runs what its handler pins. None a
    session reaches runs a refused pair, and the oracle route pins a type a
    session may send. Read from the routes the gateway builds."""
    from gateway.session_routes import USER_SESSION_ROUTES
    from runtime.access_policy import (
        BOUND_TO_THE_CALLER, HELD_FOR_A_SESSION, REFUSED_TO_A_SESSION)
    from scripts.generate_session_routes import live_route_pairs
    routes = live_route_pairs()
    bad = []
    for route in sorted(USER_SESSION_ROUTES):
        for pair, fixed in routes.get(route, {}).items():
            if pair in REFUSED_TO_A_SESSION or pair in BOUND_TO_THE_CALLER:
                bad.append(f"{route} runs {pair}")
            held = HELD_FOR_A_SESSION.get(pair)
            pinned = fixed.get(held[0]) if held else None
            if held and not (pinned and pinned[0] == "const" and pinned[1] in held[1]):
                bad.append(f"{route} runs {pair} with {fixed}")
    assert bad == [], bad
    assert ("oracle_gateway", "request") in routes["/api/v1/oracle/price/{pair}"]
