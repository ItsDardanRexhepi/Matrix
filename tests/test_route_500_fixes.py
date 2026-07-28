"""NEW-6..9 — the six route failures D1 found that the external audit did not.

Each was triaged individually rather than given a blanket treatment, because
they turned out to be three different kinds of defect:

  NEW-6  /social/feed/stream        signature drift  (real fix)
  NEW-7  /badge/* x3                missing error handling (real fix)
  NEW-8  /bridge/v1/chat            wrong status + leaked exception (real fix)
  NEW-9  /api/v1/capabilities/{}/invoke  two stacked signature errors (real fix)

Notably NONE of them warranted a 501: every one was code trying to do the right
thing and failing, not a missing subsystem. A 501 on any of these would have
told users "not supported" when the truth was "we broke it".
"""

from __future__ import annotations

import warnings

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gateway.server import GatewayServer

warnings.filterwarnings("ignore")

CONFIG = {"gateway": {"rate_limit_rpm": 100_000, "rate_limit_burst": 100_000,
                      "rate_limit_rpm_authenticated": 100_000,
                      "rate_limit_burst_authenticated": 100_000,
                      "rate_limit_rpm_anonymous": 100_000,
                      "rate_limit_burst_anonymous": 100_000}}
AUTH = {"Authorization": "Bearer test-key"}


@pytest.fixture
async def client():
    server = GatewayServer(CONFIG)
    async with TestClient(TestServer(server.create_app())) as c:
        yield c


# ── NEW-6: EventBroadcaster.register signature drift ───────────────────────

async def test_broadcaster_register_accepts_the_handler_s_arguments():
    """The SSE handler's call must match register()'s real signature.

    The handler called `broadcaster.register(ip=...)` synchronously. Three
    faults at once: the parameter is `remote_ip`; register is `async` and was
    never awaited; and BroadcasterCapacityError went unhandled. Because it fired
    AFTER response.prepare(), the client saw a truncated stream rather than an
    error, which is why body-string matching alone did not catch it.

    Asserted directly against the broadcaster rather than over HTTP: an SSE
    stream never completes, so a request/response client cannot consume one.
    """
    from gateway.event_broadcaster import EventBroadcaster

    broadcaster = EventBroadcaster()
    sub = await broadcaster.register(remote_ip="1.2.3.4", types={"feed.new_event"})
    assert sub is not None
    await broadcaster.unregister(sub)


async def test_sse_handler_calls_register_correctly():
    """Guard the exact call shape the handler uses, so it cannot drift again."""
    import inspect

    from gateway.event_broadcaster import EventBroadcaster
    from gateway.server import GatewayServer as GS

    sig = inspect.signature(EventBroadcaster.register)
    assert "remote_ip" in sig.parameters, "register() lost its remote_ip parameter"
    assert "ip" not in sig.parameters, "register() grew an `ip` parameter — update the handler"
    assert inspect.iscoroutinefunction(EventBroadcaster.register), "register must be awaited"

    src = inspect.getsource(GS.handle_social_feed_stream)
    assert "await broadcaster.register(" in src, "the handler must await register()"
    assert "remote_ip=" in src, "the handler must pass remote_ip="
    assert "BroadcasterCapacityError" in src, (
        "the handler must translate the capacity error the broadcaster documents"
    )


# ── NEW-7: badge routes returned 500 for ordinary not-found / bad input ────

async def test_unknown_badge_status_is_404_not_500(client):
    resp = await client.get("/badge/no-such-badge/status", headers=AUTH)
    assert resp.status == 404, (
        f"unknown badge id -> {resp.status}. verify_badge() correctly raises "
        "ValueError for a missing badge; the handler must translate that to 404, "
        "not let it escape as a server error."
    )
    assert (await resp.json())["status"] == "not_found"


async def test_unknown_badge_embed_is_404_not_500(client):
    resp = await client.get("/badge/no-such-badge/embed", headers=AUTH)
    assert resp.status == 404
    assert (await resp.json())["status"] == "not_found"


async def test_badge_issue_rejects_bad_input_with_400_not_500(client):
    """A caller's invalid audit report is a 400, not the server's fault."""
    resp = await client.post(
        "/badge/issue",
        json={"contract_address": "0xabc", "contract_name": "X", "audit_report": {}},
        headers=AUTH,
    )
    assert resp.status == 400, f"invalid issuance input -> {resp.status}, expected 400"
    assert (await resp.json())["status"] == "rejected"


# ── NEW-8: bridge chat disagreed with /chat and leaked the exception ───────

async def test_bridge_chat_is_503_and_redacted_when_the_model_is_unreachable(client):
    """One error contract across channels: /chat answers 503, so must the bridge.

    It answered 500 AND put the raw exception in the body, shipping internal
    hostnames, ports and model names to the client.
    """
    resp = await client.post(
        "/bridge/v1/chat", json={"message": "hello", "agent": "trinity"}, headers=AUTH
    )
    assert resp.status == 503, (
        f"unreachable model provider -> {resp.status}; /chat answers 503 for the "
        "identical condition and the two channels must not disagree"
    )
    body = await resp.text()
    for leak in ("Traceback", "localhost:", "11434", "Connect call failed",
                 "has no attribute", "ollama"):
        assert leak not in body, f"bridge chat leaked {leak!r}: {body[:300]}"


# ── NEW-9: capability invoke — two stacked signature errors ────────────────

async def test_capability_invoke_reaches_the_dispatcher(client):
    """The whole capability-invoke surface was dead behind two TypeErrors.

    First `ServiceDispatcher(config, registry)` (it takes only config), then —
    once that was fixed — `execute({...})` where execute takes
    (action, service, params), so `action not in ACTION_MAP` raised
    `unhashable type: 'dict'`. A service-level error in the RESULT is fine here;
    what must not happen is the request failing to reach the dispatcher at all.
    """
    resp = await client.post(
        "/api/v1/capabilities/send_payment/invoke", json={"params": {}}, headers=AUTH
    )
    assert resp.status == 200, f"capability invoke -> {resp.status}, expected 200"
    body = await resp.text()
    for leak in ("unhashable type", "takes 2 positional arguments",
                 "has no attribute", "Traceback"):
        assert leak not in body, f"capability invoke leaked {leak!r}"
