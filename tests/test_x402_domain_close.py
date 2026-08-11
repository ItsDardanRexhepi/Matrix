"""NEW-55/56/57/58 — x402_payments domain close (domain 4).

Two proofs are load-bearing here and are called out by name:

  VOCABULARY-COMPLETE  — no reader can still be misled into thinking value
                         moved. Enum, return fields, docstrings and every
                         consumer of the old terminal status, all checked.
  STATUS-CONSISTENT    — the status a client POLLS agrees with the terminal
                         settlement vocabulary. Fixing one without the other
                         reintroduces the confusion the other removed.

WHAT WAS WRONG

  complete_payment  the terminal settlement step of Component 10 performed
                    ZERO settlement. Its whole action was
                    `payment["status"] = PaymentStatus.COMPLETED.value`,
                    under a docstring claiming "(on-chain settlement done)".
                    No web3 call, no payment API, no ledger — the service has
                    none.
  get_payment       returned `"status": "found"`, clobbering the real
                    lifecycle status on EVERY lookup of EVERY payment.
  create_payment    returned `"status": "created"`, clobbering "pending".
  six methods       create_stream / create_recurring / create_milestone_escrow
                    / split_payment / factor_invoice / run_payroll — all
                    fabrication-live, all moving nothing. split_payment never
                    even read the per-recipient amounts (only len()).
  five routes       dead or divergent; create_payment's route sent
                    payer/payee to a method taking agent_id/recipient/purpose,
                    so the HTTP payment-creation endpoint never worked.
"""

from __future__ import annotations

import inspect
import json
import re
import subprocess
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes
from runtime.blockchain.services.x402_payments.service import (
    PaymentStatus,
    X402PaymentService,
)

REMOVED_METHODS = [
    "create_stream", "create_recurring", "create_milestone_escrow",
    "split_payment", "factor_invoice", "run_payroll",
]
REMOVED_ACTIONS = [
    "stream_payment", "recurring_create", "escrow_milestone",
    "payment_split", "invoice_factor", "payroll_run",
]
ROOT = Path(__file__).resolve().parents[1]


def _dispatch(raw: object) -> dict:
    """Parse ServiceDispatcher.execute's JSON-STRING envelope."""
    assert isinstance(raw, str), (
        f"dispatcher.execute returned {type(raw).__name__}, expected a JSON "
        "string — the envelope shape changed and these assertions no longer "
        "look at what they think they do."
    )
    env = json.loads(raw)
    assert isinstance(env, dict)
    return env


def _svc() -> X402PaymentService:
    return X402PaymentService({})


# ══ PROOF 1 — VOCABULARY-COMPLETE ═════════════════════════════════════════


def test_the_completed_status_no_longer_exists():
    assert not hasattr(PaymentStatus, "COMPLETED"), (
        "PaymentStatus.COMPLETED still exists — renaming the docstring while "
        "leaving the enum is the reworded-status dodge"
    )
    assert PaymentStatus.RECORDED_UNSETTLED.value == "recorded_unsettled"


def test_no_consumer_of_the_old_terminal_status_remains():
    """The consumer grep — the vocabulary is not changed until NO reader is left.

    Runs the search across the whole repo rather than the one service, because
    a consumer in another module is exactly the reader that would still be
    misled.
    """
    hits = subprocess.run(
        ["grep", "-rn", "--include=*.py", "PaymentStatus.COMPLETED",
         str(ROOT / "runtime"), str(ROOT / "gateway"), str(ROOT / "tests")],
        capture_output=True, text=True,
    ).stdout.strip()

    # This file names the old symbol on purpose — in its module docstring, in
    # an assertion message, and in the grep pattern itself. Prose ABOUT the
    # removed lie is not the lie; excluding only this file keeps the check
    # honest for every other reader, including other tests.
    real = [
        ln for ln in hits.splitlines()
        if ln and Path(ln.split(":", 1)[0]).name != Path(__file__).name
    ]

    assert not real, "readers of the old terminal status remain:\n" + "\n".join(real)


