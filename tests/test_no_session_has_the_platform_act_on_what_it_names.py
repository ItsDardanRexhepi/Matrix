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
with it. The operator's key keeps every one over ``/bridge/v1/action`` and
Neo's ``platform_action``, and a dispatch with no HTTP caller keeps them; the
capability invoke route runs no capability the catalog marks unavailable,
whoever asks.

THE CENSUS. The tables are derived, not only written. Two walks of the source
say what the platform's wallet or a platform credential does on what a
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
    ``socket``, ``websockets``, ``websocket``).

The services layer is then read as one program (``Layer``): every top-level
class and function under ``runtime/blockchain/services/``, and what each
function reaches. A method reaches another method of its class through
``self`` or ``cls`` (a call, or a reference such as a dispatch table of bound
methods), one it inherits from a class of the layer, a function of its module
or one it imports from the layer, and a method of an object it calls one on,
where the walk can place that object's class. It places it from what builds
it (a constructor, ``ServiceRegistry.get`` with a constant service name, a
function or method that returns one), carried through a local name, a
``self`` attribute any method of the class writes, a property, an element of
a ``self`` dict, list or tuple, an ``await``, an ``and``/``or``, a
conditional, a parameter or return annotation, and the arguments every call
it places hands a parameter, to a fixed point. A call it cannot place is
recorded; one whose method has the name of a function that reaches a payee,
an asset, a contract or a send, and a method looked up by a name computed at
run time, fail the census where any dispatchable pair reaches them. A class
name defined twice, a base the walk does not read, an ACTION_MAP pair that
names no def the walk reads, a service class that binds an action's method
name any other way, and one that answers an attribute at run time
(``__getattr__``) fail it too.

