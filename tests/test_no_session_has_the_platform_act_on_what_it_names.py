"""No user session has the platform's wallet or a platform credential act on a
payee, an account, an asset, a contract, a key, a digest or content the
request names, under any name for the method that does it.

THE DEFECT (pre-existing on The Matrix ``main``). The services layer signs with
the platform's wallet and acts with credentials the operator configured, and a
user session reached it through capability invoke, ``/bridge/v1/action`` and
chat (Trinity's ``request_execution``, which hands the request to Neo). Among
what a session could have the platform do:

  * sign, from the platform's wallet, a call whose payee or asset the request
    named: ``claim_compute_reward`` signed ``claimRewards(recipient)`` with the
    request's recipient; ``bridge_token_ccip`` sent the platform's tokens to
    the request's receiver; ``borrow_against_nft`` borrowed on behalf of the
    request's account. The signing census lists every address it reads a
    request supplying to a call the services layer signs, and two more that
    travel encoded as bytes;
  * sign a call to a contract the request named: ``breed_nft`` sent
    ``breed(parent_a, parent_b)`` from the platform's wallet to the breeding
    contract the request named;
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

THE SECOND DEFECT (the review of the first change). The refusal was keyed on
the (service, method) pair an action NAMES, not on the method it REACHES.
``compute_job_submit`` resolves to privacy's ``submit_compute_job``, which
hands the call to the compute service's: a session had the platform's
provider key run its image, with the resources it named, over
``/bridge/v1/action``, capability invoke and ``request_execution``, while
``submit_compute_job`` itself answered 403. The walk below followed a method
through ``self`` and its own module only, so it did not see the hand-on. A
held oracle type that is not hashable (a list, a dict) raised ``TypeError``
out of the refusal: HTTP 500 at both HTTP doors and an exception out of the
tool dispatcher. And ``POST /api/v1/stablecoin/transfer`` was a session route
whose handler names the sender from the body, with ``transfer_stablecoin``
dispatched for a session at every dispatcher with a ``from_addr`` it named.

THE THIRD DEFECT (the review of the second change). The census read what the
platform's wallet signs and which requests a service sends, not what rides in
them, and a pair that reached a send could be kept by listing it as a read,
with a reason nothing checked. ``oracles_plus.redstone_request`` was listed as
"a GET of a public data package"; it sends the platform's RedStone API key,
when one is configured, to ``{gateway}/data-packages/latest/{data_service_id}``
with the id the request writes, so a session had the platform's key read any
path on the gateway (``../../v1/anything?all=1#``) over ``/bridge/v1/action``
and ``request_execution``: the shape the branch already refused for the
oracle's sports type. And the walk followed no callable held to be called
later: a bound method of another service kept on ``self``, a lambda kept on
``self``, a module-level table of methods. The review planted each of those
three as a new action whose method had the platform's wallet sign to a
contract the request named, and the census passed; the self-held one was
driven end to end to the platform's signature. This docstring said a call the
walk cannot place is recorded, and a call through a ``self`` attribute was
not.

THE CHANGE. ``runtime/access_policy.py`` refuses a session each pair in
``REFUSED_TO_A_SESSION``, at every door a session reaches: capability invoke,
``/bridge/v1/action``, and the tool dispatcher for ``request_execution`` and
``platform_action``. It decides on the method an action reaches: a pair in
``HANDS_THE_CALL_TO`` hands the call on, inside the services layer, to a
method a session is refused, bound or held on, and is refused with it, a
``platform_action`` ``service`` override onto such a method included. Where
the one address a request names is the one the platform acts for and the
platform spends only gas on it, the action is kept and bound: a Lens profile,
a social or creator token, a Push subscription name the session's own
address or are refused (``BOUND_TO_THE_CALLER``). The oracle keeps a price, a
weather reading and a randomness request for a session, and refuses any
other value of the type, whatever its type (``HELD_FOR_A_SESSION``). The
stablecoin transfer route is not a session route (gateway/session_routes.py,
generated), so its operation is refused to a session at every dispatcher
with it. ``redstone_request`` is refused to a session: the platform's server
would send, with its credential, a request whose address the request writes.
The operator's key keeps every one over ``/bridge/v1/action`` and Neo's
``platform_action``, and a dispatch with no HTTP caller keeps them; the
capability invoke route runs no capability the catalog marks unavailable,
whoever asks.

THE CENSUS. The tables are derived, not only written. Three readings of the
source say what the platform's wallet or a platform credential does on what a
request names:

  * the signing census's listing of every address a request supplies to a
    call the services layer signs (``SERVICE_ADDRESSES``: a payee, an asset,
    or the contract the call is sent to), and its two payees encoded as bytes;
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
    ``socket``, ``websockets``, ``websocket``);
  * what rides in each of those requests (``Rides``, and the account of it
    beside it below): for its URL, its method, the names and the values of its
    query, its headers and its body, whether a value the request wrote, the
    platform's configuration, or a credential read from it reaches that part,
    the client's own arguments included. A request is of the class a session
    may not have the platform send when the request writes any part of its URL
    or its method; or when a platform credential rides with it and the request
    writes a header, a query parameter's name or any part of the body, or,
    on anything but a read, a query value. The reads a session keeps that
    carry a credential beside query values the request writes are listed
    (``KEPT_READS``).

The services layer is then read as one program (``Layer``): every top-level
class and function under ``runtime/blockchain/services/``, and what each
function reaches. A method reaches another method of its class through
``self`` or ``cls`` (a call, or a reference such as a dispatch table of bound
methods), one it inherits from a class of the layer, a function of its module
or one it imports from the layer, a method named through its class
(``SomeService.method``), and a method of an object it calls one on, where the
walk can place that object's class. It places it from what builds it (a
constructor, ``ServiceRegistry.get`` with a constant service name, a function
or method that returns one), carried through a local name, a ``self``
attribute any method of the class writes, a property, an element of a
``self`` dict, list or tuple, an ``await``, an ``and``/``or``, a conditional,
a parameter or return annotation, and the arguments every call it places
hands a parameter, to a fixed point. It reaches, too, what a callable held to
be called later holds: a method or a function taken as a value and kept on
``self`` or in a class attribute (by any method of the class family), in a
module name, handed to a parameter that another object keeps, or run by a
lambda or a def inside the method, alone or inside a dict, a list, a partial
or any other value. A call it cannot place is recorded: a call on an object
whose class it cannot place, and a call through a ``self`` attribute that
holds nothing it can place. One whose method has the name of a function that
reaches a payee, an asset, a contract or a send, a method looked up by a name
computed at run time, and a call through a ``self`` attribute, fail the
census where any dispatchable pair reaches them. A class name defined twice,
a base the walk does not read, an ACTION_MAP pair that names no def the walk
reads, a service class that binds an action's method name any other way, and
one that answers an attribute at run time (``__getattr__``) fail it too.

A call into a held method (the oracle's ``request``) is followed, for a
session, unless every call on that edge hands the held parameter a constant
the hold allows, which is what a session may send the method directly; a
function that only hands its own parameter on as the held parameter holds
what it wraps (``request_safe``). Which handler each value the hold allows
runs is read from the method's own table, and none may reach a request of the
class. Every method a dispatch can run, the ``service`` override included, is
read. Each pair that reaches what the readings find must be refused to a
session, handed on (``HANDS_THE_CALL_TO``, which must equal what the walk
finds; a hand-on to a pair every door refuses on request is not one, for the
reason runtime/access_policy.py gives), bound, held, already refused (to
every caller, or to a session because its route is the operator's), or
listed here with the reason it is not the class, and one that reaches a
request of the class cannot be listed; an entry in those tables the
readings do not find fails too, so neither side can drift.

WHAT THIS DOES NOT READ, stated. A payee, an asset or a contract the address
walk does not read (see its own docstring); an amount; what a part of a
request means beyond where its value comes from (a query value under a name
the code fixes is kept whatever the name is for); a credential configured
under a name that does not say it is one and riding only in a URL; an object
handed in from outside the services layer, and code outside it (a call on
such an object is recorded, and fails the census by the rules above); a
request sent by any shape not named above; code replaced at run time. What a
parameter carries is read for every call together, not call by call, so a
value one caller hands a helper is taken as what every caller hands it. A
dedicated ``/api/v1`` route a session reaches runs what its handler pins
(checked below against the routes the gateway builds, and followed through
the layer), not what a request names.

CONTROL. Of this file's 89 tests, 55 are marked [control] and 34 [guard].

Laid over the merge of main into this branch (the commit "Merge main into
fix/oldq-census: durable execution, dark by default, as schema migration
11"), 8 fail, each a control, each on redstone_request: the class control
(the census listed it as a read), the RedStone drive (the bridge answered 200
and the platform's key went out, from the bridge and from request_execution,
in a GET at the path the request wrote), the door drive, both chat drives and
the durable drive, which read what they drive from the walks, the registry
(it offered redstone_request), and the table control. The census's own new
controls were run with the census as it stood there: it reached none of the
six planted shapes a callable is held in (_HELD_CALLABLE_SHAPES), recorded
no call through a ``self`` attribute, and reported nothing for four of the
eleven plants of the review (the three a callable is held in, and the read at
a path the request writes, listed as a read); those eleven fail there. It
reported the other seven, as the review found, and each of those seven fails
here when the part of the census that catches it is taken out: the address
walk, the payee listing, the placing of a constructor, of a local name, the
computed-name rule, the name rule, the HTTP walk. The other 29 controls pass
there as the change before left them. The 34 guards pass there and here. All
89 pass here.

The change before this one was measured the same way: this file as it left
it, 50 tests, laid over the merge of main before it ("Merge main into
fix/oldq-census: one spelling for a caller, schema migration 10, a fault that
binds under OBSERVE, and test prose that names a commit by subject") failed
11 controls and passed the other 23 and the 16 guards; and before that, 29
tests laid over this branch's census-wording commit ("The signing and
attestation censuses name the shapes they read and claim no more, ...")
failed 16 and passed 13.
"""

from __future__ import annotations

import ast
import asyncio
import json
import pathlib
import re
import sys
import time
from typing import NamedTuple

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


# ── the services layer read as one program ──────────────────────────────
#
# A method hands the call on: to another method of its own class, to a
# function of its module or one it imports, and to a method of an object it
# holds, whether that object is another service or a component class. The
# walk follows each of those it can place. It reads the class of the object a
# call is made on from what builds it (a constructor, ``ServiceRegistry.get``
# with a constant service name, a function or method that returns one) and
# carries it through a local name, a ``self`` attribute any method of the
# class writes, a property, an element of a ``self`` dict, list or tuple, an
# ``await``, an ``and``/``or``, a conditional, a parameter's annotation, a
# return annotation, and the arguments each call the walk places hands a
# parameter. A method a class inherits from a class of the layer is its own.
# A call on an object the walk cannot place is recorded, and one whose method
# name is that of a function which reaches what the census looks for fails
# the census (test_no_call_the_walk_cannot_place_names_what_reaches_a_send).

_FN = (ast.FunctionDef, ast.AsyncFunctionDef)
#: What a class of the layer may inherit from that is not a class of the layer.
_LIBRARY_BASES = frozenset({"object", "Exception", "ValueError", "RuntimeError", "KeyError",
                            "LookupError", "PermissionError", "TypeError", "Enum", "IntEnum",
                            "str", "int", "dict", "ABC", "TypedDict", "NamedTuple", "Protocol"})
_PROPERTIES = frozenset({"property", "cached_property"})


