"""POST /bridge/v1/action answers a failure with the status of whoever caused it.

The route caught ``TypeError`` around ``dispatcher.execute`` and answered 422
"Invalid parameters: <the raw Python binding message>", and caught ``KeyError``
and answered 404 "Unknown action". Neither exception is a statement about the
request: a TypeError raised inside the dispatcher or a service is an internal
defect (NEW-9's signature drift was exactly that shape), and a KeyError inside
a service is not an unknown action. The caller was blamed and the internal
signature was quoted back to it. The error contract (gateway/error_contract.py)
already says what reaching this far means: ``internal_error``, redacted, a ref.

Siblings on the same route and axis:
  * what IS the caller's fault — an ``action`` that is not a string, ``params``
    that are not an object — reached the gate and the dispatcher unvalidated
    and surfaced as that same misattributed TypeError;
  * the dispatcher returns its own refusals as a JSON payload, and the route
    wrapped every one in HTTP 200 ``ok: true`` (RUN-4, fixed for /api/v1 in
    ServiceRoutes._ok, never here), including payloads carrying raw exception
    text;
  * one layer down, ServiceDispatcher.execute classified every TypeError as
    ``validation`` — "Invalid parameters for X" — including one raised by a
    service's own code after the arguments had bound. The model, and this
    route, were told the call was wrong when the service had crashed.
"""

from __future__ import annotations

import json
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "tests")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from gateway.server import GatewayServer  # noqa: E402
from runtime.blockchain.services.service_dispatcher import ACTION_MAP, ServiceDispatcher  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

READ_ACTION = "get_loan"  # a non-state-modifying action: no attestation or feed side effects
SIGNATURE_TEXT = "get_loan() missing 1 required positional argument: 'loan_id'"


def _server(dispatcher=None) -> GatewayServer:
    scratch = tempfile.mkdtemp(prefix="the-matrix-bridge-action-")
    server = GatewayServer({**SWEEP_CONFIG, "memory_dir": scratch,
                            "database": {"path": f"{scratch}/a.db"}})
    server._test_dispatcher = dispatcher
    return server


async def _post(server, body):
    async with TestClient(TestServer(server.create_app())) as client:
        # Startup attaches the shared dispatcher; replace it after.
        if server._test_dispatcher is not None:
            server.service_dispatcher = server._test_dispatcher
        resp = await client.post("/bridge/v1/action", json=body)
        return resp.status, await resp.text()


# ── internal exceptions are internal ─────────────────────────────────────────

@pytest.mark.parametrize("exc", [TypeError(SIGNATURE_TEXT), KeyError("loan_book"),
                                 TypeError("unhashable type: 'dict'")])
async def test_an_exception_escaping_the_dispatcher_is_an_internal_error_not_the_callers(exc):
    server = _server(SimpleNamespace(execute=AsyncMock(side_effect=exc)))
    status, text = await _post(server, {"action": READ_ACTION, "params": {"loan_id": "1"}})
    body = json.loads(text)
    assert status == 500, (exc, status, body)
    assert body.get("code") == "internal_error" and body.get("ref"), body
    assert str(exc).strip("'") not in text, text


# ── the caller's own mistakes are the caller's ───────────────────────────────

@pytest.mark.parametrize("body", [
    {"action": {"name": READ_ACTION}, "params": {}},     # NEW-9's shape, from the wire
    {"action": [READ_ACTION]},
    {"action": 7},
    {"action": READ_ACTION, "params": ["loan_id", "1"]},
    {"action": READ_ACTION, "params": "loan_id=1"},
    ["not", "an", "object"],
])
async def test_a_malformed_request_is_a_400_before_the_gate_or_the_dispatcher(body):
    execute = AsyncMock(return_value=json.dumps({"status": "ok"}))
    server = _server(SimpleNamespace(execute=execute))
    status, text = await _post(server, body)
    assert status == 400, (body, status, text)
    assert not execute.called, body
    assert "unhashable" not in text and "has no attribute" not in text, text


# ── the dispatcher's own refusals carry a real status ────────────────────────

async def test_an_unknown_action_is_a_404_not_a_200_wrapping_an_error():
    status, text = await _post(_server(), {"action": "no_such_action", "params": {}})
    assert status == 404, (status, text)
    assert json.loads(text).get("ok") is False, text


