"""A deliberate refusal must not be reported as the service malfunctioning.

THE DEFECT. `ServiceDispatcher.execute` special-cases exactly two exception
types and lets everything else fall to a generic handler:

    except TypeError            -> error_category "validation"       HTTP 400
    except NotImplementedError  -> error_category "not_implemented"  HTTP 501
    except Exception            -> error_category "service_error"    HTTP 502
                                   degraded=True, logger.exception (stack trace)

So a capability that is deliberately, permanently unavailable — refusing exactly
as this engagement's remediation intends — came back to callers as HTTP 502 Bad
Gateway and to operators as an ERROR-level stack trace, if it happened to raise
ValueError. "This will never work" and "the upstream is broken, retry" are
opposite operational meanings, and the honest one was one clause up the whole
time.

Three methods were affected across the codebase; two were fixed in the Cluster B
commit and the third (`GovernanceService.vote`'s weighted-voting refusal) here.
This file is the control that keeps it at zero.

THE MEASUREMENT THAT SCOPED IT, recorded because it reversed the expectation.
The question asked was whether this was a class rather than two instances. It is
NOT: of 245 `raise` statements in dispatcher-reachable service methods, only 3
are capability refusals. The other 242 are caller and business-rule errors —
"Proposal p1 not found", "Proposer address is required", "buyer cannot be the
seller", "insufficient balance". A 28-item random sample of the unclassified
remainder contained zero refusals, so the vocabulary below is not simply missing
them.

BUT THE MEASUREMENT FOUND A WIDER ONE NEXT DOOR, and it is deliberately NOT
fixed here or asserted on. Those same 242 caller errors ALSO fall to the generic
handler, so every one of them is currently reported as `service_error` /
degraded / HTTP 502 with a stack trace, when they are 400s and 404s. Verified:

    vote(proposal_id="nope")  -> "Proposal nope not found"        -> 502
    create_proposal(proposer="") -> "Proposer address is required" -> 502

A 502 is what SDKs, retry layers and load balancers treat as a transient
upstream failure, so a permanently-invalid request is retried. That is a
platform-wide change to the error contract of every action — a separate,
scoped decision, not a side effect of this fix. It is recorded on the
open-findings register rather than pinned by a failing test here, because a test
asserting the wrong behaviour is a test that must be deleted to fix it.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

from runtime.blockchain.services.service_dispatcher import ACTION_MAP, ServiceDispatcher

SERVICES = pathlib.Path(__file__).resolve().parent.parent / "runtime/blockchain/services"

#: Vocabulary of a CAPABILITY refusal — the feature does not exist. Distinct
#: from a caller error, where the feature exists and the request was bad.
REFUSAL_VOCABULARY = (
    "unavailable",
    "not implemented",
    "not available",
    "not built",
    "not supported",
    "no balance source",
    "does not exist in this platform",
)

#: The only exception type the dispatcher maps to an honest "not_implemented".
CORRECT_REFUSAL_EXCEPTION = "NotImplementedError"


def _dispatcher_reachable_methods() -> set[str]:
    return {method for _service, method in ACTION_MAP.values()}


def _raise_message(node: ast.Raise) -> str:
    if not isinstance(node.exc, ast.Call):
        return ""
    parts = []
    for arg in node.exc.args:
        try:
            parts.append(str(ast.literal_eval(arg)))
        except Exception:
            parts.append(ast.unparse(arg))
    return " ".join(parts).lower()


def find_misclassified_refusals() -> list[str]:
    """Capability refusals raising anything the dispatcher calls a malfunction."""
    reachable = _dispatcher_reachable_methods()
    bad: list[str] = []

    for path in sorted(SERVICES.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        rel = str(path.relative_to(SERVICES))
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            for fn in cls.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if fn.name not in reachable:
                    continue
                for node in ast.walk(fn):
                    if not isinstance(node, ast.Raise) or node.exc is None:
                        continue
                    message = _raise_message(node)
                    if not any(word in message for word in REFUSAL_VOCABULARY):
                        continue
                    exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
                    name = exc.id if isinstance(exc, ast.Name) else ast.unparse(exc)
                    if name != CORRECT_REFUSAL_EXCEPTION:
                        bad.append(f"{rel}::{cls.name}.{fn.name} raises {name}")
    return bad


def test_no_capability_refusal_is_reported_as_a_service_malfunction():
    """THE CONTROL. Ratchet at zero — it may never rise.

    A refusal raising the wrong type tells the caller "the upstream broke, retry"
    about a capability that will never exist, and pages an operator with a stack
    trace for correct behaviour.
    """
    misclassified = find_misclassified_refusals()

    assert not misclassified, (
        "capability refusal(s) raising an exception the dispatcher reports as "
        f"service_error / HTTP 502: {misclassified}. Raise "
        f"{CORRECT_REFUSAL_EXCEPTION} instead — it maps to not_implemented / 501."
    )


def test_the_control_can_actually_see_a_misclassified_refusal():
    """PROVEN IN BOTH DIRECTIONS. A control whose only evidence is that it
    returns zero is indistinguishable from one that cannot see anything."""
    reachable = _dispatcher_reachable_methods()
    assert reachable, "ACTION_MAP produced no methods — the scan sees nothing"

    def classify(src: str) -> bool:
        fn = ast.parse(src.strip()).body[0]
        for node in ast.walk(fn):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            if not any(w in _raise_message(node) for w in REFUSAL_VOCABULARY):
                continue
            exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            name = exc.id if isinstance(exc, ast.Name) else ast.unparse(exc)
            return name != CORRECT_REFUSAL_EXCEPTION
        return False

    assert classify('''
async def f(self):
    raise ValueError("Weighted voting is unavailable: no balance source wired.")
'''), "the control cannot see the defect it exists for"

    assert not classify('''
async def f(self):
    raise NotImplementedError("Weighted voting is unavailable: no balance source.")
'''), "the control flags the CORRECT form"

    # A caller error is not this control's business — it is a bad request, not a
    # missing capability. Flagging it here would produce pressure to convert
    # 400s into 501s, which is a different lie.
    assert not classify('''
async def f(self, proposal_id):
    raise ValueError(f"Proposal {proposal_id} not found")
'''), "the control has drifted onto caller errors"


# ── End to end: what the caller actually receives ────────────────────────


async def _dispatch(action: str, params: dict, dispatcher=None) -> dict:
    """NOTE: a fresh ServiceDispatcher holds fresh, empty service state. Two
    calls that must share state (create a proposal, then vote on it) MUST pass
    the same instance — otherwise the second call fails with "not found", which
    is a CALLER error and comes back service_error, exactly imitating the defect
    under test. That false negative cost a debugging cycle; it is written down
    rather than left as a trap."""
    d = dispatcher or ServiceDispatcher({})
    return json.loads(await d.execute(action=action, params=params))


@pytest.mark.parametrize(
    "action,params",
    [
        ("multisig_approve", {"multisig_id": "m1", "signer": "0xa"}),
        ("snapshot_vote", {"proposal_id": "p1", "voter": "0xa", "choice": "yes"}),
    ],
)
async def test_each_refusal_reaches_the_caller_as_not_implemented(action, params):
    envelope = await _dispatch(action, params)

    assert envelope["status"] == "error"
    assert envelope["error_category"] == "not_implemented", (
        f"{action} is reported as {envelope['error_category']!r}; a deliberate "
        "refusal must not read as a malfunction"
    )


async def test_the_weighted_vote_refusal_reaches_the_caller_as_not_implemented():
    """THE ONE FIXED HERE. It needs a live proposal first, so it cannot share
    the parametrised case above."""
    dispatcher = ServiceDispatcher({})
    created = await _dispatch("create_proposal", {
        "proposer": "0xp", "title": "T", "description": "d",
        "voting_model": "token_weighted", "options": ["yes", "no"],
    }, dispatcher)
    proposal_id = created["result"]["proposal_id"]

    envelope = await _dispatch("vote", {
        "proposal_id": proposal_id, "voter": "0xa", "choice": "no", "weight": 999_999.0,
    }, dispatcher)

    assert "not found" not in envelope.get("error", ""), (
        "the proposal did not survive to the vote call — this test would then "
        "pass or fail on a CALLER error, not on the refusal it exists for"
    )

    assert envelope["status"] == "error"
    assert envelope["error_category"] == "not_implemented"
    assert "balance source" in envelope["error"], (
        "the lifting condition was lost in the envelope — a refusal that does "
        "not say what would restore the capability is a dead end"
    )


async def test_the_refusal_still_refuses_and_records_nothing():
    """SCOPE PIN. Changing the exception TYPE must not change the BEHAVIOUR:
    the vote is still refused and no ballot is stored."""
    from runtime.blockchain.services.governance.service import GovernanceService

    svc = GovernanceService({"governance": {"total_eligible_voters": 10}})
    proposal = await svc.create_proposal(
        "0xp", "T", "d", "token_weighted", ["yes", "no"]
    )
    proposal_id = proposal["proposal_id"]
    votes_before = svc._proposals[proposal_id]["vote_count"]

    with pytest.raises(NotImplementedError):
        await svc.vote(proposal_id, "0xA", "no", weight=999_999.0)

    assert svc._proposals[proposal_id]["vote_count"] == votes_before


# ── THE TWO SURFACES MUST AGREE ──────────────────────────────────────────
#
# This is the assertion that makes the exception-type change a net improvement
# rather than a traded defect. The dispatcher and the HTTP gateway maintain
# SEPARATE exception ladders:
#
#     dispatcher   TypeError -> validation/400 | NotImplementedError -> 501
#                  | everything else -> service_error/502
#     gateway      KeyError -> 404 | TypeError -> 400 | ValueError -> 400
#                  | NotImplementedError -> 501 | everything else -> 500
#
# They were reconciled only at the NotImplementedError rung, and only because
# both were changed together. Converting the governance refusals took the
# dispatcher 502 -> 501 and simultaneously took POST /api/v1/governance/
# snapshot/vote from 400 -> 500, because the gateway had no such clause. Fixing
# one surface alone would have left ValueError->400 and NotImplementedError->500
# classifying the SAME refusal oppositely — worse than the original state,
# because the inconsistency would then be deliberate.


async def test_a_refusal_is_501_on_the_gateway_not_500():
    """The HTTP half. Without the `except NotImplementedError` clause in
    ServiceRoutes._call this is a 500 with an ERROR-level stack trace."""
    from aiohttp import web

    from gateway.service_routes import ServiceRoutes

    with pytest.raises(web.HTTPNotImplemented) as exc:
        await ServiceRoutes(config={})._call(
            "governance", "snapshot_vote",
            proposal_id="p1", voter="0xa", choice="yes",
        )

    body = json.loads(exc.value.text)
    assert body["error_category"] == "not_implemented"
    assert "hub" in body["error"].lower(), "the lifting condition was lost"


async def test_both_surfaces_classify_the_same_refusal_the_same_way():
    """THE PAIRING ASSERTION. One refusal, two transports, one meaning.

    A caller must not learn "not implemented" from the dispatcher and "the
    server broke" from HTTP for the identical condition.
    """
    from aiohttp import web

    from gateway.service_routes import ServiceRoutes

    envelope = await _dispatch("snapshot_vote", {
        "proposal_id": "p1", "voter": "0xa", "choice": "yes",
    })

    with pytest.raises(web.HTTPNotImplemented) as exc:
        await ServiceRoutes(config={})._call(
            "governance", "snapshot_vote",
            proposal_id="p1", voter="0xa", choice="yes",
        )
    http_body = json.loads(exc.value.text)

    assert envelope["error_category"] == http_body["error_category"] == "not_implemented", (
        f"the surfaces disagree: dispatcher={envelope['error_category']!r} "
        f"gateway={http_body['error_category']!r} — the same refusal is being "
        "reported two different ways"
    )
    assert exc.value.status == 501


async def test_the_gateway_still_calls_a_bad_value_a_client_error():
    """CONTROL IN THE OTHER DIRECTION. The new clause must not swallow
    ValueError — a bad parameter value is still an honest 400, not a 501.
    Widening the refusal rung to catch client errors would convert real 400s
    into "not implemented", which is the mirror-image lie."""
    from aiohttp import web

    from gateway.service_routes import ServiceRoutes

    with pytest.raises(web.HTTPBadRequest):
        await ServiceRoutes(config={})._call(
            "governance", "vote",
            proposal_id="does-not-exist", voter="0xa", choice="yes",
        )