class Layer:
    """Every top-level class and function under runtime/blockchain/services/,
    what each ``self`` attribute, parameter and return can hold of those
    classes, and which functions each function reaches."""

    def __init__(self, trees: dict | None = None, services: dict | None = None):
        from runtime.blockchain.services.registry import _SERVICE_MAP
        self.service_class = {svc: cls for svc, (_m, cls) in _SERVICE_MAP.items()}
        self.service_class.update(services or {})
        if trees is None:
            trees = {str(path.relative_to(ROOT)): ast.parse(path.read_text(encoding="utf-8"))
                     for path in sorted(SERVICES.rglob("*.py"))}
        self.trees = trees
        self.classes: dict = {}
        self.duplicates: list = []
        self.functions: dict = {}
        for rel, tree in trees.items():
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    if node.name in self.classes:
                        self.duplicates.append(node.name)
                    self.classes[node.name] = (rel, node)
                elif isinstance(node, _FN):
                    self.functions[(rel, node.name)] = node
        self.imports = {rel: self._imports(rel, tree) for rel, tree in trees.items()}
        self._methods: dict = {}
        self.attrs: dict = {}      # (class, attribute) -> classes it can hold
        self.elements: dict = {}   # (class, attribute) -> classes an element can be
        self.returns: dict = {}    # function -> classes it can return
        self.params: dict = {}     # (function, parameter) -> classes it can be handed
        self.units = list(self._units())
        self.defs = {key: fn for key, fn, _cls, _rel in self.units}
        self._solve()
        self.callables, self.module_callables = self._read_callables()
        self.edges, self.unplaced = self._read_edges()
        self._rides = None

    # -- names --------------------------------------------------------------

    def _module_file(self, rel: str, level: int, module: str | None) -> str | None:
        if level:
            base = pathlib.PurePosixPath(rel).parent
            for _ in range(level - 1):
                base = base.parent
            target = base.joinpath(*module.split(".")) if module else base
        elif (module or "").startswith("runtime.blockchain.services"):
            target = pathlib.PurePosixPath(*module.split("."))
        else:
            return None
        for candidate in (f"{target}.py", f"{target}/__init__.py"):
            if candidate in self.trees:
                return candidate
        return None

    def _imports(self, rel: str, tree) -> dict:
        """Local name -> (file, name) for each ``from ... import`` of the layer,
        at any depth of the module."""
        out = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                source = self._module_file(rel, n.level, n.module)
                if source is not None:
                    for a in n.names:
                        out[a.asname or a.name] = (source, a.name)
        return out

    def function(self, rel: str, name: str, seen=frozenset()):
        """The key of the top-level function *name* means in *rel*, or None."""
        if (rel, name) in self.functions:
            return (rel, name)
        imported = self.imports.get(rel, {}).get(name)
        if imported is None or (rel, name) in seen:
            return None
        return self.function(*imported, seen | {(rel, name)})

    def class_named(self, rel: str, name: str) -> str | None:
        """The class of the layer *name* means in *rel*, or None."""
        imported = self.imports.get(rel, {}).get(name)
        if imported is not None and imported[1] in self.classes:
            return imported[1]
        if name in self.classes and self.classes[name][0] == rel:
            return name
        return None

    def methods(self, cls: str) -> dict:
        """name -> (key, def) for each method *cls* has, those it inherits from
        a class of the layer included."""
        if cls not in self._methods:
            rel, node = self.classes[cls]
            out: dict = {}
            self._methods[cls] = out
            for base in reversed(node.bases):
                name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", None)
                if name in self.classes and name != cls:
                    out.update(self.methods(name))
            for n in node.body:
                if isinstance(n, _FN):
                    out[n.name] = ((rel, f"{cls}.{n.name}"), n)
        return self._methods[cls]

    def unread_bases(self) -> list:
        return sorted(f"{rel} {name}: {ast.unparse(b)}" for name, (rel, node) in self.classes.items()
                      for b in node.bases
                      if not ((isinstance(b, ast.Name) and (b.id in self.classes or b.id in _LIBRARY_BASES))
                              or (isinstance(b, ast.Attribute) and b.attr in _LIBRARY_BASES)))

    def _units(self):
        """(key, def, class or None, file) for each top-level function and method."""
        for (rel, name), fn in self.functions.items():
            yield (rel, name), fn, None, rel
        for cls, (rel, node) in self.classes.items():
            for n in node.body:
                if isinstance(n, _FN):
                    yield (rel, f"{cls}.{n.name}"), n, cls, rel

    # -- what an expression can be ------------------------------------------

    def _annotated(self, rel: str, annotation) -> set:
        if annotation is None:
            return set()
        names = {n.id for n in ast.walk(annotation) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(annotation) if isinstance(n, ast.Attribute)}
        names |= {n.value for n in ast.walk(annotation)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        return {c for c in (self.class_named(rel, x) or (x if x in self.classes else None)
                            for x in names) if c}

    def _property(self, cls: str, attr: str) -> set:
        found = self.methods(cls).get(attr)
        if found is None:
            return set()
        key, fn = found
        if not any((isinstance(d, ast.Name) and d.id in _PROPERTIES)
                   or (isinstance(d, ast.Attribute) and d.attr in _PROPERTIES)
                   for d in fn.decorator_list):
            return set()
        return set(self.returns.get(key, ()))

    def types(self, expr, unit, seen=frozenset()) -> set:
        """The classes of the layer *expr* can be, inside *unit*."""
        key, fn, cls, rel, bindings = unit
        if isinstance(expr, (ast.Await, ast.NamedExpr)):
            return self.types(expr.value, unit, seen)
        if isinstance(expr, ast.BoolOp):
            return set().union(*(self.types(v, unit, seen) for v in expr.values))
        if isinstance(expr, ast.IfExp):
            return self.types(expr.body, unit, seen) | self.types(expr.orelse, unit, seen)
        if isinstance(expr, ast.Name):
            if expr.id in ("self", "cls") and cls:
                return {cls}
            out = set(self.params.get((key, expr.id), ()))
            for arg in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs:
                if arg.arg == expr.id:
                    out |= self._annotated(rel, arg.annotation)
            if expr.id in bindings and expr.id not in seen:
                for value in bindings[expr.id]:
                    out |= self.types(value, unit, seen | {expr.id})
            return out
        if isinstance(expr, ast.Attribute):
            out = set()
            for c in self.types(expr.value, unit, seen):
                out |= set(self.attrs.get((c, expr.attr), ())) | self._property(c, expr.attr)
            return out
        if isinstance(expr, ast.Subscript) and isinstance(expr.value, ast.Attribute):
            return set().union(*(set(self.elements.get((c, expr.value.attr), ()))
                                 for c in self.types(expr.value.value, unit, seen)))
        if isinstance(expr, ast.Call):
            f = expr.func
            if isinstance(f, ast.Name):
                named = self.class_named(rel, f.id)
                if named:
                    return {named}
                target = self.function(rel, f.id)
                return set(self.returns.get(target, ())) if target else set()
            if isinstance(f, ast.Attribute):
                if f.attr in self.classes:
                    return {f.attr}
                out = set()
                for c in self.types(f.value, unit, seen):
                    if (c == "ServiceRegistry" and f.attr == "get" and expr.args
                            and isinstance(expr.args[0], ast.Constant)
                            and expr.args[0].value in self.service_class):
                        out.add(self.service_class[expr.args[0].value])
                    found = self.methods(c).get(f.attr)
                    if found:
                        out |= set(self.returns.get(found[0], ()))
                if f.attr == "get" and isinstance(f.value, ast.Attribute):
                    for c in self.types(f.value.value, unit, seen):
                        out |= set(self.elements.get((c, f.value.attr), ()))
                return out
        return set()

    def callees(self, call, unit) -> list:
        """(key, def, bound) for each function the walk places *call* on;
        *bound* when the first parameter is the instance."""
        key, fn, cls, rel, bindings = unit
        f = call.func
        out = []
        if isinstance(f, ast.Name):
            target = self.function(rel, f.id)
            if target:
                out.append((target, self.functions[target], False))
            named = self.class_named(rel, f.id)
            if named and "__init__" in self.methods(named):
                out.append((*self.methods(named)["__init__"], True))
        elif isinstance(f, ast.Attribute):
            if f.attr in self.classes and "__init__" in self.methods(f.attr):
                out.append((*self.methods(f.attr)["__init__"], True))
            for c in self.types(f.value, unit):
                found = self.methods(c).get(f.attr)
                if found:
                    out.append((*found, True))
        return out

    # -- to a fixed point ---------------------------------------------------

    def _add(self, table: dict, key, values: set) -> bool:
        current = table.setdefault(key, set())
        if values <= current:
            return False
        current |= values
        return True

    def _solve(self) -> None:
        for cls, (rel, node) in self.classes.items():
            for n in node.body:
                if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                    self._add(self.attrs, (cls, n.target.id), self._annotated(rel, n.annotation))
        units = [(key, fn, cls, rel, signing._bindings(fn)) for key, fn, cls, rel in self.units]
        changed = True
        while changed:
            changed = False
            for unit in units:
                key, fn, cls, rel, _b = unit
                changed |= self._add(self.returns, key, self._annotated(rel, fn.returns))
                for n in signing._own_nodes(fn):
                    if isinstance(n, ast.Return) and n.value is not None:
                        changed |= self._add(self.returns, key, self.types(n.value, unit))
                    elif isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None and cls:
                        targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                        for t in targets:
                            holder = t.value if isinstance(t, ast.Subscript) else t
                            if not (isinstance(holder, ast.Attribute) and isinstance(holder.value, ast.Name)
                                    and holder.value.id == "self"):
                                continue
                            if t is holder:
                                found = self.types(n.value, unit)
                                if isinstance(n, ast.AnnAssign):
                                    found |= self._annotated(rel, n.annotation)
                                changed |= self._add(self.attrs, (cls, t.attr), found)
                                items = (n.value.values if isinstance(n.value, ast.Dict)
                                         else n.value.elts if isinstance(n.value, (ast.List, ast.Tuple, ast.Set))
                                         else ())
                                changed |= self._add(self.elements, (cls, t.attr),
                                                     set().union(*(self.types(v, unit) for v in items if v)))
                            else:
                                changed |= self._add(self.elements, (cls, holder.attr),
                                                     self.types(n.value, unit))
                    if isinstance(n, ast.Call):
                        for target, tfn, bound in self.callees(n, unit):
                            names = [a.arg for a in tfn.args.posonlyargs + tfn.args.args]
                            names = names[1:] if bound else names
                            for name, arg in zip(names, n.args):
                                if not isinstance(arg, ast.Starred):
                                    changed |= self._add(self.params, (target, name), self.types(arg, unit))
                            for kw in n.keywords:
                                if kw.arg:
                                    changed |= self._add(self.params, (target, kw.arg),
                                                         self.types(kw.value, unit))

    # -- what a name or an attribute holds, to be called later ---------------
    #
    # A method or a function is taken as a value and called afterwards: bound
    # to another service (``self._breed = NFTLendingService(config).breed_nft``),
    # wrapped in a lambda or a def inside the method, or put in a table at the
    # level of a module or a class (``{'breed': NFTLendingService.breed_nft}``).
    # What such a ``self`` attribute, class attribute or module name holds is
    # read from every value written to it, and a function that reads the name
    # reaches what it holds.

    def family(self, cls: str) -> set:
        """*cls*, the classes of the layer it inherits from, and those that
        inherit from it: a ``self`` attribute one of them writes is theirs."""
        if not hasattr(self, "_families"):
            bases = {c: [b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")
                         for b in node.bases] for c, (_r, node) in self.classes.items()}
            heirs: dict = {}
            for c, names in bases.items():
                for b in names:
                    heirs.setdefault(b, []).append(c)
            self._families = {}
            for start in self.classes:
                out, stack = set(), [start]
                while stack:
                    c = stack.pop()
                    if c in out or c not in self.classes:
                        continue
                    out.add(c)
                    stack += bases[c] + heirs.get(c, [])
                self._families[start] = frozenset(out)
        return set(self._families.get(cls, ()))

    def _nested_def(self, fn, name: str):
        if not hasattr(self, "_inner_defs"):
            self._inner_defs = {}
        if id(fn) not in self._inner_defs:
            self._inner_defs[id(fn)] = {n.name: n for n in ast.walk(fn)
                                        if isinstance(n, _FN) and n is not fn}
        return self._inner_defs[id(fn)].get(name)

    def _method_value(self, cls: str, name: str, *, instance: bool):
        """The method *name* of *cls* taken as a value, or None: a property
        read on an instance is evaluated there, not taken."""
        found = self.methods(cls).get(name)
        if found is None:
            return None
        if instance and any((isinstance(d, ast.Name) and d.id in _PROPERTIES)
                            or (isinstance(d, ast.Attribute) and d.attr in _PROPERTIES)
                            for d in found[1].decorator_list):
            return None
        return found[0]

    def _taken(self, n, unit, seen=frozenset()) -> set:
        """The functions node *n* names as a value (not what a call returns).
        Remembered once what every attribute and name holds is settled."""
        memo = getattr(self, "_taken_memo", None)
        if memo is not None and not seen:
            found = memo.get((unit[0], id(n)))
            if found is None:
                found = memo[(unit[0], id(n))] = frozenset(self._taken_now(n, unit, seen))
            return set(found)
        return self._taken_now(n, unit, seen)

    def _taken_now(self, n, unit, seen) -> set:
        key, fn, cls, rel, bindings = unit
        out: set = set()
        if isinstance(n, ast.Attribute):
            base = n.value
            if isinstance(base, ast.Name) and base.id in ("self", "cls") and cls:
                found = self._method_value(cls, n.attr, instance=True)
                if found:
                    out.add(found)
                for c in self.family(cls):
                    out |= self.callables.get((c, n.attr), set())
                return out
            named = self.class_named(rel, base.id) if isinstance(base, ast.Name) else None
            if named:
                found = self._method_value(named, n.attr, instance=False)
                if found:
                    out.add(found)
                out |= self.callables.get((named, n.attr), set())
                return out
            for c in self.types(base, unit):
                found = self._method_value(c, n.attr, instance=True)
                if found:
                    out.add(found)
                for f in self.family(c):
                    out |= self.callables.get((f, n.attr), set())
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            target = self.function(rel, n.id)
            if target:
                out.add(target)
            out |= self.module_held(rel, n.id)
            out |= self.param_callables.get((key, n.id), set())
            inner = self._nested_def(fn, n.id) if n.id not in seen else None
            if inner is not None:
                out |= self._runs(inner.body, unit, seen | {n.id})
            if n.id in bindings and n.id not in seen:
                for value in bindings[n.id]:
                    if not isinstance(value, signing._Opaque):
                        out |= self.refs(value, unit, seen | {n.id})
        return out

    def _runs(self, body, unit, seen=frozenset()) -> set:
        """What running *body* (a lambda's, or a def's inside a function)
        reaches directly: each function it calls or takes."""
        out: set = set()
        for stmt in (body if isinstance(body, list) else [body]):
            for n in ast.walk(stmt):
                if isinstance(n, ast.Call):
                    out |= {t for t, _f, _b in self.callees(n, unit)}
                out |= self._taken(n, unit, seen)
        return out

    def refs(self, expr, unit, seen=frozenset()) -> set:
        """The functions *expr* holds, to be called later: a method or a
        function taken as a value, bound or through its class's name, and what a
        lambda runs, anywhere inside it (a dict, a list, a partial, ...). A call
        made while the value is built is not held; its arguments may be."""
        out: set = set()
        parents = {id(c): p for p in ast.walk(expr) for c in ast.iter_child_nodes(p)}
        for n in ast.walk(expr):
            if isinstance(n, ast.Lambda):
                out |= self._runs(n.body, unit, seen)
                continue
            parent = parents.get(id(n))
            if isinstance(parent, ast.Call) and parent.func is n:
                continue
            out |= self._taken(n, unit, seen)
        return out

    def module_held(self, rel: str, name: str, seen=frozenset()) -> set:
        """What the module name *name* means in *rel* holds, imported or not."""
        if (rel, name) in self.module_callables:
            return set(self.module_callables[(rel, name)])
        imported = self.imports.get(rel, {}).get(name)
        if imported is None or (rel, name) in seen:
            return set()
        return self.module_held(*imported, seen | {(rel, name)})

    def _read_callables(self):
        """({(class, attribute): functions}, {(file, name): functions}): what
        each ``self`` or class attribute and each module name holds, from every
        value written to it, to a fixed point."""
        self.callables, self.module_callables, self.param_callables = {}, {}, {}
        empty = ast.parse("def _():\n    pass\n").body[0]
        writes = []     # (table, key, value, unit)
        for rel, tree in self.trees.items():
            for node in tree.body:
                if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                    unit = ((rel, "<module>"), empty, None, rel, {})
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in targets:
                        writes += [("module", (rel, name), node.value, unit)
                                   for name in signing._stored(t)]
                elif isinstance(node, ast.ClassDef):
                    unit = ((rel, f"{node.name}.<class>"), empty, node.name, rel, {})
                    for n in node.body:
                        if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                            for t in targets:
                                writes += [("class", (node.name, name), n.value, unit)
                                           for name in signing._stored(t)]
        for key, fn, cls, rel in self.units:
            unit = (key, fn, cls, rel, signing._bindings(fn))
            for n in ast.walk(fn):
                if isinstance(n, ast.Call):
                    # A callable handed to a parameter is held by that parameter.
                    for target, tfn, bound in self.callees(n, unit):
                        names = [a.arg for a in tfn.args.posonlyargs + tfn.args.args]
                        if bound and not any(isinstance(d, ast.Name) and d.id == "staticmethod"
                                             for d in tfn.decorator_list):
                            names = names[1:]
                        for name, arg in zip(names, n.args):
                            if not isinstance(arg, ast.Starred):
                                writes.append(("param", (target, name), arg, unit))
                        writes += [("param", (target, kw.arg), kw.value, unit)
                                   for kw in n.keywords if kw.arg]
                if not cls:
                    continue
                if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and n.value is not None:
                    for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                        root = signing._root(t)
                        if root and root[0] == "self":
                            writes.append(("class", (cls, root[1]), n.value, unit))
                elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr in signing.MUTATORS):
                    root = signing._root(n.func.value)
                    if root and root[0] == "self":
                        value = ast.Tuple(elts=[*n.args, *(k.value for k in n.keywords)],
                                          ctx=ast.Load())
                        writes.append(("class", (cls, root[1]), value, unit))
        changed = True
        while changed:
            changed = False
            for table, where, value, unit in writes:
                held = self.refs(value, unit)
                into = {"module": self.module_callables, "param": self.param_callables}.get(
                    table, self.callables)
                changed |= self._add(into, where, held)
        self._taken_memo = {}
        return self.callables, self.module_callables

    # -- what each function reaches -----------------------------------------

    def _read_edges(self):
        """({function: {function it reaches: [each call or reference]}},
        {function: [(line, name, text)] of each it cannot place})."""
        edges: dict = {}
        unplaced: dict = {}
        for key, fn, cls, rel in self.units:
            unit = (key, fn, cls, rel, signing._bindings(fn))
            out: dict = {}
            lost: list = []
            clients = _clients(fn)
            parents = {id(c): p for p in ast.walk(fn) for c in ast.iter_child_nodes(p)}

            def site(node):
                parent = parents.get(id(node))
                return parent if isinstance(parent, ast.Call) and parent.func is node else None

            def called(node):
                """A call made through *node*: on it, or on an element of it."""
                parent = parents.get(id(node))
                while isinstance(parent, ast.Subscript) and parent.value is node:
                    node, parent = parent, parents.get(id(parent))
                return isinstance(parent, ast.Call) and parent.func is node

            own = self.methods(cls) if cls else {}
            for n in ast.walk(fn):
                if isinstance(n, ast.Attribute):
                    base = n.value
                    if isinstance(base, ast.Name) and base.id in ("self", "cls") and cls:
                        if n.attr in own:
                            out.setdefault(own[n.attr][0], []).append(site(n))
                            continue
                        held = set().union(*(self.callables.get((c, n.attr), set())
                                             for c in self.family(cls)))
                        for target in held:
                            out.setdefault(target, []).append(site(n))
                        if not held and called(n):
                            lost.append((n.lineno, f"self.{n.attr}", ast.unparse(n)[:120]))
                        continue
                    named = self.class_named(rel, base.id) if isinstance(base, ast.Name) else None
                    if named and (n.attr in self.methods(named)
                                  or self.callables.get((named, n.attr))):
                        for target in self._taken(n, unit):
                            out.setdefault(target, []).append(site(n))
                        continue
                    placed = self.types(base, unit)
                    for c in placed:
                        found = self.methods(c).get(n.attr)
                        if found:
                            out.setdefault(found[0], []).append(site(n))
                        for target in set().union(*(self.callables.get((f, n.attr), set())
                                                    for f in self.family(c))):
                            out.setdefault(target, []).append(site(n))
                    if placed or (isinstance(base, ast.Attribute) and base.attr == "functions"):
                        continue
                    if isinstance(base, ast.Name) and (base.id in clients or base.id in HTTP_MODULES):
                        continue
                    lost.append((n.lineno, n.attr, ast.unparse(n)[:120]))
                elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                    target = self.function(rel, n.id)
                    if target:
                        out.setdefault(target, []).append(site(n))
                    for held in self.module_held(rel, n.id):
                        out.setdefault(held, []).append(site(n))
                    named = self.class_named(rel, n.id)
                    if named and "__init__" in self.methods(named):
                        out.setdefault(self.methods(named)["__init__"][0], []).append(site(n))
                elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "getattr"
                      and len(n.args) > 1 and not isinstance(n.args[1], ast.Constant)):
                    lost.append((n.lineno, "getattr", ast.unparse(n)[:120]))
            edges[key] = out
            unplaced[key] = lost
        return edges, unplaced

    def node(self, service: str, method: str):
        """The function a dispatch of (*service*, *method*) runs, or None."""
        cls = self.service_class.get(service)
        found = self.methods(cls).get(method) if cls in self.classes else None
        return found[0] if found else None

    def dispatchable(self, extra_names=frozenset()) -> dict:
        """(service, method) -> function, for every pair a dispatch can run: an
        ACTION_MAP method name on any service that has it (a platform_action
        ``service`` override moves an action's method onto another service).
        *extra_names* are method names a planted ACTION_MAP would add."""
        from runtime.blockchain.services.service_dispatcher import ACTION_MAP
        names = {method for _service, method in ACTION_MAP.values()} | set(extra_names)
        return {(svc, name): self.node(svc, name) for svc, cls in self.service_class.items()
                if cls in self.classes for name in names & set(self.methods(cls))}

    def reach(self, start, cut=frozenset()) -> set:
        """Every function *start* reaches, *start* included, not following an
        edge in *cut*."""
        seen, stack = set(), [start]
        while stack:
            key = stack.pop()
            if key in seen:
                continue
            seen.add(key)
            stack.extend(t for t in self.edges.get(key, ()) if (key, t) not in cut)
        return seen

    def _argument(self, target, call, field: str):
        """What *call* hands *target*'s parameter *field*, or None."""
        for kw in call.keywords:
            if kw.arg == field:
                return kw.value
        fn = self.defs[target]
        names = [a.arg for a in fn.args.posonlyargs + fn.args.args]
        names = names[1:] if "." in target[1] else names
        if field in names and names.index(field) < len(call.args):
            value = call.args[names.index(field)]
            return None if isinstance(value, ast.Starred) else value
        return None

    def held(self, held: dict, sites: set) -> dict:
        """*held* ({function: (parameter, allowed values)}) and each function
        that hands one of them, as the held parameter, only a parameter of its
        own it does not rebind, and reaches nothing else the census looks for:
        a wrapper holds what it wraps. To a fixed point."""
        out = dict(held)
        changed = True
        while changed:
            changed = False
            for key, targets in self.edges.items():
                into = [t for t in targets if t in out and t != key]
                if key in out or not into:
                    continue
                if any(self.reach(t) & sites for t in targets if t not in out):
                    continue
                fn = self.defs[key]
                own = {a.arg for a in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs}
                rebound = set(signing._bindings(fn))
                names, allowed = set(), None
                for t in into:
                    field, values = out[t]
                    allowed = values if allowed is None else allowed & values
                    for call in targets[t]:
                        value = self._argument(t, call, field) if call is not None else None
                        names.add(value.id if isinstance(value, ast.Name) and value.id in own
                                  and value.id not in rebound else None)
                if len(names) == 1 and None not in names:
                    out[key] = (names.pop(), allowed)
                    changed = True
        return out

    def pinned(self, held: dict) -> set:
        """The edges into a held function on which every call hands the held
        parameter a constant the hold allows: {(function, held function)}."""
        out = set()
        for key, targets in self.edges.items():
            for target, calls in targets.items():
                if target not in held or target == key:
                    continue
                field, allowed = held[target]
                values = [self._argument(target, call, field) if call is not None else None
                          for call in calls]
                if calls and all(isinstance(v, ast.Constant) and isinstance(v.value, str)
                                 and v.value in allowed for v in values):
                    out.add((key, target))
        return out