def _dispatcher_with(method) -> ServiceDispatcher:
    service, method_name = ACTION_MAP[READ_ACTION]
    dispatcher = ServiceDispatcher({})
    svc = SimpleNamespace(**{method_name: method})
    dispatcher._get_registry = lambda: SimpleNamespace(get=lambda name: svc)
    return dispatcher


async def test_arguments_that_do_not_bind_are_a_400_without_the_internal_signature():
    async def get_loan(loan_id):
        return {"loan_id": loan_id}
    status, text = await _post(_server(_dispatcher_with(get_loan)),
                               {"action": READ_ACTION, "params": {"loan": "1"}})
    assert status == 400, (status, text)
    assert "get_loan()" not in text and "unexpected keyword" not in text, text


async def test_a_service_that_crashes_is_not_reported_as_the_callers_invalid_parameters():
    async def get_loan(loan_id):
        record = None
        return record["principal"]  # a TypeError from the service's own code
    dispatcher = _dispatcher_with(get_loan)
    result = json.loads(await dispatcher.execute(READ_ACTION, params={"loan_id": "1"}))
    assert result["status"] == "error", result
    assert result["error_category"] != "validation", result
    assert "Invalid parameters" not in result["error"], result

    status, text = await _post(_server(dispatcher), {"action": READ_ACTION, "params": {"loan_id": "1"}})
    assert 500 <= status < 600, (status, text)
    assert "NoneType" not in text and "subscriptable" not in text, text


async def test_arguments_that_do_not_bind_are_still_validation_for_the_model():
    """The agent loop reads this category to correct its own call."""
    async def get_loan(loan_id):
        return {"loan_id": loan_id}
    result = json.loads(await _dispatcher_with(get_loan).execute(READ_ACTION, params={"loan": "1"}))
    assert result["error_category"] == "validation", result


async def test_a_successful_action_is_unchanged():
    async def get_loan(loan_id):
        return {"loan_id": loan_id, "principal": 10}
    status, text = await _post(_server(_dispatcher_with(get_loan)),
                               {"action": READ_ACTION, "params": {"loan_id": "1"}})
    assert status == 200, (status, text)
    body = json.loads(text)
    assert body["ok"] is True and json.loads(body["data"])["status"] == "ok", body


# ── the other route that relays the dispatcher: /api/v1/capabilities/{id}/invoke ─

async def _invoke(monkeypatch, dispatcher, body):
    from gateway.service_routes import ServiceRoutes
    from runtime.capabilities.registry import CapabilityRegistry
    monkeypatch.setattr(ServiceRoutes, "_capability_registry",
                        lambda self: CapabilityRegistry({}, dispatcher=dispatcher))
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post(f"/api/v1/capabilities/{READ_ACTION}/invoke", json=body)
        return resp.status, await resp.text()


async def test_capability_invoke_does_not_answer_200_for_a_service_that_crashed(monkeypatch):
    async def get_loan(loan_id):
        record = None
        return record["principal"]
    status, text = await _invoke(monkeypatch, _dispatcher_with(get_loan), {"params": {"loan_id": "1"}})
    assert 500 <= status < 600, (status, text)
    assert "NoneType" not in text and "subscriptable" not in text, text


async def test_capability_invoke_answers_unbindable_arguments_with_a_400(monkeypatch):
    async def get_loan(loan_id):
        return {"loan_id": loan_id}
    status, text = await _invoke(monkeypatch, _dispatcher_with(get_loan), {"params": {"loan": "1"}})
    assert status == 400, (status, text)
    assert "unexpected keyword" not in text, text


@pytest.mark.parametrize("params", [["loan_id", "1"], "loan_id=1"])
async def test_capability_invoke_refuses_params_that_are_not_an_object(monkeypatch, params):
    execute = AsyncMock(return_value=json.dumps({"status": "ok"}))
    status, text = await _invoke(monkeypatch, SimpleNamespace(execute=execute), {"params": params})
    assert status == 400, (params, status, text)
    assert not execute.called


async def test_capability_invoke_success_is_unchanged(monkeypatch):
    async def get_loan(loan_id):
        return {"loan_id": loan_id}
    status, text = await _invoke(monkeypatch, _dispatcher_with(get_loan), {"params": {"loan_id": "1"}})
    assert status == 200, (status, text)
    assert json.loads(text)["status"] == "ok"