def test_no_settlement_claim_survives_in_the_service_source():
    """No UNQUALIFIED settlement claim anywhere — docstrings included.

    Getting this test right took two attempts and the second failure is worth
    recording, because it is the trap this whole audit keeps hitting.

    v1 scanned the raw source: it FAILED post-fix, because the new docstring
    QUOTES the old lie while explaining it was false.

    v2 stripped docstrings and comments first: it then PASSED against pre-fix
    HEAD — i.e. it could no longer see the defect at all, because the original
    lie ("(on-chain settlement done)") lived IN A DOCSTRING. A test that
    cannot fail on the thing it exists to catch is worthless, and stripping
    the very region the bug occupied is how it happened.

    v3 (this one) scans everything and discriminates by CONTEXT: the phrase is
    permitted only inside a window that also denies it. Prose about a removed
    lie is fine; an unqualified assertion is not.
    """
    from runtime.blockchain.services.x402_payments import service as mod

    src = Path(inspect.getsourcefile(mod)).read_text()
    lines = src.splitlines()

    DENIALS = [
        "was not", "used to", "never", "no value", "not settled",
        "unsettled", "moves no value", "former", "removed", "fiction",
        "did not", "no web3", "no ledger",
    ]
    CLAIMS = ["settlement done", "on-chain settlement", "settled on-chain"]

    offenders = []
    for i, line in enumerate(lines):
        low = line.lower()
        if not any(c in low for c in CLAIMS):
            continue
        window = " ".join(lines[max(0, i - 3): i + 6]).lower()
        if not any(d in window for d in DENIALS):
            offenders.append(f"line {i + 1}: {line.strip()}")

    assert not offenders, (
        "unqualified settlement claim(s) — a reader would believe value moved:\n  "
        + "\n  ".join(offenders)
    )


async def test_complete_payment_states_plainly_that_nothing_moved():
    svc = _svc()
    created = await svc.create_payment("agentA", "0xRecipient", 10.0, "USDC", "test")
    await svc.authorize_payment(created["payment_id"])

    result = await svc.complete_payment(created["payment_id"])

    assert result["status"] == "recorded_unsettled"
    assert result["settled"] is False
    assert result["value_moved"] is False
    assert "NOT SETTLED" in result["disclosure"]
    # And it must not smuggle the old vocabulary back in a neighbouring key.
    assert "completed_at" not in result
    assert result["recorded_at"] > 0


async def test_the_record_itself_carries_no_completed_field():
    """The stored record, not just the return value."""
    svc = _svc()
    created = await svc.create_payment("agentA", "0xRecipient", 10.0, "USDC", "t")
    record = svc._payments[created["payment_id"]]

    assert "completed_at" not in record
    assert "recorded_at" in record


# ══ PROOF 2 — STATUS-CONSISTENT (item 4 agrees with item 2) ═══════════════


async def test_a_polling_client_sees_the_real_state_at_every_lifecycle_point():
    """The load-bearing agreement test.

    Walks the full lifecycle and asserts that what `get_payment` reports is
    exactly the record's real status at each step — and that the terminal one
    is the honest unsettled vocabulary, not a re-clobbered overclaim. If item 4
    were fixed without item 2 (or vice versa) this fails.
    """
    svc = _svc()
    created = await svc.create_payment("agentA", "0xRecipient", 10.0, "USDC", "t")
    pid = created["payment_id"]

    # 1. after creation
    assert created["status"] == PaymentStatus.PENDING.value, (
        "create_payment still clobbers the real status"
    )
    assert created["created"] is True
    polled = await svc.get_payment(pid)
    assert polled["status"] == PaymentStatus.PENDING.value
    assert polled["found"] is True

    # 2. after authorization
    await svc.authorize_payment(pid)
    polled = await svc.get_payment(pid)
    assert polled["status"] == PaymentStatus.AUTHORIZED.value

    # 3. after the record is closed — the terminal state is the HONEST one
    await svc.complete_payment(pid)
    polled = await svc.get_payment(pid)
    assert polled["status"] == PaymentStatus.RECORDED_UNSETTLED.value, (
        "the polled terminal status disagrees with the settlement vocabulary — "
        "item 4 and item 2 have diverged, which is the coherent-looking lie"
    )

    # 4. no string anywhere in the polled payload overclaims
    blob = json.dumps(polled)
    for overclaim in ['"completed"', '"settled"', '"paid"', '"found"']:
        assert f'"status": {overclaim}' not in blob, (
            f"polled status overclaims with {overclaim}"
        )