# ── what rides in each request the services layer sends ─────────────────
#
# The walk above says which functions send. This says what each request
# carries, part by part — its URL, its method, its query (the names of its
# parameters, and their values), its headers and its body — and where each
# part comes from: the request (a value the caller handed in), the platform's
# configuration, or a credential read from it. It is read from the code, as
# one program: a function's parameter carries what every call the walk places
# hands it (context by context, not per call), a ``self`` attribute what every
# method of its class family writes into it, a return what every ``return``
# gives, a name what every binding and every write into it (``d[k] = v``,
# ``update``, ``setdefault``, an element added) gives, to a fixed point.
#
# Where it starts: every method a dispatch or a gateway route can run is
# handed the request; so is a function the walk sees taken as a value (it
# cannot say what the caller hands it), the parameters of a lambda or a def
# inside a function, a module name a function writes from what it was handed,
# and a function nothing in the layer calls. A constructor nothing in the
# layer calls is handed the platform's configuration: the registry builds
# the services from it. A value read from ``os.environ`` is configuration.
#
# A credential: a value read from the configuration under a name that says it
# is one (a key, a token, a secret, a password, an app id, a signer, a
# bearer, ``auth...``), wherever it rides; and, since the walk does not tell a
# key from any other configured value there, every configured value that
# rides in the headers, the query or the body.
#
# The class, a request a user session may not have the platform send:
#   * the request writes any part of the URL itself (its host, its path, or a
#     query string written into it) or its method, credential or none; or
#   * a platform credential rides with it, and the request writes a header, a
#     query parameter's name or any part of the body, or it is not a read
#     (GET, HEAD, OPTIONS) and the request writes any part at all.
# Kept for a session: a request with no part the request writes, and a read
# to an address the platform fixes whose only parts the request writes are
# values the client encodes under query names the code fixes (the city a
# weather reading is for, the id of the message a tracker reports on).
# Those with a credential are listed, each with its reason (KEPT_READS).

REQUEST, CONFIGURATION, CREDENTIAL = "request", "configuration", "credential"
_CREDENTIAL_WORDS = frozenset({"key", "apikey", "token", "secret", "password", "passphrase",
                               "bearer", "auth", "authorization", "appid", "credential",
                               "credentials", "jwt", "signer", "cookie", "private"})
_URL_ARGUMENTS = frozenset({"url", "base_url", "proxy", "proxies", "mounts", "transport"})
_QUERY_ARGUMENTS = frozenset({"params"})
_HEADER_ARGUMENTS = frozenset({"headers", "cookies", "auth"})
_INERT_ARGUMENTS = frozenset({"timeout", "follow_redirects", "allow_redirects", "verify",
                              "ssl", "raise_for_status", "http2", "limits", "trust_env"})
_WRITES_INTO = frozenset({"update", "setdefault", "append", "extend", "insert", "add",
                          "__setitem__"})
_NOTHING: frozenset = frozenset()


def _credential_name(name: object) -> bool:
    """Whether a configured value's name, a header's or a query name says it
    is a credential."""
    if not isinstance(name, str):
        return False
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)
    return (re.sub(r"[-_\s]", "", name).lower() in _CREDENTIAL_WORDS
            or any(w.lower() in _CREDENTIAL_WORDS for w in words))


def _is_static(fn) -> bool:
    return any(isinstance(d, ast.Name) and d.id == "staticmethod" for d in fn.decorator_list)


def _all_params(fn) -> set:
    a = fn.args
    names = {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
    names |= {x.arg for x in (a.vararg, a.kwarg) if x is not None}
    return names - {"self", "cls"}


class Carried(NamedTuple):
    """What one request a function sends carries, part by part: each part the
    set of REQUEST, CONFIGURATION and CREDENTIAL that reach it."""
    verb: str
    url: frozenset
    method: frozenset
    query_names: frozenset
    query_values: frozenset
    headers: frozenset
    body: frozenset

    @property
    def credential(self) -> bool:
        parts = (self.url, self.method, self.query_names, self.query_values, self.headers, self.body)
        return (any(CREDENTIAL in p for p in parts)
                or any(CONFIGURATION in p for p in parts[2:]))

    @property
    def request_writes(self) -> bool:
        return any(REQUEST in p for p in self[1:])

    def why(self) -> list[str]:
        """Why a session may not have the platform send it, or []."""
        out = []
        if REQUEST in self.url:
            out.append("the request writes its URL")
        if REQUEST in self.method:
            out.append("the request writes its method")
        if self.credential:
            parts = (self.url, self.method, self.query_names, self.query_values, self.headers,
                     self.body)
            rides = ("a platform credential" if any(CREDENTIAL in p for p in parts)
                     else "a configured value, counted as a platform credential,")
            for part, what in ((self.headers, "a header"), (self.query_names, "a query name"),
                               (self.body, "its body")):
                if REQUEST in part:
                    out.append(f"{rides} rides with {what} the request writes")
            if self.verb not in READ_VERBS and REQUEST in self.query_values:
                out.append(f"{rides} rides with a query value the request writes, on a "
                           f"{self.verb.upper()} that is not a read")
        return out


def send_calls(fn) -> list:
    """(call, verb, the call that built its client or None) for each HTTP
    request *fn* sends, as http_sends finds them."""
    factories = {}
    for n in ast.walk(fn):
        if isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                ctx = item.context_expr
                if (isinstance(ctx, ast.Call) and _is_factory(ctx.func)
                        and isinstance(item.optional_vars, ast.Name)):
                    factories[item.optional_vars.id] = ctx
    out = []
    for n in ast.walk(fn):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)):
            continue
        if n.func.value.id in factories or n.func.value.id in HTTP_MODULES:
            verb = _verb(n)
            if verb is not None:
                out.append((n, verb, factories.get(n.func.value.id)))
    return out