A call into a held method (the oracle's ``request``) is followed, for a
session, unless every call on that edge hands the held parameter a constant
the hold allows, which is what a session may send the method directly; a
function that only hands its own parameter on as the held parameter holds
what it wraps (``request_safe``). Every method a dispatch can run, the
``service`` override included, is read. Each pair that reaches what either
walk finds must be refused to a session, handed on (``HANDS_THE_CALL_TO``,
which must equal what the walk finds; a hand-on to a pair every door refuses
on request is not one, for the reason runtime/access_policy.py gives), bound,
held, already refused (to
every caller, or to a session because its route is the operator's), or
listed here with the reason it is not the class; an entry in those tables
the walks do not find fails too, so neither side can drift.

WHAT THIS DOES NOT READ, stated. A payee, an asset or a contract the address
walk does not read (see its own docstring); an amount; an object handed in
from outside the services layer, and code outside it (a call on such an
object is recorded, and fails the census only by the name rule above); a
request sent by any shape not named above; code replaced at run time. A
dedicated ``/api/v1`` route a session reaches runs what its handler pins
(checked below against the routes the gateway builds, and followed through
the layer), not what a request names.

CONTROL. Of this file's 50 tests, 34 are marked [control] and 16 [guard].

Laid over the merge of main into this branch (the commit "Merge main into
fix/oldq-census: one spelling for a caller, schema migration 10, a fault that
binds under OBSERVE, and test prose that names a commit by subject"), 11
fail, each a control, each on what it drives or reads: the second name
(compute_job_submit dispatched at the bridge, at invoke and through
request_execution), the compute drive (both HTTP doors answered 200 and the
platform's provider key sent the session's image), the contract drive
(breed_nft dispatched at the bridge and through request_execution), the
stablecoin drive (the route answered 400 from its handler, the other three
doors dispatched), a held type sent as a list and as a dict (HTTP 500 at the
bridge, TypeError out of both chat tools), the door drive and the
request_execution drive read from the walks (the doors ran breed_nft and
compute_job_submit, request_execution ran breed_nft), the registry (it offered breed_nft, decentralized_store, ipfs_pin and
compute_job_submit), and the two table controls (two pairs open; the three
hand-ons the walk finds, which no table held). 23 controls pass there: the
census's own ten (the nine planted hand-on shapes and the compute job's
second name), which, run with the walk as it stood there, reach none of the
nine (one is not even dispatched, as the class defines no such method) and
do not find the second name; the ten of the change before, which pass there
as that change left them; and three of the five held values (a number, null
and a very long string were refused there already). The 16 guards pass
there and here. All 50 pass here.

The change before this one was measured the same way: this file as it left
it, 29 tests, laid over this branch's census-wording commit ("The signing and
attestation censuses name the shapes they read and claim no more, ...")
fails 16 and passes 13. Eight controls fail on what they drive (the two MPC
drives, the unavailable invoke, the four bound cases and the oracle's
custom type); six fail on the import of REFUSED_TO_A_SESSION, which that
commit lacks (the two table controls, the door drive, the two chat drives and
the registry); and two guards fail on the same import (the listed reads and
the route check).
"""

from __future__ import annotations

import ast
import asyncio
import json
import pathlib
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

    def __init__(self, trees: dict | None = None):
        from runtime.blockchain.services.registry import _SERVICE_MAP
        self.service_class = {svc: cls for svc, (_m, cls) in _SERVICE_MAP.items()}
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
        self.edges, self.unplaced = self._read_edges()

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

            own = self.methods(cls) if cls else {}
            for n in ast.walk(fn):
                if isinstance(n, ast.Attribute):
                    base = n.value
                    if isinstance(base, ast.Name) and base.id in ("self", "cls") and cls:
                        if n.attr in own:
                            out.setdefault(own[n.attr][0], []).append(site(n))
                        continue
                    placed = self.types(base, unit)
                    for c in placed:
                        found = self.methods(c).get(n.attr)
                        if found:
                            out.setdefault(found[0], []).append(site(n))
                    if placed or (isinstance(base, ast.Attribute) and base.attr == "functions"):
                        continue
                    if isinstance(base, ast.Name) and (base.id in clients or base.id in HTTP_MODULES):
                        continue
                    lost.append((n.lineno, n.attr, ast.unparse(n)[:120]))
                elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                    target = self.function(rel, n.id)
                    if target:
                        out.setdefault(target, []).append(site(n))
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

    def dispatchable(self) -> dict:
        """(service, method) -> function, for every pair a dispatch can run: an
        ACTION_MAP method name on any service that has it (a platform_action
        ``service`` override moves an action's method onto another service)."""
        from runtime.blockchain.services.service_dispatcher import ACTION_MAP
        names = {method for _service, method in ACTION_MAP.values()}
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


_LAYER: list = []


def _layer() -> Layer:
    if not _LAYER:
        _LAYER.append(Layer())
    return _LAYER[0]


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


class Derived(NamedTuple):
    onchain: set          # pairs that reach a platform-signed payee, asset or contract
    http: dict            # pairs that reach an HTTP send -> its verbs
    unreached_payees: set
    unreached_sends: set
    reached: dict         # pair -> every function it reaches for a session
    pairs: dict           # pair -> the function it runs
    sites: set            # every function the census looks for
    cut: set              # the edges into a held method a session may take


def derive() -> Derived:
    """What each dispatchable pair reaches, for a session: a call into a held
    method is followed unless every such call hands it a value the hold
    allows (that is what a session may send it directly)."""
    from runtime.access_policy import HELD_FOR_A_SESSION
    layer = _layer()
    pairs = layer.dispatchable()
    payee_sites = {(f, q) for (f, q, _fn, _path), kind in signing.SERVICE_ADDRESSES.items()
                   if kind in (signing.PAYEE, signing.ASSET, signing.CONTRACT)} | _PAYEE_BYTES
    sends = all_http_sends()
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
    return Derived(onchain, http, unreached_payees, unreached_sends, reached, pairs,
                   payee_sites | set(sends), cut)


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
    ("oracles_plus", "redstone_request"): (
        "a GET of a public data package from the configured RedStone gateway; the "
        "optional key meters it"),
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
    senders = _senders(layer, derived)
    assert {"submit_compute_job", "store_filecoin", "request"} <= senders, senders
    reached = set().union(*(layer.reach(node) for node in derived.pairs.values()))
    lost = sorted(f"{f}:{line} {q}: {text}" for (f, q) in reached
                  for line, name, text in layer.unplaced.get((f, q), [])
                  if name in senders or name == "getattr")
    assert lost == [], lost


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
}
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
    ``self``, ``cls`` and module names only, and reached none of them."""
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
    a session is refused or bound on; one that runs a held method, or a
    wrapper that holds what it wraps, pins a value the hold allows; and what a
    route's pair hands on to a held method is pinned or a configured custom
    request. Read from the routes the gateway builds, and followed through the
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
    assert bad == [], bad
    assert ("oracle_gateway", "request") in routes["/api/v1/oracle/price/{pair}"]