async def test_get_payment_never_reports_the_same_status_for_every_payment():
    """The specific defect: one string for all payments in all states."""
    svc = _svc()
    a = await svc.create_payment("agentA", "0xR1", 1.0, "USDC", "t")
    b = await svc.create_payment("agentB", "0xR2", 2.0, "USDC", "t")
    await svc.authorize_payment(b["payment_id"])

    sa = (await svc.get_payment(a["payment_id"]))["status"]
    sb = (await svc.get_payment(b["payment_id"]))["status"]

    assert sa != sb, (
        "two payments in different states report the same status — the "
        "clobber is back"
    )
    assert sa == PaymentStatus.PENDING.value
    assert sb == PaymentStatus.AUTHORIZED.value


# ══ item 3 — the six fabrications, all surfaces ═══════════════════════════


@pytest.mark.parametrize("method", REMOVED_METHODS)
def test_the_fabricating_method_is_gone(method):
    assert not hasattr(X402PaymentService, method)


@pytest.mark.parametrize("action", REMOVED_ACTIONS)
def test_the_action_is_not_dispatchable(action):
    from runtime.blockchain.services.service_dispatcher import (
        ACTION_MAP,
        ACTION_TO_FEED_EVENT,
        _STATE_MODIFYING_ACTIONS,
    )

    assert action not in ACTION_MAP
    assert action not in _STATE_MODIFYING_ACTIONS
    assert action not in ACTION_TO_FEED_EVENT


@pytest.mark.parametrize("action", REMOVED_ACTIONS)
async def test_dispatching_a_removed_action_fails(action):
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    env = _dispatch(await ServiceDispatcher({}).execute(action=action, params={}))
    assert env["status"] == "error", f"{action} still works: {env!r}"
    assert "unknown action" in env["error"].lower()


@pytest.mark.parametrize("action", REMOVED_ACTIONS)
def test_the_action_is_not_advertised(action):
    from runtime.capabilities import catalog

    assert catalog.get_by_id(action) is None

    registry = json.loads((ROOT / "extensions" / "registry.json").read_text())
    components = registry["components"] if isinstance(registry, dict) else registry
    assert not [
        c["id"] for c in components if action in (c.get("gateway_actions") or [])
    ]


@pytest.mark.parametrize("action", REMOVED_ACTIONS)
def test_the_model_is_not_told_the_action_works(action):
    from runtime.chat.intent_actions import INTENT_ACTION_MAP

    guide = INTENT_ACTION_MAP[action]
    assert guide.get("unavailable") is True
    assert "action_name" not in guide
    assert "NOT AVAILABLE" in guide["description"]


# ══ item 5 — routes ═══════════════════════════════════════════════════════


@pytest.fixture
async def client():
    routes = ServiceRoutes(config={})
    app = web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as c:
        yield c


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/payments/stream/create",
        "/api/v1/payments/recurring/create",
        "/api/v1/payments/escrow/milestone",
        "/api/v1/payments/split",
        "/api/v1/payments/payroll",
    ],
)
async def test_the_dead_routes_are_unregistered(client, path):
    """Never-functional routes go with their methods.

    Each of these bound to a removed fabrication, and several were already
    permanently broken (escrow/milestone called a method that never existed).
    A route that has never worked is not a regression to remove.
    """
    resp = await client.post(path, json={})
    assert resp.status == 404, (
        f"{path} still registered (HTTP {resp.status}) — it points at a method "
        "that no longer exists"
    )


async def test_the_create_payment_route_now_reaches_its_method(client):
    """NEW-58: this route was permanently dead — payer/payee vs agent_id/recipient.

    Positive proof it now binds: a well-formed call must NOT come back as a
    parameter error, and must carry the real pending status rather than the
    old "created" clobber.
    """
    resp = await client.post(
        "/api/v1/payments/create",
        json={"payer": "agentA", "payee": "0xRecipient", "amount": 5.0,
              "token": "USDC", "purpose": "test"},
    )
    body = await resp.json()
    blob = json.dumps(body)

    assert "unexpected keyword" not in blob, f"route still diverges: {blob[:250]}"
    assert "Invalid parameters" not in blob, f"route still diverges: {blob[:250]}"

    data = body.get("data", body)
    assert data.get("status") == PaymentStatus.PENDING.value, (
        f"route reached the method but the status is wrong: {blob[:250]}"
    )
    assert data.get("agent_id") == "agentA"