class Rides:
    """What reaches each part of every request the layer sends: see above."""

    def __init__(self, layer: "Layer", entries: set):
        self.layer = layer
        self.units = {key: (key, fn, cls, rel, signing._bindings(fn))
                      for key, fn, cls, rel in layer.units}
        self.params = {key: _all_params(u[1]) for key, u in self.units.items()}
        self.inner = {key: {x for n in ast.walk(u[1]) if isinstance(n, (ast.Lambda, *_FN))
                            and n is not u[1] for x in _all_params(n)}
                      for key, u in self.units.items()}
        self.written = {key: self._writes_into(u[1]) for key, u in self.units.items()}
        self.module_tainted = {rel: signing._taint(tree)[1] for rel, tree in layer.trees.items()}
        self.calls = {key: [(n, layer.callees(n, u)) for n in ast.walk(u[1]) if isinstance(n, ast.Call)]
                      for key, u in self.units.items()}
        self._placed = {id(n): placed for found in self.calls.values() for n, placed in found}
        self.P: dict = {}      # (function, parameter) -> what reaches it
        self.K: dict = {}      # (function, parameter) -> (names, values) of a mapping
        self.A: dict = {}      # (class, attribute) -> what reaches it
        self.R: dict = {}      # function -> what its returns carry
        self.RK: dict = {}     # function -> (names, values) of a mapping it returns
        self.M: dict = {}      # (file, module name) or (class, attribute) at class level
        self._memo: dict = {}
        called = {t for found in self.calls.values() for _n, placed in found for t, _f, _b in placed}
        taken = set()
        for key, unit in self.units.items():
            taken |= self._taken_as_values(unit)
        both = (frozenset({REQUEST}), frozenset({REQUEST}))
        for key, unit in self.units.items():
            fn = unit[1]
            if key in entries or key in taken:
                seed = both
            elif key not in called:
                seed = ((frozenset({CONFIGURATION}),) * 2 if fn.name == "__init__" else both)
            else:
                continue
            for name in self.params[key]:
                self._add(self.P, (key, name), seed[1])
                self._add2(self.K, (key, name), seed)
        empty = ast.parse("def _():\n    pass\n").body[0]
        self.statics = []
        for rel, tree in layer.trees.items():
            for node in tree.body:
                if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                    unit = ((rel, "<module>"), empty, None, rel, {})
                    for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                        self.statics += [((rel, name), node.value, unit) for name in signing._stored(t)]
                elif isinstance(node, ast.ClassDef):
                    unit = ((rel, f"{node.name}.<class>"), empty, node.name, rel, {})
                    for n in node.body:
                        if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                            for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                                self.statics += [((node.name, name), n.value, unit)
                                                 for name in signing._stored(t)]
        self._solve()

    def _taken_as_values(self, unit) -> set:
        """The functions *unit* takes as values, to be called with what the
        walk cannot see: a method or a function not called where it is named,
        and a class of the layer named other than to build it, in an
        annotation or in isinstance."""
        key, fn, cls, rel, bindings = unit
        skip = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.arg) and n.annotation is not None:
                skip |= {id(x) for x in ast.walk(n.annotation)}
            elif isinstance(n, (ast.AnnAssign, *_FN)):
                ann = n.annotation if isinstance(n, ast.AnnAssign) else n.returns
                if ann is not None:
                    skip |= {id(x) for x in ast.walk(ann)}
            elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id in ("isinstance", "issubclass") and len(n.args) > 1):
                skip |= {id(x) for x in ast.walk(n.args[1])}
        parents = {id(c): p for p in ast.walk(fn) for c in ast.iter_child_nodes(p)}
        out = set()
        for n in ast.walk(fn):
            if id(n) in skip or not isinstance(n, (ast.Name, ast.Attribute)):
                continue
            parent = parents.get(id(n))
            if isinstance(parent, ast.Call) and parent.func is n:
                continue
            if isinstance(parent, ast.Attribute) and parent.value is n:
                continue            # read through, not taken: x.attr
            out |= self.layer._taken(n, unit)
            named = (self.layer.class_named(rel, n.id) if isinstance(n, ast.Name)
                     and isinstance(n.ctx, ast.Load) else None)
            if named and "__init__" in self.layer.methods(named):
                out.add(self.layer.methods(named)["__init__"][0])
        return out

    # -- the tables ---------------------------------------------------------

    @staticmethod
    def _add(table: dict, key, values) -> bool:
        current = table.get(key, _NOTHING)
        if values <= current:
            table.setdefault(key, current)
            return False
        table[key] = current | values
        return True

    def _add2(self, table: dict, key, pair) -> bool:
        names, values = table.get(key, (_NOTHING, _NOTHING))
        if pair[0] <= names and pair[1] <= values:
            table.setdefault(key, (names, values))
            return False
        table[key] = (names | pair[0], values | pair[1])
        return True

    @staticmethod
    def _writes_into(fn) -> dict:
        """name -> [(key or None, value)] for each write into a local name's
        contents: ``d[k] = v``, ``d.update(x, k=v)``, ``d.setdefault(k, v)``, an
        element added, ``dict.update(d, ...)`` and ``operator.setitem(d, ...)``.
        A key of None is one the walk does not read; the value "<mapping>" key
        marks a mapping merged in."""
        out: dict = {}
        for n in ast.walk(fn):
            targets = (n.targets if isinstance(n, ast.Assign)
                       else [n.target] if isinstance(n, (ast.AugAssign, ast.AnnAssign)) else [])
            for t in targets:
                if isinstance(t, ast.Subscript):
                    root = signing._root(t)
                    if root and root[0] == "name" and n.value is not None:
                        key = t.slice if isinstance(t.value, ast.Name) else None
                        out.setdefault(root[1], []).append((key, n.value))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                recv, attr = n.func.value, n.func.attr
                if isinstance(recv, ast.Name) and attr in _WRITES_INTO:
                    if attr == "update":
                        out.setdefault(recv.id, []).extend(
                            [("<mapping>", a) for a in n.args]
                            + [(ast.Constant(k.arg) if k.arg else "<mapping>", k.value)
                               for k in n.keywords])
                    elif attr in ("setdefault", "__setitem__") and n.args:
                        out.setdefault(recv.id, []).append((n.args[0], ast.Tuple(
                            elts=n.args[1:], ctx=ast.Load())))
                    else:
                        out.setdefault(recv.id, []).append((None, ast.Tuple(
                            elts=[*n.args, *(k.value for k in n.keywords)], ctx=ast.Load())))
                elif attr in ("update", "setitem", "__setitem__") and n.args and isinstance(
                        n.args[0], ast.Name):
                    out.setdefault(n.args[0].id, []).append((None, ast.Tuple(
                        elts=[*n.args[1:], *(k.value for k in n.keywords)], ctx=ast.Load())))
        return out

    def _solve(self) -> None:
        kinds = (ast.Return, ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Call)
        own = {key: [n for n in signing._own_nodes(u[1]) if isinstance(n, kinds)]
               for key, u in self.units.items()}
        changed = True
        while changed:
            changed = False
            self._memo = {}
            for where, value, unit in self.statics:
                changed |= self._add(self.M, where, self.origins(value, unit))
            for key, unit in self.units.items():
                _k, fn, cls, rel, _b = unit
                for n in own[key]:
                    if isinstance(n, ast.Return) and n.value is not None:
                        changed |= self._add(self.R, key, self.origins(n.value, unit))
                        changed |= self._add2(self.RK, key, self.keyed(n.value, unit))
                    elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and cls \
                            and n.value is not None:
                        for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                            root = signing._root(t)
                            if root and root[0] == "self":
                                found = self.origins(n.value, unit)
                                if isinstance(t, ast.Subscript) and not isinstance(
                                        t.slice, ast.Constant):
                                    found |= self.origins(t.slice, unit)
                                changed |= self._add(self.A, (cls, root[1]), found)
                    elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and cls
                          and n.func.attr in _WRITES_INTO):
                        root = signing._root(n.func.value)
                        if root and root[0] == "self":
                            found = _NOTHING.union(*(self.origins(a, unit) for a in
                                                     [*n.args, *(k.value for k in n.keywords)]))
                            changed |= self._add(self.A, (cls, root[1]), found)
                for n, placed in self.calls[key]:
                    for target, tfn, bound in placed:
                        changed |= self._hand(n, target, tfn, bound, unit)

    def _hand(self, call, target, tfn, bound, unit) -> bool:
        """Hand *target*'s parameters what *call* gives them."""
        a = tfn.args
        positional = [x.arg for x in a.posonlyargs + a.args]
        if bound and not _is_static(tfn):
            positional = positional[1:]
        named = set(positional) | {x.arg for x in a.kwonlyargs}
        changed = False
        for i, arg in enumerate(call.args):
            if isinstance(arg, ast.Starred):
                o = self.origins(arg.value, unit)
                for name in positional[i:] + ([a.vararg.arg] if a.vararg else []):
                    changed |= self._add(self.P, (target, name), o)
                    changed |= self._add2(self.K, (target, name), (o, o))
                break
            name = (positional[i] if i < len(positional)
                    else a.vararg.arg if a.vararg else None)
            if name is not None:
                changed |= self._add(self.P, (target, name), self.origins(arg, unit))
                changed |= self._add2(self.K, (target, name), self.keyed(arg, unit))
        for kw in call.keywords:
            if kw.arg is None:
                names, values = self.keyed(kw.value, unit)
                for name in named:
                    changed |= self._add(self.P, (target, name), names | values)
                    changed |= self._add2(self.K, (target, name), (names | values,) * 2)
                if a.kwarg:
                    changed |= self._add(self.P, (target, a.kwarg.arg), names | values)
                    changed |= self._add2(self.K, (target, a.kwarg.arg), (names, values))
            elif kw.arg in named:
                changed |= self._add(self.P, (target, kw.arg), self.origins(kw.value, unit))
                changed |= self._add2(self.K, (target, kw.arg), self.keyed(kw.value, unit))
            elif a.kwarg:
                o = self.origins(kw.value, unit)
                changed |= self._add(self.P, (target, a.kwarg.arg), o)
                changed |= self._add2(self.K, (target, a.kwarg.arg), (_NOTHING, o))
        return changed

    # -- what reaches an expression -----------------------------------------

    def _callees(self, call, unit) -> list:
        placed = self._placed.get(id(call))
        return self.layer.callees(call, unit) if placed is None else placed

    def _attr(self, cls: str, name: str) -> frozenset:
        out = set()
        for c in self.layer.family(cls):
            out |= self.A.get((c, name), _NOTHING) | self.M.get((c, name), _NOTHING)
            found = self.layer.methods(c).get(name)
            if found and any((isinstance(d, ast.Name) and d.id in _PROPERTIES)
                             or (isinstance(d, ast.Attribute) and d.attr in _PROPERTIES)
                             for d in found[1].decorator_list):
                out |= self.R.get(found[0], _NOTHING)
        return frozenset(out)

    def _module(self, rel: str, name: str, seen=frozenset()) -> frozenset:
        if (rel, name) in self.M:
            return self.M[(rel, name)]
        imported = self.layer.imports.get(rel, {}).get(name)
        if imported is None or (rel, name) in seen:
            return _NOTHING
        return self._module(*imported, seen | {(rel, name)})

    def origins(self, e, unit, seen=frozenset()) -> frozenset:
        """What reaches the value of *e* inside *unit*."""
        memo = (unit[0], id(e)) if not seen else None
        if memo is not None and memo in self._memo:
            return self._memo[memo]
        found = frozenset(self._origins(e, unit, seen))
        if memo is not None:
            self._memo[memo] = found
        return found

    def _origins(self, e, unit, seen) -> set:
        key, fn, cls, rel, bindings = unit
        if e is None or isinstance(e, (ast.Constant, ast.Lambda)):
            return set()
        if isinstance(e, signing._Opaque):
            return {REQUEST}
        if isinstance(e, ast.Name):
            name = e.id
            if name in ("self", "cls"):
                return set()
            out = set(self.P.get((key, name), _NOTHING)) if name in self.params.get(key, ()) else set()
            if name in bindings and name not in seen:
                for value in bindings[name]:
                    out |= self.origins(value, unit, seen | {name})
            elif name in self.inner.get(key, ()) or name in self.module_tainted.get(rel, ()):
                out.add(REQUEST)
            elif name not in self.params.get(key, ()):
                out |= self._module(rel, name)
            for k, value in self.written.get(key, {}).get(name, []) if name not in seen else []:
                if isinstance(k, ast.AST) and not isinstance(k, ast.Constant):
                    out |= self.origins(k, unit, seen | {name})
                out |= self.origins(value, unit, seen | {name})
            return out
        if isinstance(e, ast.Attribute):
            base = e.value
            if isinstance(base, ast.Name) and base.id in ("self", "cls") and cls:
                out = set(self._attr(cls, e.attr))
            else:
                out = set(self.origins(base, unit, seen))
                for c in self.layer.types(base, unit):
                    out |= self._attr(c, e.attr)
                named = self.layer.class_named(rel, base.id) if isinstance(base, ast.Name) else None
                if named:
                    out |= self._attr(named, e.attr)
                if isinstance(base, ast.Name) and base.id == "os" and e.attr == "environ":
                    out.add(CONFIGURATION)
            if CONFIGURATION in out and _credential_name(e.attr):
                out.add(CREDENTIAL)
            return out
        if isinstance(e, ast.Subscript):
            out = set(self.origins(e.value, unit, seen))
            k = e.slice
            if isinstance(k, ast.Constant):
                if CONFIGURATION in out and _credential_name(k.value):
                    out.add(CREDENTIAL)
            else:
                out |= self.origins(k, unit, seen)
            return out
        if isinstance(e, ast.Call):
            f = e.func
            args = [a.value if isinstance(a, ast.Starred) else a for a in e.args]
            args += [k.value for k in e.keywords]
            environment = ((isinstance(f, ast.Attribute) and f.attr == "getenv")
                           or (isinstance(f, ast.Name) and f.id == "getenv"))
            placed = [] if environment else self._callees(e, unit)
            if placed:
                out = set()
                for target, _tfn, _bound in placed:
                    out |= self.R.get(target, _NOTHING)
                return out
            out = {CONFIGURATION} if environment else set()
            if isinstance(f, ast.Attribute):
                out |= self.origins(f.value, unit, seen)
            first = e.args[0] if e.args else None
            if (isinstance(first, ast.Constant) and CONFIGURATION in out
                    and isinstance(f, (ast.Attribute, ast.Name))
                    and (environment or f.attr in ("get", "pop", "setdefault"))
                    and _credential_name(first.value)):
                out.add(CREDENTIAL)
            for a in args:
                out |= self.origins(a, unit, seen)
            return out
        if isinstance(e, ast.comprehension):
            return set(self.origins(e.iter, unit, seen)).union(
                *(self.origins(x, unit, seen) for x in e.ifs))
        out = set()
        for child in ast.iter_child_nodes(e):
            if isinstance(child, (ast.expr, ast.comprehension)):
                out |= self.origins(child, unit, seen)
        return out

    def keyed(self, e, unit, seen=frozenset()) -> tuple:
        """(what reaches the names, what reaches the values) of a mapping *e*;
        both what reaches *e* where its shape is not one the walk reads."""
        key, fn, cls, rel, bindings = unit
        if e is None or isinstance(e, ast.Constant):
            return _NOTHING, _NOTHING
        if isinstance(e, ast.Dict):
            names, values = set(), set()
            for k, v in zip(e.keys, e.values):
                if k is None:
                    n2, v2 = self.keyed(v, unit, seen)
                    names |= n2
                    values |= v2
                elif isinstance(k, ast.Constant):
                    values |= self.origins(v, unit, seen)
                else:
                    names |= self.origins(k, unit, seen)
                    values |= self.origins(v, unit, seen)
            return frozenset(names), frozenset(values)
        if isinstance(e, (ast.Await, ast.NamedExpr)):
            return self.keyed(e.value, unit, seen)
        if isinstance(e, (ast.IfExp, ast.BoolOp)):
            parts = [e.body, e.orelse] if isinstance(e, ast.IfExp) else e.values
            found = [self.keyed(p, unit, seen) for p in parts]
            return (_NOTHING.union(*(f[0] for f in found)), _NOTHING.union(*(f[1] for f in found)))
        if isinstance(e, ast.Name) and e.id not in ("self", "cls") and e.id not in seen and (
                e.id in bindings or e.id in self.params.get(key, ())):
            names, values = set(), set()
            if e.id in self.params.get(key, ()):
                n2, v2 = self.K.get((key, e.id), (_NOTHING, _NOTHING))
                names |= n2
                values |= v2
            for value in bindings.get(e.id, []):
                n2, v2 = self.keyed(value, unit, seen | {e.id})
                names |= n2
                values |= v2
            for k, value in self.written.get(key, {}).get(e.id, []):
                if k == "<mapping>":
                    n2, v2 = self.keyed(value, unit, seen | {e.id})
                    names |= n2
                    values |= v2
                    continue
                o = self.origins(value, unit, seen | {e.id})
                if not isinstance(k, ast.Constant):
                    names |= o | (self.origins(k, unit, seen | {e.id}) if k is not None else o)
                values |= o
            return frozenset(names), frozenset(values)
        if isinstance(e, ast.Call):
            f = e.func
            placed = self._callees(e, unit)
            if placed:
                names, values = set(), set()
                for target, _tfn, _bound in placed:
                    n2, v2 = self.RK.get(target, (_NOTHING, _NOTHING))
                    names |= n2
                    values |= v2
                return frozenset(names), frozenset(values)
            if isinstance(f, ast.Name) and f.id == "dict":
                names, values = set(), set()
                for a in e.args:
                    n2, v2 = self.keyed(a, unit, seen)
                    names |= n2
                    values |= v2
                for k in e.keywords:
                    if k.arg is None:
                        n2, v2 = self.keyed(k.value, unit, seen)
                        names |= n2
                        values |= v2
                    else:
                        values |= self.origins(k.value, unit, seen)
                return frozenset(names), frozenset(values)
            if isinstance(f, ast.Attribute) and f.attr == "copy" and not e.args:
                return self.keyed(f.value, unit, seen)
        o = self.origins(e, unit, seen)
        return o, o

    # -- each send ----------------------------------------------------------

    def carried(self, key, call, verb, factory) -> Carried:
        unit = self.units[key]
        url, method, query, headers, body = [], [], [], [], []
        args = list(call.args)
        if call.func.attr in VERB_ARGUMENT and args:
            method.append(args.pop(0))
        if args:
            url.append(args.pop(0))
        body += args
        keywords = list(call.keywords)
        if factory is not None:
            keywords += factory.keywords
            url += factory.args[:1]
        for kw in keywords:
            if kw.arg is None:
                body.append(kw.value)
            elif kw.arg == "method":
                method.append(kw.value)
            elif kw.arg in _URL_ARGUMENTS:
                url.append(kw.value)
            elif kw.arg in _QUERY_ARGUMENTS:
                query.append(kw.value)
            elif kw.arg in _HEADER_ARGUMENTS:
                headers.append(kw.value)
            elif kw.arg not in _INERT_ARGUMENTS:
                body.append(kw.value)

        def union(exprs, read=None):
            return _NOTHING.union(*((read or self.origins)(x, unit) for x in exprs))
        shapes = [self.keyed(q, unit) for q in query]
        header_shapes = [self.keyed(h, unit) for h in headers]
        header_parts = _NOTHING.union(*(n | v for n, v in header_shapes))
        # A configured value under a header or query name that says it is a
        # credential is one, whatever the name it was configured under.
        for exprs in (headers, query):
            for x in exprs:
                if isinstance(x, ast.Dict) and any(
                        isinstance(k, ast.Constant) and _credential_name(k.value)
                        and CONFIGURATION in self.origins(v, unit)
                        for k, v in zip(x.keys, x.values)):
                    header_parts |= {CREDENTIAL}
        return Carried(verb, union(url), union(method),
                       _NOTHING.union(*(n for n, _v in shapes)),
                       _NOTHING.union(*(v for _n, v in shapes)),
                       header_parts, union(body))

    def sends(self) -> dict:
        """(file, qualified name) -> [Carried] for every function that sends."""
        out = {}
        for key, unit in self.units.items():
            found = [self.carried(key, call, verb, factory)
                     for call, verb, factory in send_calls(unit[1])]
            if found:
                out[key] = found
        return out


_LAYER: list = []


def _layer() -> Layer:
    if not _LAYER:
        _LAYER.append(Layer())
    return _LAYER[0]


def all_http_sends(trees: dict | None = None) -> dict:
    """(file, qualified name) -> [(line, verb)] for every top-level function or
    method under the services directory that sends."""
    if trees is None:
        trees = {str(path.relative_to(ROOT)): ast.parse(path.read_text(encoding="utf-8"))
                 for path in sorted(SERVICES.rglob("*.py"))}
    out = {}
    for rel, tree in sorted(trees.items()):
        for qual, fn, _cls, outer in signing._functions(tree):
            sends = http_sends(fn)
            if sends and not outer:
                out[(rel, qual)] = sends
    return out


_PAYEE_BYTES = {(signing._CCIP, "CrossChainMessagingService.bridge_token_ccip"),
                (signing._CCIP, "CrossChainMessagingService.bridge_stargate")}


class Derived(NamedTuple):
    onchain: set          # pairs that reach a platform-signed payee, asset or contract
    http: dict            # pairs that reach an HTTP send -> its verbs
    unreached_payees: set
    unreached_sends: set
    reached: dict         # pair -> every function it reaches for a session
    pairs: dict           # pair -> the function it runs
    sites: set            # every function the census looks for
    cut: set              # the edges into a held method a session may take
    carried: dict = {}    # sending function -> [Carried], one per request it sends
    class_sends: dict = {}  # sending function -> why a session may not have it sent
    classed: dict = {}    # pair -> the sending functions of the class it reaches


def _route_nodes(layer: Layer) -> set:
    """The function each pair a gateway route runs names: handed the request."""
    from scripts.generate_session_routes import live_route_pairs
    return {layer.node(*pair) for pairs in live_route_pairs().values() for pair in pairs} - {None}


_DERIVED: dict = {}


