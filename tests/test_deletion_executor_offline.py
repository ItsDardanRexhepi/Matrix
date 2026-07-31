"""NEW-38 — data deletion is OFFLINE, and no path reports success.

WHAT WAS WRONG
--------------
`DeletionExecutor.execute_deletion` walked a hardcoded list of nine data
category NAMES, hashed each name with the request id and a timestamp, and
appended `{"category": ..., "status": "deleted", "deletion_hash": ...}`. It
opened no database, no object store, no cache, and no chain. Its `try` block
contained only a hash computation, so `failed_items` could never populate and
`success = len(failed_items) == 0` was unconditionally True.

`verify_deletion` then read back the dict that fake write had just populated,
found every item marked "deleted", concluded `all_verified=True`, and minted
`f"attest_{uuid4().hex[:16]}"` labelled "Component 8 (EAS Attestation)".

Reproduced end-to-end against an address holding no data anywhere on the
platform: request_deletion -> pending, elapse the cooldown (the only gate),
execute_deletion -> success=True, total_deleted=9, total_failed=0,
on_chain_status='marked_deleted', request status -> 'completed'.

WHAT THIS FILE PINS
-------------------
The user's requirement, verbatim: "a test asserting no path obtains
`success: true` from the deletion executor."

`test_no_public_entry_point_can_report_success` is the load-bearing one. It
does NOT check the callers I happened to find — two of the six frames this
engagement has already broken were caller-enumeration frames (a route that
was registered under a prefix I did not expect; an action reachable through
four dispatch call sites when no HTTP route pointed at it). Instead it
enumerates the executor's own public async surface by reflection and drives
every method, so a method added later is covered the day it is added — and an
entry point whose parameters it cannot bind is a FAILURE, not a skip.

The remaining tests cover the surfaces above the executor: the service, the
action map, the capability catalog, the intent table, and the HTTP route.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes
from runtime.blockchain.services.privacy.deletion_executor import DeletionExecutor
from runtime.blockchain.services.privacy.service import PrivacyService

_EXECUTOR_SRC = Path(
    "runtime/blockchain/services/privacy/deletion_executor.py"
)

# Keys a caller might read as "the work was done". Checked as a set rather
# than one field: the old payload said success=True AND total_deleted=9 AND
# on_chain_status="marked_deleted", and a partial fix that flipped only
# `success` would still hand a caller two other reasons to believe it.
_SUCCESS_CLAIM_KEYS = ("success", "all_verified", "attestation_uid")


def _claims_success(payload: object) -> list[str]:
    """Every way *payload* claims deletion happened. Empty list == honest.

    Callers MUST pass a dict. Returning [] for a non-dict is what made the
    first draft of the two dispatcher tests below pass for free:
    `ServiceDispatcher.execute` returns a JSON *string*, so `_claims_success`
    took the non-dict branch and found nothing to complain about — a vacuous
    pass inside the file whose whole subject is vacuous success. It now
    raises instead, so the mistake cannot recur silently.
    """
    if not isinstance(payload, dict):
        raise TypeError(
            f"_claims_success needs a dict, got {type(payload).__name__} — "
            "parse the envelope first; a non-dict would pass vacuously"
        )

    claims = []
    for key in _SUCCESS_CLAIM_KEYS:
        if payload.get(key):
            claims.append(f"{key}={payload[key]!r}")
    if payload.get("status") in ("ok", "completed", "deleted", "verified"):
        claims.append(f"status={payload['status']!r}")
    if payload.get("total_deleted"):
        claims.append(f"total_deleted={payload['total_deleted']!r}")
    if payload.get("deleted_items"):
        claims.append(f"deleted_items={len(payload['deleted_items'])} items")
    if payload.get("on_chain_status") not in (None, "none"):
        claims.append(f"on_chain_status={payload.get('on_chain_status')!r}")
    return claims


# ── the load-bearing assertion ─────────────────────────────────────────────


async def test_no_public_entry_point_can_report_success():
    """No public async method of DeletionExecutor reports a deletion.

    Reflection over the class, not a hand-list of callers. A new method that
    fabricates a deletion fails this test without anyone remembering to add
    it here.
    """
    executor = DeletionExecutor({})

    entry_points = [
        (name, member)
        for name, member in inspect.getmembers(
            executor, predicate=inspect.iscoroutinefunction
        )
        if not name.startswith("_")
    ]

    # Guard against the test silently covering nothing — if the class is
    # renamed or its methods become sync, an empty list would "pass".
    assert len(entry_points) >= 3, (
        f"expected at least the 3 known entry points, found {entry_points!r} — "
        "the reflection is no longer finding the executor's surface"
    )

    offenders = []
    for name, method in entry_points:
        sig = inspect.signature(method)
        kwargs = {}
        unbindable = []
        for pname, param in sig.parameters.items():
            if pname == "request_id":
                kwargs[pname] = "del_probe"
            elif param.default is not inspect.Parameter.empty:
                continue
            else:
                unbindable.append(pname)

        # An entry point this test cannot drive is a hole in the guarantee,
        # so it fails closed rather than skipping.
        assert not unbindable, (
            f"{name} requires {unbindable} which this test cannot supply — "
            "extend the test; do not leave the entry point unchecked"
        )

        result = await method(**kwargs)
        claims = _claims_success(result)
        if claims:
            offenders.append(f"{name} -> {', '.join(claims)}")

    assert not offenders, (
        "the deletion executor reports work it did not do:\n  "
        + "\n  ".join(offenders)
    )


async def test_execute_deletion_returns_a_failure_shaped_payload():
    """Positive proof of the refusal, not just absence of success.

    `_claims_success` returning empty could also mean the method returned
    None, or {}, or raised something swallowed upstream. This asserts the
    payload actively says not-implemented, so a caller has something to act
    on.
    """
    result = await DeletionExecutor({}).execute_deletion("del_probe")

    assert result["status"] == "error"
    assert result["error_category"] == "not_implemented"
    assert result["success"] is False
    assert result["total_deleted"] == 0
    assert result["deleted_items"] == []
    assert "not available" in result["message"].lower()


async def test_verify_deletion_mints_no_attestation():
    """The second half of the pair: no attestation for a deletion that did
    not happen."""
    result = await DeletionExecutor({}).verify_deletion("del_probe")

    assert result["attestation_uid"] is None
    assert result.get("all_verified") is not True
    assert result["status"] == "error"


async def test_verify_deletion_refuses_even_with_a_prepopulated_execution():
    """The refusal is unconditional, not a consequence of an empty dict.

    If `verify_deletion` refused only because `_executions` was empty, then
    anything that populated `_executions` — a future caller, a cache warm-up,
    a test fixture — would quietly restart the attestation minting. This
    hand-populates the dict in exactly the shape the old fake produced and
    asserts the answer does not change.
    """
    executor = DeletionExecutor({})
    executor._executions["del_probe"] = {
        "execution_id": "exec_forged",
        "request_id": "del_probe",
        "success": True,
        "deleted_items": [
            {"category": "profile_data", "status": "deleted", "deletion_hash": "ab" * 32}
        ],
        "failed_items": [],
    }

    result = await executor.verify_deletion("del_probe")

    assert result["attestation_uid"] is None, (
        "a forged execution record was enough to obtain an attestation"
    )
    assert not _claims_success(result)


# ── the fabrication is gone from the source, not just unreachable ──────────


def test_the_nine_hardcoded_categories_are_gone():
    """The fabricated payload's ingredients are absent from the module.

    Unreachable-but-present code is the dead-twin shape this audit has hit
    repeatedly: someone wires it back up because it looks finished. The
    category list, the per-category hash, and the "marked_deleted" claim are
    checked as CODE, so the long docstring quoting the old behaviour does not
    satisfy them.
    """
    src = _EXECUTOR_SRC.read_text()
    # Strip docstrings and comments — the module deliberately describes what
    # it used to do, and that prose must not count as an implementation.
    code_only = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    code_only = re.sub(r'""".*?"""', "", code_only, flags=re.DOTALL)

    for banned in ("hashlib", "marked_deleted", "attest_", "uuid"):
        assert banned not in code_only, (
            f"{banned!r} is still live code in {_EXECUTOR_SRC.name} — "
            "the fabrication's ingredients are back"
        )

    # The nine category names were the fabricated inventory.
    for category in ("profile_data", "message_history", "transaction_records"):
        assert category not in code_only, (
            f"the hardcoded category {category!r} is still live code"
        )


# ── the service above it ───────────────────────────────────────────────────


async def test_request_deletion_queues_nothing():
    """It answers, and the answer is not a pending request id."""
    svc = PrivacyService({})

    result = await svc.request_deletion("0xVICTIM", ["all"])

    assert result["status"] == "error"
    assert result["error_category"] == "not_implemented"
    assert result["request_id"] is None
    assert result["queued"] is False
    assert result["status"] != "pending"
    # The queue that nothing ever drained stays empty.
    assert svc._deletion_requests == {}, (
        "a request was queued — the user will believe erasure is in progress"
    )


async def test_execute_pending_deletion_never_reaches_the_executor():
    """Positive proof the executor is not called, not just that the result
    looks wrong.

    The executor is replaced with a probe that records the call. Asserting on
    the returned payload alone would pass even if the real executor ran and
    its output were discarded — and "did the work happen" is the whole
    question here.
    """
    svc = PrivacyService({})
    calls = []

    class _Probe:
        async def execute_deletion(self, request_id):
            calls.append(("execute_deletion", request_id))
            return {"success": True, "total_deleted": 9}

        async def verify_deletion(self, request_id):
            calls.append(("verify_deletion", request_id))
            return {"attestation_uid": "attest_forged"}

    svc.executor = _Probe()

    result = await svc.execute_pending_deletion("del_probe")

    assert calls == [], f"the executor was invoked: {calls!r}"
    assert result["success"] is False
    assert result["executed"] is False
    assert result["attestation_uid"] is None
    assert result["error_category"] == "not_implemented"


async def test_the_cooldown_path_no_longer_leads_anywhere():
    """The original reproduction, replayed. It must now dead-end.

    Previously: request_deletion -> pending, set cooldown_until into the past,
    execute_pending_deletion -> completed + attestation. The cooldown was the
    only gate. There is now nothing to elapse.
    """
    svc = PrivacyService({})

    requested = await svc.request_deletion("0xVICTIM", ["all"])
    assert requested["request_id"] is None

    # Nothing to age past, because nothing was queued.
    assert svc._deletion_requests == {}

    executed = await svc.execute_pending_deletion("del_anything")
    assert not _claims_success(executed)


async def test_privacy_commitment_no_longer_claims_on_chain_irrevocability():
    """The adjacent surface stops promising what the platform cannot do."""
    svc = PrivacyService({})

    commitment = await svc.get_privacy_commitment("0xVICTIM")

    text = commitment["commitment"].lower()
    assert "irrevocab" not in text
    assert "on-chain" not in text
    assert "cannot be revoked" not in text
    assert commitment["deletion_available"] is False
    assert commitment["recorded_on_chain"] is False


# ── the action / tool / catalog surfaces ───────────────────────────────────


def test_execute_deletion_is_not_dispatchable():
    """Removed from ACTION_MAP, so all four dispatch call sites lose it.

    gateway/bridge.py (the chat tool surface), capabilities/registry.invoke,
    agents/handoff, and tools/dispatcher all resolve through ACTION_MAP. No
    HTTP route ever pointed at this action, which is exactly why it read as
    inert — the tool surface was the live one.
    """
    from runtime.blockchain.services.service_dispatcher import (
        ACTION_MAP,
        _STATE_MODIFYING_ACTIONS,
    )

    assert "execute_deletion" not in ACTION_MAP
    assert "execute_deletion" not in _STATE_MODIFYING_ACTIONS

    # request_deletion stays reachable BY DESIGN — it has to be, to give the
    # honest answer — and must still point at the refusing method.
    assert ACTION_MAP["request_deletion"] == ("privacy", "request_deletion")


def _dispatch_envelope(raw: object) -> dict:
    """Parse what `ServiceDispatcher.execute` actually returns.

    It returns a JSON STRING, not a dict — established by dumping it rather
    than reading the signature. Anything else is a shape change that must
    fail the test rather than be quietly tolerated.
    """
    assert isinstance(raw, str), (
        f"dispatcher.execute returned {type(raw).__name__}, expected a JSON "
        "string — the envelope shape changed and these assertions no longer "
        "look at what they think they do"
    )
    envelope = json.loads(raw)
    assert isinstance(envelope, dict)
    return envelope


async def test_dispatching_execute_deletion_does_not_succeed():
    """Driving the dispatcher, not reading its table.

    Membership in ACTION_MAP is a claim about a data structure. This calls
    `execute()` the way the tool surface does (gateway/bridge.py:801) and
    asserts on the parsed outcome.
    """
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    envelope = _dispatch_envelope(
        await ServiceDispatcher({}).execute(
            action="execute_deletion", params={"confirmation": True}
        )
    )

    assert envelope["status"] == "error", f"execute_deletion still works: {envelope!r}"
    assert "unknown action" in envelope["error"].lower()
    assert not _claims_success(envelope)


async def test_dispatching_request_deletion_returns_the_honest_answer():
    """The kept action answers, and the answer is the refusal.

    Note the outer envelope says status="ok" while the inner service result
    says status="error". That inversion is the known dispatcher-level mirror
    of NEW-29 (logged, frozen by ruling) — it is not what this test is about,
    so the assertion goes to the inner payload the caller ultimately reads.
    """
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    envelope = _dispatch_envelope(
        await ServiceDispatcher({}).execute(
            action="request_deletion",
            params={"user": "0xVICTIM", "data_types": ["all"]},
        )
    )

    inner = envelope["result"]
    assert isinstance(inner, dict), f"no inner result to check: {envelope!r}"
    assert not _claims_success(inner)
    assert inner["status"] == "error"
    assert inner["request_id"] is None
    assert inner["queued"] is False
    assert "not available" in inner["message"].lower()


def test_the_model_is_not_told_deletion_works():
    """Both intent entries follow the NEW-12 idiom: recognised, not offered."""
    from runtime.chat.intent_actions import INTENT_ACTION_MAP

    for action in ("request_deletion", "execute_deletion"):
        guide = INTENT_ACTION_MAP[action]
        assert guide.get("unavailable") is True, f"{action} still offered"
        assert "action_name" not in guide, (
            f"{action} still has an action_name — the model can dispatch it"
        )
        assert "NOT AVAILABLE" in guide["description"]
        # Keywords stay so the request is still RECOGNISED (NEW-12): deleting
        # the entry would make "delete my data" match nothing at all.
        assert guide["keywords"], f"{action} lost its keywords"


def test_the_capability_catalog_does_not_advertise_deletion():
    from runtime.capabilities import catalog

    assert catalog.get_by_id("execute_deletion") is None

    request_cap = catalog.get_by_id("request_deletion")
    assert request_cap is not None
    assert request_cap["available"] is False


# ── the HTTP surface ───────────────────────────────────────────────────────


@pytest.fixture
async def client():
    routes = ServiceRoutes(config={})
    app = web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as c:
        yield c


async def test_privacy_delete_route_answers_501(client):
    """The route is kept and tells the truth, rather than 404-ing.

    501 is the code /api/v1/contracts/deploy already returns for a feature
    that is not built. 503 would imply "retry later"; there is nothing to
    retry.
    """
    resp = await client.post(
        "/api/v1/privacy/delete",
        json={"user": "0xVICTIM", "data_types": ["all"]},
    )

    assert resp.status == 501, f"expected 501, got {resp.status}"
    body = await resp.json()
    assert body["status"] == "error"
    assert not _claims_success(body.get("data", {}))
    assert "not available" in str(body).lower()


async def test_privacy_delete_route_is_honest_even_with_an_empty_body(client):
    """The 501 does not depend on the caller filling in the form correctly.

    The handler used to `_require("user", "data_types")` and answer 400 —
    a claim about the request — when the truth is a fact about the platform.
    """
    resp = await client.post("/api/v1/privacy/delete", json={})

    assert resp.status == 501, f"expected 501, got {resp.status}"