def derive(layer: Layer | None = None, extra_names=frozenset(),
           extra_payees=frozenset()) -> Derived:
    """What each dispatchable pair reaches, for a session: a call into a held
    method is followed unless every such call hands it a value the hold
    allows (that is what a session may send it directly); and what each
    request the layer sends carries. *layer*, *extra_names* and
    *extra_payees* are a planted layer's."""
    from runtime.access_policy import HELD_FOR_A_SESSION
    memo = (id(layer), frozenset(extra_names), frozenset(extra_payees))
    if memo in _DERIVED:
        return _DERIVED[memo]
    layer = layer or _layer()
    pairs = layer.dispatchable(extra_names)
    payee_sites = {(f, q) for (f, q, _fn, _path), kind in signing.SERVICE_ADDRESSES.items()
                   if kind in (signing.PAYEE, signing.ASSET, signing.CONTRACT)} | _PAYEE_BYTES
    payee_sites |= set(extra_payees)
    sends = all_http_sends(layer.trees)
    held = layer.held({layer.node(*pair): spec for pair, spec in HELD_FOR_A_SESSION.items()},
                      payee_sites | set(sends))
    cut = layer.pinned(held)
    reached = {pair: layer.reach(node, cut) for pair, node in pairs.items()}
    onchain = {pair for pair, funcs in reached.items() if funcs & payee_sites}
    everything = set().union(*(layer.reach(node) for node in pairs.values()))
    unreached_payees = payee_sites - everything
    http = {}
    for pair, funcs in reached.items():
        verbs = sorted({v for site in funcs & set(sends) for _line, v in sends[site]})
        if verbs:
            http[pair] = verbs
    unreached_sends = set(sends) - everything
    carried = Rides(layer, set(pairs.values()) | _route_nodes(layer)).sends()
    class_sends = {site: sorted({why for c in found for why in c.why()})
                   for site, found in carried.items() if any(c.why() for c in found)}
    derived = Derived(onchain, http, unreached_payees, unreached_sends, reached, pairs,
                      payee_sites | set(sends), cut, carried, class_sends, {})
    classed = {}
    for pair, node in pairs.items():
        hit = sorted(_class_reach(layer, derived, node) & set(class_sends))
        if hit:
            classed[pair] = hit
    derived = derived._replace(classed=classed)
    _DERIVED[memo] = derived
    return derived


def _class_reach(layer: Layer, derived: Derived, node) -> set:
    """What *node* reaches for a session, with the held method read call by
    call: a call that pins a value the hold allows reaches what that value
    runs, which test_a_held_value_runs_no_request_of_the_class reads, and the
    insurance triggers' configured custom requests send what the operator
    configured (test_the_insurance_triggers_hand_the_oracle_only_configured_
    urls). Any other call into the held method reaches all of it."""
    from runtime.access_policy import HELD_FOR_A_SESSION
    held = layer.held({layer.node(*pair): spec for pair, spec in HELD_FOR_A_SESSION.items()},
                      derived.sites)
    if node in held or _held_calls_outside_the_hold(layer, derived, node):
        return layer.reach(node, derived.cut)
    into = {(k, t) for k, targets in layer.edges.items() for t in targets if t in held and t != k}
    return layer.reach(node, into)


def handed_on(derived: Derived, decided: set) -> dict:
    """pair -> the other pairs in *decided* whose method it reaches."""
    out = {}
    for pair, funcs in derived.reached.items():
        others = sorted(q for q in decided if q != pair and derived.pairs.get(q) in funcs)
        if others:
            out[pair] = tuple(others)
    return out


#: A pair the walks find that is not the class, each with the reason.
_CONFIGURED_CUSTOM = (
    "reaches the oracle's custom type from the insurance trigger manager, which hands it "
    "a URL read from the operator's configuration and the method GET, and nothing the "
    "request writes (test_the_insurance_triggers_hand_the_oracle_only_configured_urls); "
    "its price and weather reads pin a type a session may send")
OFF_CHAIN_READS = {
    ("advanced_governance", "quadratic_vote"): (
        "relays to the configured Snapshot hub an envelope the voter's own wallet "
        "signed; the hub checks that signature, and no platform credential rides "
        "with it (without one it returns the unsigned payload)"),
    ("ccip", "query_remote_chain"): (
        "a GET of a cross-chain message's public status from the configured tracker; "
        "the optional tracker key meters it"),
    ("insurance", "auto_settle_claim"): _CONFIGURED_CUSTOM,
    ("insurance", "file_claim"): _CONFIGURED_CUSTOM,
    ("oracles_plus", "pyth_pull"): (
        "a GET of public price updates from Pyth's Hermes; no credential is sent"),
}


def _already_refused(pair) -> bool:
    """Refused to every caller, or to a session because its route is the operator's."""
    from gateway.session_routes import SERVICE_METHODS_OFF_ALLOWLIST
    from runtime.access_policy import REFUSED_ON_REQUEST
    return pair in REFUSED_ON_REQUEST or f"{pair[0]}.{pair[1]}" in SERVICE_METHODS_OFF_ALLOWLIST


def _decided() -> set:
    from runtime.access_policy import (
        BOUND_TO_THE_CALLER, HELD_FOR_A_SESSION, REFUSED_TO_A_SESSION)
    return set(REFUSED_TO_A_SESSION) | set(BOUND_TO_THE_CALLER) | set(HELD_FOR_A_SESSION)


def _hands() -> dict:
    """runtime/access_policy.py HANDS_THE_CALL_TO, or {} where it does not
    exist, so a tree without it fails on what the walks find, not on an import."""
    import runtime.access_policy as policy
    return dict(getattr(policy, "HANDS_THE_CALL_TO", {}))


def test_every_pair_the_walks_find_is_refused_bound_held_or_read():
    """[control] Every pair that reaches a platform-signed payee, asset or
    contract, or an HTTP send, by its own code or through what it hands the
    call on to, is refused (itself, or with the method it hands the call to),
    bound, held, already refused, or listed."""
    derived = derive()
    assert len(derived.onchain) >= 15 and len(derived.http) >= 15, (
        len(derived.onchain), len(derived.http))
    decided = _decided() | set(_hands())
    open_ = sorted(f"{s}.{m} ({'signed payee, asset or contract' if (s, m) in derived.onchain else 'HTTP ' + ','.join(derived.http[(s, m)])})"
                   for s, m in derived.onchain | set(derived.http)
                   if (s, m) not in decided and (s, m) not in OFF_CHAIN_READS
                   and not _already_refused((s, m)))
    assert open_ == [], ("a session can have the platform act on what the request names:\n  "
                         + "\n  ".join(open_))


def test_every_action_that_hands_the_call_on_is_refused_with_what_it_reaches():
    """[control] HANDS_THE_CALL_TO is what the walk finds: each dispatchable
    pair that is not itself refused, bound, held or listed, with the pairs a
    session is refused, bound or held on that it hands the call on to. A pair
    that is bound or held reaches none but itself, and a listed read reaches
    none it would be refused."""
    derived = derive()
    decided = _decided()
    handed = handed_on(derived, decided)
    expected = {pair: targets for pair, targets in handed.items()
                if pair not in decided and pair not in OFF_CHAIN_READS}
    assert expected and _hands() == expected, sorted(set(expected.items()) ^ set(_hands().items()))
    from runtime.access_policy import BOUND_TO_THE_CALLER, HELD_FOR_A_SESSION, REFUSED_TO_A_SESSION
    kept = set(BOUND_TO_THE_CALLER) | set(HELD_FOR_A_SESSION)
    assert {p: t for p, t in handed.items() if p in kept} == {}, handed
    assert {p: t for p, t in handed.items() if p in OFF_CHAIN_READS
            and set(t) & (set(REFUSED_TO_A_SESSION) | set(BOUND_TO_THE_CALLER))} == {}, handed


def test_every_table_entry_is_one_the_walks_find():
    """[control] A refusal, a binding, a hold, a hand-on or a listed read the
    walks do not find is a table drifting from the code."""
    derived = derive()
    found = derived.onchain | set(derived.http)
    stale = sorted(f"{s}.{m}" for s, m in (_decided() | set(OFF_CHAIN_READS) | set(_hands()))
                   - found)
    assert stale == [], stale
    for pair in OFF_CHAIN_READS:
        assert pair not in derived.onchain, pair


def test_every_payee_and_send_is_reached():
    """[guard] A payee, asset or contract the address walk lists, or a send,
    that no dispatchable method reaches would be outside the derivation."""
    derived = derive()
    assert derived.unreached_payees == set(), derived.unreached_payees
    assert derived.unreached_sends == set(), derived.unreached_sends


def test_the_listed_reads_send_only_reads_or_what_their_reason_says():
    """[guard] A listed read sends GET only, except the relay and the
    configured custom type named."""
    derived = derive()
    for pair in OFF_CHAIN_READS:
        verbs = set(derived.http[pair])
        assert (verbs <= READ_VERBS or pair == ("advanced_governance", "quadratic_vote")
                or OFF_CHAIN_READS[pair] is _CONFIGURED_CUSTOM), (pair, verbs)


# ── a request the platform sends with its credential, the request writing it ─

def _open_to_the_class(derived: Derived, listed=None) -> list[str]:
    """Each pair that reaches a request of the class, for a session, and is
    not refused (itself, or with what it hands the call to), bound, held or
    already refused: listing it as a read does not keep it."""
    decided = _decided() | set(_hands())
    return sorted(f"{s}.{m}: {q} ({'; '.join(derived.class_sends[(f, q)])})"
                  for (s, m), sites in derived.classed.items()
                  if (s, m) not in decided and not _already_refused((s, m))
                  for f, q in sites)


def test_no_session_has_a_platform_credential_send_what_the_request_writes():
    """[control] Every pair that reaches a request the platform's server sends
    in which the request writes the URL or the method, or with a platform
    credential riding along a header, a query name or a body the request
    writes (or a query value, on anything but a read), is refused to a
    session, handed on, bound or held; none is kept as a listed read. At the
    merge of main into this branch ("Merge main into fix/oldq-census: durable
    execution, dark by default, as schema migration 11") the census read no
    part of a request and listed oracles_plus.redstone_request as a read: a
    GET with the platform's RedStone key, at a path the request writes."""
    derived = derive()
    assert len(derived.class_sends) >= 12 and len(derived.classed) >= 20, (
        sorted(derived.class_sends), sorted(derived.classed))
    open_ = _open_to_the_class(derived)
    assert open_ == [], ("a session can have the platform send, with its credential, what "
                         "the request writes:\n  " + "\n  ".join(open_))
    listed = sorted(f"{s}.{m}" for s, m in OFF_CHAIN_READS if (s, m) in derived.classed)
    assert listed == [], f"listed as a read, and of the class: {listed}"


#: A read the platform's credential makes, which the request writes only a
#: value of, one the client encodes under a query name the code fixes, to an
#: address the platform's configuration fixes. Kept for a session, each with
#: its reason; a new one fails here until it is read.
KEPT_READS = {
    ("runtime/blockchain/services/oracle_gateway/weather_oracle.py", "WeatherOracle._http_get"): (
        "the weather reading a session keeps (HELD_FOR_A_SESSION): the provider's configured "
        "address, the platform's key and units as query values, and the location the "
        "request names as the value of q, or of lat and lon"),
    ("runtime/blockchain/services/ccip/service.py", "CrossChainMessagingService.query_remote_chain"): (
        "the configured tracker's address, the optional tracker key as a bearer header, and "
        "the message id and protocol the request names as the values of messageId and "
        "protocol"),
}


def test_the_credentialed_reads_a_session_keeps_are_the_listed_ones():
    """[guard] The requests with a platform credential in which the request
    writes only query values are exactly KEPT_READS."""
    derived = derive()
    kept = {site for site, found in derived.carried.items() if site not in derived.class_sends
            and any(c.credential and REQUEST in c.query_values for c in found)}
    assert kept == set(KEPT_READS), sorted(kept ^ set(KEPT_READS))


def test_every_action_refused_for_a_credential_reaches_a_request_of_the_class():
    """[guard] The walk of what rides reads what the refusals name: every pair
    refused to a session because a platform credential would act, or send, on
    what the request writes reaches a request of the class."""
    from runtime.access_policy import REFUSED_TO_A_SESSION, _SESSION_PLATFORM_CREDENTIAL
    import runtime.access_policy as policy
    statements = {_SESSION_PLATFORM_CREDENTIAL, getattr(policy, "_SESSION_PLATFORM_SEND", None)}
    derived = derive()
    named = sorted(pair for pair, why in REFUSED_TO_A_SESSION.items() if why in statements)
    assert len(named) >= 12, named
    assert [pair for pair in named if pair not in derived.classed] == [], derived.classed


def _dispatch_table(layer: Layer, node) -> tuple[str, dict] | None:
    """(the held parameter, {value: the handler it runs}) where *node* hands
    its held parameter, and only it, to a method of its class that looks the
    handler up in one dict of that class's own methods keyed by constants,
    by that parameter; None where the census cannot read one."""
    from runtime.access_policy import HELD_FOR_A_SESSION
    field = next(spec[0] for pair, spec in HELD_FOR_A_SESSION.items() if layer.node(*pair) == node)
    found = []
    for target, calls in layer.edges.get(node, {}).items():
        fn = layer.defs[target]
        names = [a.arg for a in fn.args.posonlyargs + fn.args.args][1:]
        params = set()
        for c in calls:
            if c is None:
                continue
            params |= {names[i] for i, a in enumerate(c.args)
                       if isinstance(a, ast.Name) and a.id == field and i < len(names)}
            params |= {k.arg for k in c.keywords if isinstance(k.value, ast.Name) and k.value.id == field}
        if len(params) != 1:
            continue
        (param,) = params
        cls = target[1].split(".")[0]
        bindings = signing._bindings(fn)
        for n in ast.walk(fn):
            if not (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Name)
                    and n.slice.id == param and isinstance(n.value, ast.Name)):
                continue
            tables = bindings.get(n.value.id, [])
            if len(tables) != 1 or not isinstance(tables[0], ast.Dict):
                return None
            out = {}
            for k, v in zip(tables[0].keys, tables[0].values):
                method = (layer.methods(cls).get(v.attr) if isinstance(v, ast.Attribute)
                          and isinstance(v.value, ast.Name) and v.value.id == "self" else None)
                if not isinstance(k, ast.Constant) or method is None:
                    return None
                out[k.value] = method[0]
            found.append(out)
    return (field, found[0]) if len(found) == 1 else None


def test_a_held_value_runs_no_request_of_the_class():
    """[guard] What a session may send the held method runs no request of the
    class: the census reads which handler each value runs from the method's
    own table, and fails where it cannot read one. The values a session may
    not send (the sports and custom types) each reach one."""
    from runtime.access_policy import HELD_FOR_A_SESSION
    layer = _layer()
    derived = derive()
    for pair, (field, allowed) in HELD_FOR_A_SESSION.items():
        table = _dispatch_table(layer, layer.node(*pair))
        assert table is not None and table[0] == field, (pair, table)
        handlers = table[1]
        assert allowed < set(handlers), (allowed, sorted(handlers))
        for value, handler in sorted(handlers.items()):
            hits = layer.reach(handler) & set(derived.class_sends)
            if value in allowed:
                assert hits == set(), (pair, value, hits)
            else:
                assert hits, (pair, value, "reaches no request of the class")


def _unplaced_self_calls(layer: Layer, derived: Derived) -> list[str]:
    """Calls through a ``self`` attribute that holds nothing the walk can
    place, in what a dispatchable pair reaches."""
    reached = set().union(*(layer.reach(node) for node in derived.pairs.values()))
    return sorted(f"{f}:{line} {q}: {text}" for (f, q) in reached
                  for line, name, text in layer.unplaced.get((f, q), [])
                  if name.startswith("self."))


def test_no_callable_held_on_self_is_one_the_walk_cannot_place():
    """[guard] Fail closed: a call through a ``self`` attribute holding a
    callable the walk cannot place (one handed in from outside the layer) is
    reported where a dispatchable pair reaches it."""
    assert _unplaced_self_calls(_layer(), derive()) == []


#: Planted requests, one method each: what the walk of what rides must read.
_PLANTED_SENDS = '''\
import os

import httpx


class Front:
    def __init__(self, config):
        self.config = config
        self._key = config["provider"]["api_key"]

    def _cfg(self):
        return self.config.get("provider", {})

    async def _send(self, method, key, path, body):
        async with httpx.AsyncClient() as client:
            return await client.request(method, self._cfg()["base"] + path, json=body,
                                        headers={"Authorization": f"Bearer {key}"})

    async def a_path_it_writes(self, **p):
        async with httpx.AsyncClient() as client:
            return await client.get(f"{self._cfg()['base']}/data/{p['id']}",
                                    headers={"X-Api-Key": self._key})

    async def a_url_it_writes(self, **p):
        async with httpx.AsyncClient() as client:
            return await client.get(p["url"])

    async def a_method_it_writes(self, **p):
        async with httpx.AsyncClient() as client:
            return await client.request(p["verb"], self._cfg()["base"])

    async def a_query_name_it_writes(self, **p):
        query = dict(p)
        query["apiKey"] = self._key
        async with httpx.AsyncClient() as client:
            return await client.get(self._cfg()["base"], params=query)

    async def a_header_it_writes(self, **p):
        async with httpx.AsyncClient() as client:
            return await client.get(self._cfg()["base"],
                                    headers={"Authorization": self._key, "X-Trace": p["trace"]})

    async def a_body_it_writes(self, **p):
        async with httpx.AsyncClient() as client:
            return await client.post(self._cfg()["base"], json={"content": p["content"]},
                                     headers={"Authorization": f"Bearer {self._key}"})

    async def a_query_value_on_a_post(self, **p):
        async with httpx.AsyncClient() as client:
            return await client.post(self._cfg()["base"], params={"id": p["id"], "key": self._key})

    async def the_key_handed_to_a_helper(self, **p):
        return await self._send("POST", self._cfg().get("api_key"), "/jobs", p)

    async def the_key_on_the_client(self, **p):
        async with httpx.AsyncClient(headers={"Authorization": self._key}) as client:
            return await client.post(self._cfg()["base"], json=p)

    async def a_key_from_the_environment(self, **p):
        headers = {"Authorization": os.environ.get("PROVIDER_TOKEN", "")}
        async with httpx.AsyncClient() as client:
            return await client.post(self._cfg()["base"], json=p, headers=headers)

    async def a_query_value_under_a_fixed_name(self, **p):
        query = {"q": p.get("city")}
        query.update({"appid": self._key})
        async with httpx.AsyncClient() as client:
            return await client.get(self._cfg()["base"] + "/weather", params=query)

    async def a_body_with_no_credential(self, **p):
        async with httpx.AsyncClient() as client:
            return await client.post(self._cfg()["hub"] + "/api/msg", json=p.get("envelope"))

    async def nothing_it_writes(self, **p):
        async with httpx.AsyncClient() as client:
            return await client.get(self._cfg()["base"] + "/status",
                                    headers={"Authorization": self._key})
'''
#: method -> (of the class, carries a platform credential).
_PLANTED_SEND_SHAPES = {
    "a_path_it_writes": (True, True),
    "a_url_it_writes": (True, False),
    "a_method_it_writes": (True, False),
    "a_query_name_it_writes": (True, True),
    "a_header_it_writes": (True, True),
    "a_body_it_writes": (True, True),
    "a_query_value_on_a_post": (True, True),
    "the_key_handed_to_a_helper": (True, True),
    "the_key_on_the_client": (True, True),
    "a_key_from_the_environment": (True, True),
    "a_query_value_under_a_fixed_name": (False, True),
    "a_body_with_no_credential": (False, False),
    "nothing_it_writes": (False, True),
}


@pytest.mark.parametrize("method", sorted(_PLANTED_SEND_SHAPES))
def test_the_walk_reads_what_a_planted_request_carries(method):
    """[guard] Each shape a request carries what the request writes in, or a
    credential, planted: the walk of what rides reads whether it is of the
    class and whether a credential rides with it."""
    if not _PLANTED_SENDS_READ:
        rel = "runtime/blockchain/services/planted/front.py"
        layer = Layer({rel: ast.parse(_PLANTED_SENDS)}, services={"front": "Front"})
        entries = {layer.methods("Front")[m][0] for m in _PLANTED_SEND_SHAPES}
        _PLANTED_SENDS_READ.append(Rides(layer, entries).sends())
    sends = _PLANTED_SENDS_READ[0]
    of_the_class, credential = _PLANTED_SEND_SHAPES[method]
    site = ("runtime/blockchain/services/planted/front.py",
            "Front._send" if method == "the_key_handed_to_a_helper" else f"Front.{method}")
    (carried,) = sends[site]
    assert bool(carried.why()) is of_the_class and carried.credential is credential, (
        method, carried, carried.why())


_PLANTED_SENDS_READ: list = []


def _configured_custom(call) -> bool:
    """True when *call* hands the oracle's held method the custom type with a
    URL read from ``self._config`` and the method GET, and no other field."""
    if call is None or len(call.args) < 2:
        return False
    kind, body = call.args[0], call.args[1]
    if not (isinstance(kind, ast.Constant) and kind.value == "custom" and isinstance(body, ast.Dict)):
        return False
    fields = {k.value: v for k, v in zip(body.keys, body.values) if isinstance(k, ast.Constant)}
    if set(fields) != {"url", "method"} or len(fields) != len(body.keys):
        return False
    if not (isinstance(fields["method"], ast.Constant) and fields["method"].value == "GET"):
        return False
    node = fields["url"]
    while isinstance(node, (ast.Call, ast.Attribute)):
        if (isinstance(node, ast.Attribute) and node.attr == "_config"
                and isinstance(node.value, ast.Name) and node.value.id == "self"):
            return True
        node = node.func if isinstance(node, ast.Call) else node.value
    return False


def _held_calls_outside_the_hold(layer: Layer, derived: Derived, start) -> list:
    """Each call into a held function, from what *start* reaches for a
    session, that neither pins a value the hold allows (those edges are cut)
    nor is a configured custom request."""
    from runtime.access_policy import HELD_FOR_A_SESSION
    held = layer.held({layer.node(*pair): spec for pair, spec in HELD_FOR_A_SESSION.items()},
                      derived.sites)
    def allowed(target, call) -> bool:
        field, values = held[target]
        value = layer._argument(target, call, field) if call is not None else None
        return isinstance(value, ast.Constant) and value.value in values

    out = []
    for key in layer.reach(start, derived.cut):
        for target, calls in layer.edges.get(key, {}).items():
            if target in held and target != key and (key, target) not in derived.cut:
                out += [f"{key[1]} -> {target[1]}: {ast.unparse(c) if c is not None else 'a reference'}"
                        for c in calls if not (allowed(target, c) or _configured_custom(c))]
    return out


def test_the_insurance_triggers_hand_the_oracle_only_configured_urls():
    """[guard] Each call into the held oracle method from what the listed
    insurance pairs reach pins a type a session may send, or is the custom
    type with a URL read from ``self._config`` and the method GET, and no
    other field."""
    layer = _layer()
    derived = derive()
    listed = [p for p in OFF_CHAIN_READS if OFF_CHAIN_READS[p] is _CONFIGURED_CUSTOM]
    assert listed
    for pair in listed:
        assert _held_calls_outside_the_hold(layer, derived, derived.pairs[pair]) == [], pair
    custom = [c for key in layer.reach(derived.pairs[listed[0]], derived.cut)
              for calls in layer.edges.get(key, {}).values() for c in calls if _configured_custom(c)]
    assert len(custom) >= 2, custom


def test_the_oracle_wrappers_reach_nothing_for_a_session():
    """[guard] query_price, query_weather and request_vrf hand the held
    oracle method a type a session may send, through request_safe or
    directly; so what they reach for a session is no send."""
    derived = derive()
    for method in ("query_price", "query_weather", "request_vrf"):
        pair = ("oracle_gateway", method)
        assert pair not in derived.http and pair not in derived.onchain, pair
        assert derived.reached[pair] & derived.sites == set(), pair


def test_no_network_use_in_the_services_is_one_the_walk_does_not_read():
    """[guard] Fail closed: a client or a library the walk does not read is reported."""
    unread = [f"{path.relative_to(ROOT)}:{line} {why}"
              for path in sorted(SERVICES.rglob("*.py"))
              for line, why in http_unread(ast.parse(path.read_text(encoding="utf-8")))]
    assert unread == [], unread


def _senders(layer: Layer, derived: Derived) -> set:
    """The names of the functions that reach what the census looks for."""
    return {q.rsplit(".", 1)[-1] for key in layer.edges if layer.reach(key) & derived.sites
            for _f, q in [key]}


def test_no_call_the_walk_cannot_place_names_what_reaches_a_send():
    """[guard] Fail closed: in what any dispatchable pair reaches, a call on an
    object the walk cannot place whose method has the name of a function that
    reaches a payee, an asset, a contract or a send, and a method looked up by
    a name computed at run time, are reported."""
    layer = _layer()
    derived = derive()
    assert {"submit_compute_job", "store_filecoin", "request"} <= _senders(layer, derived)
    assert _lost_calls(layer, derived) == [], _lost_calls(layer, derived)


def _lost_calls(layer: Layer, derived: Derived) -> list[str]:
    """In what any dispatchable pair reaches, each call on an object the walk
    cannot place whose method has the name of a function that reaches what
    the census looks for, and each method looked up by a computed name."""
    senders = _senders(layer, derived)
    reached = set().union(*(layer.reach(node) for node in derived.pairs.values()))
    return sorted(f"{f}:{line} {q}: {text}" for (f, q) in reached
                  for line, name, text in layer.unplaced.get((f, q), [])
                  if name in senders or name == "getattr")


def test_every_class_of_the_layer_is_one_class_the_walk_reads():
    """[guard] The walk places a class by its name; a name defined twice, or a
    base it does not read, would place a call on the wrong class or none."""
    layer = _layer()
    assert layer.duplicates == [], layer.duplicates
    assert layer.unread_bases() == [], layer.unread_bases()
    assert set(layer.service_class.values()) <= set(layer.classes)


def test_every_method_a_dispatch_can_run_is_a_def_the_walk_reads():
    """[guard] Dispatch finds a method with ``getattr``; the walk reads a def.
    Every ACTION_MAP pair names a def of its service's class (or one it
    inherits from the layer), no service class binds an ACTION_MAP method
    name any other way, and none answers an attribute at run time."""
    import ast as _ast

    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    layer = _layer()
    names = {method for _service, method in ACTION_MAP.values()}
    assert sorted(a for a, pair in ACTION_MAP.items() if layer.node(*pair) is None) == []
    other = []
    for cls in layer.service_class.values():
        _rel, node = layer.classes[cls]
        for n in node.body:
            targets = (n.targets if isinstance(n, _ast.Assign)
                       else [n.target] if isinstance(n, _ast.AnnAssign) else [])
            other += [f"{cls}.{t.id}" for t in targets if isinstance(t, _ast.Name) and t.id in names]
        other += [f"{cls}.{m}" for m in layer.methods(cls) if m in ("__getattr__", "__getattribute__")]
    assert other == [], other


_PLANTED_HAND_ONS = {
    "a service built lazily and returned": (
        "class Front:\n"
        "    def _back(self):\n"
        "        if self._svc is None:\n"
        "            self._svc = Back(self.config)\n"
        "        return self._svc\n"
        "    async def go(self, **p):\n"
        "        return await self._back().send(**p)\n"),
    "a component built in __init__": (
        "class Front:\n"
        "    def __init__(self, config):\n"
        "        self._back = Back(config)\n"
        "    async def go(self, **p):\n"
        "        return await self._back.send(**p)\n"),
    "a property": (
        "class Front:\n"
        "    @property\n"
        "    def back(self) -> 'Back':\n"
        "        return self._b\n"
        "    async def go(self, **p):\n"
        "        return await self.back.send(**p)\n"),
    "a component handed to another's constructor": (
        "class Middle:\n"
        "    def __init__(self, config, back):\n"
        "        self._back = back\n"
        "    async def relay(self, p):\n"
        "        return await self._back.send(**p)\n"
        "class Front:\n"
        "    def __init__(self, config):\n"
        "        self._middle = Middle(config, Back(config))\n"
        "    async def go(self, **p):\n"
        "        return await self._middle.relay(p)\n"),
    "the service registry by name": (
        "class Front:\n"
        "    async def go(self, **p):\n"
        "        svc = ServiceRegistry(self.config).get('compute')\n"
        "        return await svc.send(**p)\n"),
    "a local name, an or and an await": (
        "class Front:\n"
        "    async def go(self, **p):\n"
        "        back = self._cached or Back(self.config)\n"
        "        return await back.send(**p)\n"),
    "a dict of components": (
        "class Front:\n"
        "    def __init__(self, config):\n"
        "        self._by_kind = {'a': Back(config)}\n"
        "    async def go(self, kind, **p):\n"
        "        return await self._by_kind[kind].send(**p)\n"),
    "an imported function": (
        "from .helpers import hand_on\n"
        "class Front:\n"
        "    async def go(self, **p):\n"
        "        return await hand_on(Back(self.config), p)\n"),
    "a method inherited from a class of the layer": (
        "class Base:\n"
        "    async def go(self, **p):\n"
        "        return await Back(self.config).send(**p)\n"
        "class Front(Base):\n"
        "    pass\n"),
    # What the review of the seventh repair planted past the walk, and what
    # the same reading found beside them: a callable held, and called later.
    "a bound method of another service held on self": (
        "class Front:\n"
        "    def __init__(self, config):\n"
        "        self._send = Back(config).send\n"
        "    async def go(self, **p):\n"
        "        return await self._send(**p)\n"),
    "a lambda held on self": (
        "class Front:\n"
        "    def __init__(self, config):\n"
        "        self._send = lambda **p: Back(config).send(**p)\n"
        "    async def go(self, **p):\n"
        "        return await self._send(**p)\n"),
    "a module-level table of methods": (
        "SENDERS = {'send': Back.send}\n"
        "class Front:\n"
        "    async def go(self, **p):\n"
        "        return await SENDERS['send'](Back(self.config), **p)\n"),
    "a def inside __init__ held on self": (
        "class Front:\n"
        "    def __init__(self, config):\n"
        "        def run(**p):\n"
        "            return Back(config).send(**p)\n"
        "        self._run = run\n"
        "    async def go(self, **p):\n"
        "        return await self._run(**p)\n"),
    "a class-level table of methods": (
        "class Front:\n"
        "    SENDERS = {'send': Back.send}\n"
        "    async def go(self, **p):\n"
        "        return await self.SENDERS['send'](Back(self.config), **p)\n"),
    "a method handed to another object, which holds it": (
        "class Middle:\n"
        "    def set_sink(self, sink):\n"
        "        self._sink = sink\n"
        "    async def fire(self, p):\n"
        "        return await self._sink(**p)\n"
        "class Front:\n"
        "    def __init__(self, config):\n"
        "        self._middle = Middle()\n"
        "        self._middle.set_sink(Back(config).send)\n"
        "    async def go(self, **p):\n"
        "        return await self._middle.fire(p)\n"),
}
#: The shapes a callable is held in, planted: the walk at the merge of main
#: into this branch ("Merge main into fix/oldq-census: durable execution, dark
#: by default, as schema migration 11") reached none of them.
_HELD_CALLABLE_SHAPES = frozenset({
    "a bound method of another service held on self", "a lambda held on self",
    "a module-level table of methods", "a def inside __init__ held on self",
    "a class-level table of methods", "a method handed to another object, which holds it"})
_PLANTED_BACK = (
    "import httpx\n"
    "class Back:\n"
    "    async def send(self, **p):\n"
    "        async with httpx.AsyncClient() as c:\n"
    "            return await c.post('https://x.invalid', json=p)\n"
    "class DecentralizedComputeService(Back):\n"
    "    pass\n"
    "class ServiceRegistry:\n"
    "    def get(self, name):\n"
    "        return None\n")
_PLANTED_HELPERS = (
    "async def hand_on(back, p):\n"
    "    return await back.send(**p)\n")


def _planted_layer(front: str) -> Layer:
    base = "runtime/blockchain/services/planted/"
    return Layer({base + "front.py": ast.parse("from .back import Back, ServiceRegistry\n" + front),
                  base + "back.py": ast.parse(_PLANTED_BACK),
                  base + "helpers.py": ast.parse(_PLANTED_HELPERS)})


@pytest.mark.parametrize("shape", sorted(_PLANTED_HAND_ONS))
def test_the_walk_follows_a_planted_hand_on(shape):
    """[control] Each shape a method hands the call on through, planted: the
    walk of this file's census-wording commit ("The signing and attestation
    censuses name the shapes they read and claim no more, ...") followed
    ``self``, ``cls`` and module names only, and reached none of them; the
    walk at the merge of main into this branch reached none of the six a
    callable is held in (_HELD_CALLABLE_SHAPES)."""
    layer = _planted_layer(_PLANTED_HAND_ONS[shape])
    start = layer.methods("Front")["go"][0]
    assert ("runtime/blockchain/services/planted/back.py", "Back.send") in layer.reach(start), (
        shape, layer.reach(start))


def test_the_walk_records_a_call_it_cannot_place():
    """[guard] An object handed in from outside the layer is not placed; the
    call is recorded, so the census can fail on it."""
    layer = _planted_layer(
        "class Front:\n"
        "    async def go(self, client, **p):\n"
        "        return await client.send(**p)\n")
    key = layer.methods("Front")["go"][0]
    assert [name for _line, name, _text in layer.unplaced[key]] == ["send"], layer.unplaced[key]


def test_the_walk_records_a_callable_held_on_self_it_cannot_place():
    """[control] A callable handed in from outside the layer and held on
    ``self`` is not placed; the call through it is recorded, so the census
    can fail on it (test_no_callable_held_on_self_is_one_the_walk_cannot_place).
    The walk at the merge of main into this branch recorded nothing, though
    this file's docstring said a call it cannot place is recorded."""
    layer = _planted_layer(
        "class Front:\n"
        "    def __init__(self, config, callback):\n"
        "        self._callback = callback\n"
        "    async def go(self, **p):\n"
        "        return await self._callback(**p)\n")
    key = layer.methods("Front")["go"][0]
    assert [name for _line, name, _text in layer.unplaced[key]] == ["self._callback"]


def test_a_dispatch_table_of_bound_methods_is_followed():
    """[guard] The oracle reaches its handlers through a dict of bound methods."""
    layer = _layer()
    funcs = {q for _f, q in layer.reach(layer.node("oracle_gateway", "request"))}
    assert "OracleGateway._handle_custom" in funcs, funcs
    assert "WeatherOracle._http_get" in funcs, funcs


def test_the_second_name_of_the_compute_job_is_found():
    """[control] compute_job_submit runs privacy's submit_compute_job, which
    hands the call to the compute service's, which sends the platform's
    provider key: the walk of this file's census-wording commit found it
    nowhere."""
    derived = derive()
    assert ("privacy", "submit_compute_job") in derived.http, sorted(derived.http)
    assert handed_on(derived, {("compute", "submit_compute_job")}).get(
        ("privacy", "submit_compute_job")) == (("compute", "submit_compute_job"),)


# ── the review's plants, in the tree as it is ───────────────────────────
#
# The review of the seventh repair planted ten shapes in a copy of the tree,
# one at a time, each a new action of a new service the platform's wallet or
# credential acts through, and ran the census: it failed on seven and passed
# on three. The ten are planted here together in one new service module read
# beside every real one, each under an action name of its own, and the census
# is derived again over that layer. What it reports is what the tests above
# fail on: a pair that reaches a platform-signed payee, asset or contract, or
# an HTTP send, that nothing decides or lists; a pair that reaches a request of
# the class; a call it cannot place, by the name rule. An eleventh is the shape
# of redstone_request, planted as a listed read.

_PLANTED_SERVICE = "runtime/blockchain/services/relay/service.py"
_PLANTED_RELAY = '''\
import httpx

from runtime.blockchain.services.nft_lending.service import NFTLendingService
from runtime.blockchain.services.registry import ServiceRegistry
from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
from runtime.blockchain.services.storage.service import DecentralizedStorageService

TRANSFER = [{"name": "transfer", "type": "function", "inputs": [
    {"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}]}]
_TABLE = {"breed": NFTLendingService.breed_nft}


class RelayService:
    def __init__(self, config):
        self.config = config
        self._breed = NFTLendingService(config).breed_nft
        self._breed_later = lambda **p: NFTLendingService(config).breed_nft(**p)

    async def relay_held_on_self(self, **p):
        return await self._breed(**p)

    async def relay_lambda_on_self(self, **p):
        return await self._breed_later(**p)

    async def relay_module_table(self, **p):
        return await _TABLE["breed"](NFTLendingService(self.config), **p)

    async def relay_constructed(self, **p):
        return await NFTLendingService(self.config).breed_nft(**p)

    async def relay_dispatcher(self, **p):
        return await ServiceDispatcher(self.config).execute("breed_nft", params=p)

    async def relay_registry_by_variable(self, **p):
        name = p.get("service")
        return await ServiceRegistry(self.config).get(name).breed_nft(**p)

    async def relay_local_alias(self, **p):
        store = DecentralizedStorageService(self.config)
        go = store.ceramic_stream_create
        return await go(**p)

    async def fresh_send(self, **p):
        cfg = self.config["relay"]
        async with httpx.AsyncClient() as client:
            return await client.post(cfg["endpoint"], json=p,
                                     headers={"Authorization": f"Bearer {cfg['api_key']}"})

    async def fresh_read_at_a_written_path(self, **p):
        cfg = self.config["relay"]
        async with httpx.AsyncClient() as client:
            return await client.get(f"{cfg['endpoint']}/packages/{p['package']}",
                                    headers={"X-Api-Key": cfg["api_key"]})

    async def fresh_transfer(self, **p):
        token = self._web3.load_contract(self.config["relay"]["token"], TRANSFER)
        tx = token.functions.transfer(p.get("to"), 1).build_transaction({})
        return await self._web3.send_transaction(tx)
'''
#: shape -> (the planted action, what the census reports for it). The first
#: three passed the census the review ran; the other seven failed it.
_PLANTS = {
    "a bound method of another service held on self": ("relay_held_on_self", "open"),
    "a lambda held on self": ("relay_lambda_on_self", "open"),
    "a module-level table of methods": ("relay_module_table", "open"),
    "a constructor wrapper": ("relay_constructed", "open"),
    "a wrapper through ServiceDispatcher.execute": ("relay_dispatcher", "getattr"),
    "the service registry by a variable name": ("relay_registry_by_variable", "breed_nft"),
    "a local alias of another service's method": ("relay_local_alias", "open"),
    "a fresh send with the platform's key": ("fresh_send", "open"),
    "a fresh platform-signed transfer to an address the request names": (
        "fresh_transfer", "address"),
    "the same transfer, its address listed as a payee": ("fresh_transfer", "open"),
    "a listed read at a path the request writes, with the platform's key": (
        "fresh_read_at_a_written_path", "class"),
}
_PLANTED_READ = {("relay", "fresh_read_at_a_written_path"): "a GET of a public package"}
_PLANTED: list = []


def _planted_census():
    """(layer, derived, the address walk's rows) over the tree with the
    planted service beside it; derived once."""
    if not _PLANTED:
        trees = {str(path.relative_to(ROOT)): ast.parse(path.read_text(encoding="utf-8"))
                 for path in sorted(SERVICES.rglob("*.py"))}
        trees[_PLANTED_SERVICE] = ast.parse(_PLANTED_RELAY)
        layer = Layer(trees, services={"relay": "RelayService"})
        names = {n.name for n in ast.parse(_PLANTED_RELAY).body[-1].body
                 if isinstance(n, _FN) and not n.name.startswith("_")}
        payee = (_PLANTED_SERVICE, "RelayService.fresh_transfer")
        derived = derive(layer, frozenset(names), frozenset({payee}))
        unlisted = derive(layer, frozenset(names))
        rows = set(signing._request_addresses(_PLANTED_RELAY, _PLANTED_SERVICE))
        _PLANTED.append((layer, derived, unlisted, rows))
    return _PLANTED[0]


def census_findings(layer: Layer, derived: Derived, listed: dict) -> list[str]:
    """What the census reports over *derived*, as the tests above read it:
    "open <pair>", "class <pair>", and each call it cannot place."""
    decided = _decided() | set(_hands())
    out = [f"open {pair}" for pair in sorted(derived.onchain | set(derived.http))
           if pair not in decided and pair not in listed and not _already_refused(pair)]
    out += [f"class {pair}" for pair in sorted(derived.classed)
            if pair not in decided and not _already_refused(pair)]
    out += [f"lost {text}" for text in _lost_calls(layer, derived)]
    out += [f"held on self {text}" for text in _unplaced_self_calls(layer, derived)]
    return out


@pytest.mark.parametrize("shape", sorted(_PLANTS))
def test_the_census_fails_on_what_the_review_planted(shape):
    """[control] Each shape the review planted fails the census, over the tree
    as it is. At the merge of main into this branch ("Merge main into
    fix/oldq-census: durable execution, dark by default, as schema migration
    11") the census reported nothing for the three a callable is held in and
    for the read at a written path. Each of the other seven stops being
    reported when the part of the census that catches it is taken out (the
    address walk, the HTTP walk, the constructor, local-name and computed-name
    reading, and the name rule)."""
    layer, derived, unlisted, rows = _planted_census()
    action, report = _PLANTS[shape]
    pair = ("relay", action)
    if report == "address":
        assert ("RelayService.fresh_transfer", "transfer", "to") in rows, rows
        assert not any(k[0] == _PLANTED_SERVICE for k in signing.SERVICE_ADDRESSES)
        assert pair not in unlisted.onchain, "the transfer was found without its listing"
        return
    findings = census_findings(layer, derived, {**OFF_CHAIN_READS, **_PLANTED_READ})
    if report in ("open", "class"):
        expected = [f"{report} {pair}"]
    else:
        expected = [f"lost {f}:{line} {q}: {text}" for f, q in layer.reach(derived.pairs[pair])
                    for line, name, text in layer.unplaced.get((f, q), []) if name == report]
    assert expected and set(expected) <= set(findings), (shape, expected, findings)


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


def _refused_pairs() -> set:
    """The pairs a session must be refused whatever it sends, read from the
    walks, not the tables: every pair they find but those a session is bound
    or held on and the listed reads. Each is refused to a session in
    runtime/access_policy.py or gateway/session_routes.py, itself or with
    the method it hands the call to."""
    from runtime.access_policy import BOUND_TO_THE_CALLER, HELD_FOR_A_SESSION
    derived = derive()
    return ((derived.onchain | set(derived.http))
            - set(BOUND_TO_THE_CALLER) - set(HELD_FOR_A_SESSION) - set(OFF_CHAIN_READS))


def _refused_actions():
    """Every action name that resolves to a refused pair, each name of one
    pair included."""
    out = {}
    for pair in sorted(_refused_pairs()):
        actions = _actions_for(pair)
        assert actions, f"{pair}: no action resolves to it"
        out.update({action: pair for action in actions})
    return out


async def test_no_session_door_dispatches_them(dispatched, tmp_path):
    """[control] Capability invoke and /bridge/v1/action answer a session 403
    for every name of every refused pair before the dispatcher runs."""
    from aiohttp.test_utils import TestClient, TestServer

    from runtime.access_policy import dispatch_pair
    from runtime.capabilities import catalog
    refused = _refused_pairs()
    server = signing._server(tmp_path)
    answered = {}
    async with TestClient(TestServer(server.create_app())) as client:
        await _session(server)
        for action in _refused_actions():
            resp = await client.post("/bridge/v1/action", headers=SESSION,
                                     json={"action": action, "params": {"to": B}, "session_id": "s1"})
            answered[f"bridge {action}"] = resp.status
        for cap in catalog.CAPABILITIES:
            if dispatch_pair(cap["action"]) in refused:
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


#: What the review drove: a method a session is refused, run under another
#: name. compute_job_submit is privacy's submit_compute_job, which hands the
#: call to the compute service's; the platform_action ``service`` override
#: moves submit_compute_job onto privacy the same way. Written out here, not
#: read from the tables, so the control does not rest on what it tests.
SECOND_NAMES = [
    ({"action": "compute_job_submit"}, ("privacy", "submit_compute_job")),
    ({"action": "submit_compute_job", "service": "privacy"}, ("privacy", "submit_compute_job")),
]
JOB = {"requester": B, "image": "somebody/miner:latest", "cpu": 64, "memory": "512Gi", "gpu": 8}


async def test_no_session_door_runs_a_refused_method_under_a_second_name(dispatched, tmp_path):
    """[control] Laid over the merge of main into this branch ("Merge main into
    fix/oldq-census: one spelling for a caller, ..."), compute_job_submit was
    dispatched for a session at /bridge/v1/action, at capability invoke and
    through both chat tools: the refusal read the pair an action names, not
    the method that pair hands the call to."""
    from aiohttp.test_utils import TestClient, TestServer

    from runtime.tools.dispatcher import ToolDispatcher
    server = signing._server(tmp_path)
    answered = {}
    async with TestClient(TestServer(server.create_app())) as client:
        await _session(server)
        resp = await client.post("/bridge/v1/action", headers=SESSION,
                                 json={"action": "compute_job_submit", "params": JOB,
                                       "session_id": "s1"})
        answered["bridge"] = resp.status
        resp = await client.post("/api/v1/capabilities/compute_job_submit/invoke",
                                 headers=SESSION, json={"params": JOB})
        answered["invoke"] = resp.status
    for arguments, _pair in SECOND_NAMES:
        for tool in ("request_execution", "platform_action"):
            if tool == "request_execution" and "service" in arguments:
                continue        # the hand-off takes no service override
            out = await ToolDispatcher({"workspace": "."}).dispatch(
                tool, {**arguments, "params": JOB},
                agent_name="trinity", caller_identity=A, caller_kind="session")
            answered[f"{tool} {arguments}"] = "denied" if "[DENIED]" in out.model_text else out.model_text
    assert dispatched == [], f"a session's doors ran {dispatched}: {answered}"
    assert set(answered.values()) <= {403, "denied"}, answered


def _walked_actions():
    """An action for every pair the walks find, but those every door refuses
    and those listed as reads: what the operator's key must still reach."""
    from runtime.access_policy import REFUSED_ON_REQUEST
    derived = derive()
    out = {}
    for pair in sorted(derived.onchain | set(derived.http)):
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
    assert len(actions) > 30 and "compute_job_submit" in actions and "breed_nft" in actions, actions
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


async def test_the_refusals_hold_with_durable_execution_on(dispatched, tmp_path, monkeypatch):
    """[control] With engines.durable.mode on, /bridge/v1/action refuses a
    session every refused action, an Idempotency-Key sent with each, before
    the gate, the key and the dispatcher: no run is opened and no key bound.
    Chat acting for the session is refused before the tool's handler, so the
    engine's wrap around a tool call is never asked; the operator's tool call
    still runs inside that wrap. (The service dispatcher's run around an
    operator's dispatch is tests/test_durable_replay_corpus.py's to measure.)"""
    from aiohttp.test_utils import TestClient, TestServer

    from gateway.server import GatewayServer
    from runtime.durable import wiring
    from runtime.tools.dispatcher import ToolDispatcher
    from test_route_sweep import SWEEP_CONFIG
    monkeypatch.delenv("MATRIX_DURABLE_MODE", raising=False)
    previous = wiring.current()
    answered, asked, chat = {}, [], {}
    try:
        server = GatewayServer({**SWEEP_CONFIG, "memory_dir": str(tmp_path / "m"),
                                "rexhepi": {"rate_limit_max_actions": 100_000},
                                "database": {"path": str(tmp_path / "s.db")},
                                "engines": {"durable": {"mode": "on"}},
                                "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": "k"}})
        async with TestClient(TestServer(server.create_app())) as client:
            engine = server._durable_engine
            assert engine is not None and engine.mode == "on" and wiring.current() is engine
            await _session(server)
            for i, action in enumerate(_refused_actions()):
                resp = await client.post("/bridge/v1/action",
                                         headers={**SESSION, "Idempotency-Key": f"refused-{i}"},
                                         json={"action": action, "params": {"to": B},
                                               "session_id": "s1"})
                answered[action] = resp.status
            db = server.react_loop.memory.db
            runs = db.fetchall_sync("SELECT * FROM workflow_runs")
            keys = db.fetchall_sync("SELECT * FROM idempotency_keys")
            wrapped = engine.run_tool

            async def run_tool(tool_name, arguments, caller_identity, make_call):
                asked.append(tool_name)
                return await wrapped(tool_name, arguments, caller_identity, make_call)
            monkeypatch.setattr(engine, "run_tool", run_tool)
            for action in _refused_actions():
                out = await ToolDispatcher({"workspace": "."}).dispatch(
                    "request_execution", {"action": action, "params": {"to": B}},
                    agent_name="trinity", caller_identity=A, caller_kind="session")
                chat[action] = "[DENIED]" in out.model_text
            refused_asked = list(asked)
            await ToolDispatcher({"workspace": "."}).dispatch(
                "platform_action", {"action": "breed_nft", "params": {"to": B}},
                agent_name="neo", caller_identity="", caller_kind="operator")
    finally:
        wiring.install(previous)
    assert len(answered) > 20 and set(answered.values()) == {403}, answered
    assert all(chat.values()), chat
    assert runs == [] and keys == [], (runs, keys)
    assert refused_asked == [] and asked == ["platform_action"], asked
    assert dispatched == ["breed_nft"], dispatched


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
            is_success = True
            text = ""

            def raise_for_status(self):
                return None

            def json(self):
                return {"signature": "0x" + "5a" * 65, "dseq": "1"}
        return _Resp()

    async def request(self, method, url, json=None, headers=None, **k):
        return await self.post(url, json=json, headers={**(headers or {}), "method": method})

    async def get(self, url, params=None, headers=None, **k):
        return await self.post(url, json={"params": params}, headers=headers)


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


# ── the review's reproduction: the compute job under its second name ────

COMPUTE = {"endpoint": "https://akash.invalid", "api_key": "platform-compute-key"}


def _compute_server(tmp_path):
    from gateway.server import GatewayServer
    from test_route_sweep import SWEEP_CONFIG
    return GatewayServer({**SWEEP_CONFIG, "memory_dir": str(tmp_path / "m"),
                          "rexhepi": {"rate_limit_max_actions": 100_000},
                          "database": {"path": str(tmp_path / "s.db")},
                          "services": {"compute": COMPUTE},
                          "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": "k"}})


async def test_a_session_has_the_compute_provider_run_nothing_under_a_second_name(captured, tmp_path):
    """[control] The review's drive: a session over /bridge/v1/action, capability
    invoke and request_execution, the gate OBSERVE, the outgoing request
    captured. Laid over the merge of main into this branch, each answered 200
    and the platform's provider key asked the provider to run the session's
    image with the resources it named."""
    from aiohttp.test_utils import TestClient, TestServer

    from runtime.tools.dispatcher import ToolDispatcher
    server = _compute_server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        await _session(server)
        bridge = await client.post("/bridge/v1/action", headers=SESSION,
                                   json={"action": "compute_job_submit", "params": JOB,
                                         "session_id": "s1"})
        invoke = await client.post("/api/v1/capabilities/compute_job_submit/invoke",
                                   headers=SESSION, json={"params": JOB})
    out = await ToolDispatcher({"workspace": ".", "services": {"compute": COMPUTE}}).dispatch(
        "request_execution", {"action": "compute_job_submit", "params": JOB},
        agent_name="trinity", caller_identity=A, caller_kind="session")
    assert captured == [], f"HTTP {bridge.status}/{invoke.status}, chat {out.model_text[:80]}: sent {captured}"
    assert (bridge.status, invoke.status) == (403, 403)
    assert out.ok is False and "[DENIED]" in out.model_text, out.model_text


async def test_the_operator_still_has_the_provider_run_a_job(captured):
    """[guard] Neo's platform_action with the operator's key still reaches the
    provider under the second name, so the control above sees a request when
    there is one."""
    from runtime.tools.dispatcher import ToolDispatcher
    await ToolDispatcher({"workspace": ".", "services": {"compute": COMPUTE}}).dispatch(
        "platform_action", {"action": "compute_job_submit", "params": JOB},
        agent_name="neo", caller_identity="", caller_kind="operator")
    assert [c["url"] for c in captured] == ["https://akash.invalid/v1/deployments"], captured
    assert captured[0]["headers"]["Authorization"] == "Bearer platform-compute-key"
    assert captured[0]["json"]["image"] == JOB["image"]


# ── the review's reproduction: the platform's RedStone key, a written path ──

REDSTONE = {"redstone_endpoint": "https://redstone-gw.invalid",
            "redstone_api_key": "platform-redstone-key"}
PACKAGE = {"data_feed": "ETH", "data_service_id": "../../v1/anything-the-request-writes?all=1#"}


def _redstone_server(tmp_path):
    from gateway.server import GatewayServer
    from test_route_sweep import SWEEP_CONFIG
    return GatewayServer({**SWEEP_CONFIG, "memory_dir": str(tmp_path / "m"),
                          "rexhepi": {"rate_limit_max_actions": 100_000},
                          "database": {"path": str(tmp_path / "s.db")},
                          "services": {"oracles_plus": REDSTONE},
                          "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": "k"}})


async def test_a_session_has_the_platform_s_redstone_key_read_nothing(captured, tmp_path):
    """[control] The review's drive: a session over /bridge/v1/action and
    request_execution, the gate OBSERVE, the outgoing request captured. At the
    merge of main into this branch ("Merge main into fix/oldq-census: durable
    execution, dark by default, as schema migration 11") the bridge answered
    200 and the platform's RedStone key went out, from both doors, in a GET at
    the path the request wrote."""
    from aiohttp.test_utils import TestClient, TestServer

    from runtime.tools.dispatcher import ToolDispatcher
    server = _redstone_server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        await _session(server)
        bridge = await client.post("/bridge/v1/action", headers=SESSION,
                                   json={"action": "redstone_request", "params": PACKAGE,
                                         "session_id": "s1"})
    out = await ToolDispatcher({"workspace": ".", "services": {"oracles_plus": REDSTONE}}).dispatch(
        "request_execution", {"action": "redstone_request", "params": PACKAGE},
        agent_name="trinity", caller_identity=A, caller_kind="session")
    assert captured == [], f"HTTP {bridge.status}, chat {out.model_text[:80]}: sent {captured}"
    assert bridge.status == 403 and out.ok is False and "[DENIED]" in out.model_text


async def test_the_operator_still_reads_redstone_with_the_platform_s_key(captured):
    """[guard] Neo's platform_action with the operator's key still reaches the
    RedStone gateway with the platform's key, so the control above sees a
    request when there is one."""
    from runtime.tools.dispatcher import ToolDispatcher
    await ToolDispatcher({"workspace": ".", "services": {"oracles_plus": REDSTONE}}).dispatch(
        "platform_action", {"action": "redstone_request", "params": PACKAGE},
        agent_name="neo", caller_identity="", caller_kind="operator")
    assert [c["url"] for c in captured] == [
        "https://redstone-gw.invalid/data-packages/latest/" + PACKAGE["data_service_id"]], captured
    assert captured[0]["headers"] == {"X-Api-Key": "platform-redstone-key"}


# ── a contract the request names ────────────────────────────────────────

async def test_a_session_has_the_platform_call_no_contract_it_names(dispatched, tmp_path):
    """[control] breed_nft sends breed(parent_a, parent_b) from the platform's
    wallet to the breeding contract the request names. Laid over the merge of
    main into this branch, a session's /bridge/v1/action and both chat tools
    dispatched it."""
    from aiohttp.test_utils import TestClient, TestServer

    from runtime.tools.dispatcher import ToolDispatcher
    params = {"parent_a": 1, "parent_b": 2, "breed_contract": B}
    server = signing._server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        await _session(server)
        bridge = await client.post("/bridge/v1/action", headers=SESSION,
                                   json={"action": "breed_nft", "params": params, "session_id": "s1"})
    chat = {}
    for tool in ("request_execution", "platform_action"):
        out = await ToolDispatcher({"workspace": "."}).dispatch(
            tool, {"action": "breed_nft", "params": params},
            agent_name="trinity", caller_identity=A, caller_kind="session")
        chat[tool] = "[DENIED]" in out.model_text
    assert dispatched == [], f"bridge {bridge.status}, chat denied {chat}: ran {dispatched}"
    assert bridge.status == 403 and all(chat.values()), (bridge.status, chat)


# ── a transfer recorded from an address the request names ──────────────

TRANSFER_ROUTE = {"sender": B, "recipient": A, "amount": 1, "token": "USDC"}
TRANSFER = {"token": "USDC", "from_addr": B, "to_addr": A, "amount": 1}


async def test_a_session_records_no_stablecoin_transfer_from_an_address_it_names(dispatched, tmp_path):
    """[control] POST /api/v1/stablecoin/transfer takes its sender from the body,
    and transfer_stablecoin takes from_addr from the request: nothing held
    either to the session. Laid over the merge of main into this branch, the
    route answered a session 400 from its handler (it hands the service names
    it does not take), and /bridge/v1/action, capability invoke and
    request_execution dispatched the transfer for a session."""
    from aiohttp.test_utils import TestClient, TestServer

    from runtime.tools.dispatcher import ToolDispatcher
    server = signing._server(tmp_path)
    answered = {}
    async with TestClient(TestServer(server.create_app())) as client:
        await _session(server)
        resp = await client.post("/api/v1/stablecoin/transfer", headers=SESSION, json=TRANSFER_ROUTE)
        answered["route"] = resp.status
        resp = await client.post("/bridge/v1/action", headers=SESSION,
                                 json={"action": "transfer_stablecoin", "params": TRANSFER,
                                       "session_id": "s1"})
        answered["bridge"] = resp.status
        resp = await client.post("/api/v1/capabilities/transfer_stablecoin/invoke",
                                 headers=SESSION, json={"params": TRANSFER})
        answered["invoke"] = resp.status
    out = await ToolDispatcher({"workspace": "."}).dispatch(
        "request_execution", {"action": "transfer_stablecoin", "params": TRANSFER},
        agent_name="trinity", caller_identity=A, caller_kind="session")
    answered["request_execution"] = "denied" if "[DENIED]" in out.model_text else out.model_text
    assert dispatched == [], f"{answered}: ran {dispatched}"
    assert set(answered.values()) <= {403, "denied"}, answered


async def test_the_operator_still_reaches_the_stablecoin_transfer(dispatched, tmp_path):
    """[guard] The operator's key is still let through to the route's handler
    (not answered 401, 403, 404 or 405 at the door), and the dispatcher still
    runs transfer_stablecoin for it. What the handler then answers, and that
    the public texts say so, is
    tests/test_the_stablecoin_route_is_described_as_it_answers.py's to check,
    so a repair of the handler does not fail this guard."""
    from aiohttp.test_utils import TestClient, TestServer

    server = signing._server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        route = await client.post("/api/v1/stablecoin/transfer", headers=OPERATOR, json=TRANSFER_ROUTE)
        bridge = await client.post("/bridge/v1/action", headers=OPERATOR,
                                   json={"action": "transfer_stablecoin", "params": TRANSFER,
                                         "session_id": "s1"})
    assert route.status not in (401, 403, 404, 405) and bridge.status == 200, (
        route.status, bridge.status)
    assert dispatched == ["transfer_stablecoin"], dispatched


# ── a held parameter, whatever its type ─────────────────────────────────

HELD_VALUES = {
    "a list": ["price_feed"],
    "a dict": {"oracle_type": "price_feed"},
    "a number": 7,
    "null": None,
    "a very long string": "price_feed" * 100_000,
}


def _held_actions():
    """(action, capability id or None, field) for every action that resolves
    to a held pair."""
    from runtime.access_policy import HELD_FOR_A_SESSION
    from runtime.capabilities import catalog
    out = []
    for pair, (field, _allowed) in sorted(HELD_FOR_A_SESSION.items()):
        for action in _actions_for(pair):
            caps = [c["id"] for c in catalog.CAPABILITIES if c["action"] == action] or [None]
            out += [(action, cap, field) for cap in caps]
    assert out, "no action resolves to a held pair"
    return out


@pytest.mark.parametrize("kind", sorted(HELD_VALUES))
async def test_a_held_parameter_of_any_type_is_refused_not_raised(dispatched, tmp_path, kind):
    """[control] A session sends the held parameter as a list, a dict, a number,
    null or a very long string, at /bridge/v1/action, at capability invoke and
    through both chat tools. Laid over the merge of main into this branch, a
    list and a dict raised TypeError out of the refusal: HTTP 500 at both HTTP
    doors and an exception out of the tool dispatcher."""
    from aiohttp.test_utils import TestClient, TestServer

    from runtime.tools.dispatcher import ToolDispatcher
    value = HELD_VALUES[kind]
    answered = {}
    server = signing._server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        await _session(server)
        for action, cap, field in _held_actions():
            params = {field: value, "params": {"pair": "ETH/USD"}}
            resp = await client.post("/bridge/v1/action", headers=SESSION,
                                     json={"action": action, "params": params, "session_id": "s1"})
            answered[f"bridge {action}"] = resp.status
            if cap:
                resp = await client.post(f"/api/v1/capabilities/{cap}/invoke",
                                         headers=SESSION, json={"params": params})
                answered[f"invoke {cap}"] = resp.status
    for action, _cap, field in _held_actions():
        for tool in ("request_execution", "platform_action"):
            try:
                out = await ToolDispatcher({"workspace": "."}).dispatch(
                    tool, {"action": action, "params": {field: value, "params": {"pair": "ETH/USD"}}},
                    agent_name="trinity", caller_identity=A, caller_kind="session")
                answered[f"{tool} {action}"] = "denied" if "[DENIED]" in out.model_text else out.model_text
            except Exception as exc:  # noqa: BLE001 — the control records what escaped
                answered[f"{tool} {action}"] = f"raised {type(exc).__name__}"
    assert dispatched == [], dispatched
    assert set(answered.values()) <= {403, "denied"}, answered


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
    from runtime.access_policy import dispatch_pair
    refused = _refused_pairs()
    data = json.loads((ROOT / "extensions" / "registry.json").read_text(encoding="utf-8"))
    offered = [f"{c['id']}: {a}" for c in data["components"] for a in c.get("gateway_actions", [])
               if dispatch_pair(a) in refused]
    assert offered == [], offered
    for component in data["components"]:
        assert component["capability_count"] == len(component["gateway_actions"]), component["id"]
    assert data["total_capabilities"] == sum(c["capability_count"] for c in data["components"])


def test_no_route_a_session_reaches_runs_what_it_is_refused():
    """[guard] A dedicated /api/v1 route runs what its handler pins. None a
    session reaches runs a refused pair or one that hands the call on to what
    a session is refused or bound on, or reaches a request of the class; one
    that runs a held method, or a wrapper that holds what it wraps, pins a
    value the hold allows; and what a route's pair hands on to a held method
    is pinned or a configured custom request. Read from the routes the gateway builds, and followed through the
    services layer by the walk above."""
    from gateway.session_routes import USER_SESSION_ROUTES
    from runtime.access_policy import (
        BOUND_TO_THE_CALLER, HELD_FOR_A_SESSION, REFUSED_TO_A_SESSION)
    from scripts.generate_session_routes import live_route_pairs
    layer = _layer()
    derived = derive()
    held = layer.held({layer.node(*pair): spec for pair, spec in HELD_FOR_A_SESSION.items()},
                      derived.sites)
    refused = {layer.node(*pair): pair for pair in set(REFUSED_TO_A_SESSION) | set(BOUND_TO_THE_CALLER)}
    routes = live_route_pairs()
    bad = []
    for route in sorted(USER_SESSION_ROUTES):
        for pair, fixed in routes.get(route, {}).items():
            if pair in REFUSED_TO_A_SESSION or pair in BOUND_TO_THE_CALLER:
                bad.append(f"{route} runs {pair}")
            node = layer.node(*pair)
            if node is None:
                continue
            if node in held:
                field, allowed = held[node]
                pinned = fixed.get(field)
                if not (pinned and pinned[0] == "const" and pinned[1] in allowed):
                    bad.append(f"{route} runs {pair} with {fixed}")
                continue
            reached = sorted(refused[n] for n in layer.reach(node, derived.cut) & set(refused)
                             if refused[n] != pair)
            if reached:
                bad.append(f"{route} runs {pair}, which hands the call to {reached}")
            bad += [f"{route} runs {pair}: {c}" for c in _held_calls_outside_the_hold(layer, derived, node)]
            sends = sorted(q for _f, q in _class_reach(layer, derived, node) & set(derived.class_sends))
            if sends:
                bad.append(f"{route} runs {pair}, which reaches a request of the class: {sends}")
    assert bad == [], bad
    assert ("oracle_gateway", "request") in routes["/api/v1/oracle/price/{pair}"]
