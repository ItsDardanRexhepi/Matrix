"""RUN-5 — one error contract across every channel, and it must compose with RUN-4.

Two things are proven here.

1. NOTHING a client can see carries internal detail. The audit found the leak on
   /chat; the real count was 13 sites across three files, and the channels also
   DISAGREED — /chat answered 503 for an unreachable model while
   /bridge/v1/chat answered 500 for the identical condition.

2. The redacted body composes with RUN-4. RUN-4 made the clients throw on a
   failing response; RUN-5 changes what that response CONTAINS. If the redacted
   shape did not parse, the client would report a decode failure instead of the
   real error and the correlation id would be lost — trading one dishonest
   message for another. The shape is therefore constrained by the client, not
   chosen freely: `error` must be a top-level string, because Swift's
   `extractErrorMessage` reads `obj["error"] as? String`, falling back only to a
   top-level `obj["message"] as? String`.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from gateway.error_contract import classify, client_error, is_redacted, sse_error_frame

# Anything matching these in a client-visible body is a leak.
FORBIDDEN = (
    "Traceback",
    "has no attribute",
    "Connect call failed",
    "Cannot connect to host",
    "localhost:11434",
    "llama3.1",
    "mistral",
    "sk-",
    "api_key",
)


def _leaks(body: str) -> list[str]:
    return [s for s in FORBIDDEN if s in body]


# ── redaction ──────────────────────────────────────────────────────────────

def test_provider_failure_is_redacted_to_a_stable_sentence():
    """The exact leak the audit found, now closed."""
    exc = RuntimeError(
        "All model providers failed: ollama: Both Ollama models failed. "
        "Primary (llama3.1:8b): Cannot connect to host localhost:11434 "
        "ssl:default [Errno 61] Connect call failed ('127.0.0.1', 11434)"
    )
    status, body = client_error(exc, "req-abc", what="Chat")

    assert status == 503, "an unreachable provider is a dependency failure"
    rendered = json.dumps(body)
    assert not _leaks(rendered), f"leaked {_leaks(rendered)} in {rendered}"
    assert body["code"] == "upstream_unavailable"
    assert body["ref"] == "req-abc"
    assert "req-abc" in body["error"], (
        "the correlation id must be inside the message too — a client that "
        "keeps only the message would otherwise have nothing to quote"
    )


@pytest.mark.parametrize(
    "exc,expected_code,expected_status",
    [
        (ConnectionRefusedError("refused"), "upstream_unavailable", 503),
        (OSError("no route to host"), "upstream_unavailable", 503),
        (asyncio.TimeoutError(), "upstream_timeout", 504),
        (RuntimeError("something opaque"), "internal_error", 500),
        (RuntimeError("Cannot connect to host x:1"), "upstream_unavailable", 503),
    ],
)
def test_classification_is_stable(exc, expected_code, expected_status):
    assert classify(exc) == expected_code
    status, body = client_error(exc, "r1")
    assert status == expected_status
    assert body["code"] == expected_code


def test_a_flattened_timeout_is_still_a_timeout():
    """The same condition must not answer differently by how far it travelled.

    A typed asyncio.TimeoutError gets 504 from the isinstance branch. Once the
    provider aggregator flattens it into `RuntimeError("All model providers
    failed: ... timed out")`, only the text survives — and the text markers
    used to classify it as `upstream_unavailable` (503), so one real condition
    produced two different answers depending on the depth it was raised at.
    That is the channel disagreement this module exists to remove.
    """
    typed = classify(asyncio.TimeoutError())
    flattened = classify(
        RuntimeError("All model providers failed: ollama: request timed out")
    )
    assert typed == flattened == "upstream_timeout", (
        f"typed timeout -> {typed}, flattened -> {flattened}"
    )


# ── retryability: the over-correction guard ────────────────────────────────

@pytest.mark.parametrize(
    "exc,retryable,why",
    [
        (asyncio.TimeoutError(), True, "a slow provider may answer next attempt"),
        (TimeoutError("timed out"), True, "same, raised as the builtin"),
        (ConnectionRefusedError("refused"), False, "nothing is listening; it will not heal"),
        (OSError("no route to host"), False, "no path exists; retrying is pure latency"),
        (RuntimeError("500 from provider"), True, "a 5xx is worth another attempt"),
    ],
)
def test_unreachable_does_not_swallow_retryable_failures(exc, retryable, why):
    """RUN-5 stopped retrying unreachable providers. It must NOT have stopped
    retrying transient ones.

    The trap is real and silent: TimeoutError subclasses OSError, and since
    Python 3.11 asyncio.TimeoutError IS TimeoutError. A bare
    `isinstance(exc, OSError)` therefore classes every timeout — including
    aiohttp.ServerTimeoutError — as unreachable, and the fix for a latency bug
    becomes a reliability bug that no existing test would notice.
    """
    from runtime.models.router import _is_unreachable

    assert _is_unreachable(exc) is not retryable, why


def test_aiohttp_server_timeout_is_retryable():
    """The concrete type this actually arrives as in production."""
    import aiohttp

    from runtime.models.router import _is_unreachable

    assert issubclass(aiohttp.ServerTimeoutError, TimeoutError), (
        "assumption changed upstream — re-check the classification"
    )
    assert _is_unreachable(aiohttp.ServerTimeoutError("timed out")) is False


@pytest.mark.parametrize(
    "label,exc,retried",
    [
        ("timeout", asyncio.TimeoutError(), True),
        ("5xx", RuntimeError("500 upstream"), True),
        ("refused", ConnectionRefusedError("refused"), False),
        ("no route", OSError("no route to host"), False),
    ],
)
async def test_the_retry_loop_actually_honours_the_distinction(label, exc, retried):
    """Behaviour, not just the predicate — count real attempts through complete().

    A correct `_is_unreachable` still proves nothing if the loop consults it
    wrongly, so this drives the actual provider chain with a failing stub.
    """
    from runtime.models.router import MAX_RETRIES, ModelRouter

    class Flaky:
        def __init__(self): self.attempts = 0
        async def complete(self, *a, **k):
            self.attempts += 1
            raise exc

    provider = Flaky()
    router = ModelRouter.__new__(ModelRouter)
    router.providers, router.primary_name = {"p": provider}, "p"
    router._classify_and_get_kwargs = lambda *a, **k: {}

    with pytest.raises(RuntimeError):
        await router.complete([{"role": "user", "content": "x"}], agent_name="t")

    expected = MAX_RETRIES if retried else 1
    assert provider.attempts == expected, (
        f"{label}: {provider.attempts} attempt(s), expected {expected} — "
        "a transient failure must still get its retries"
    )


def test_missing_correlation_id_still_yields_the_same_shape():
    """A client parses one shape; it must not vary because a ref was absent."""
    _, body = client_error(RuntimeError("x"), None)
    assert is_redacted(body)
    assert body["ref"] == "-"


# ── one contract across channels ───────────────────────────────────────────

async def test_all_channels_agree_on_the_same_condition():
    """/chat and /bridge/v1/chat disagreed: 503 vs 500 for one event.

    This drives BOTH ROUTES for real. An earlier version of this test called
    `client_error` twice and compared the two results, which is vacuous against
    the bug that matters: a channel that never calls the contract at all. The
    bridge did exactly that — it hand-rolled its own classification, so it
    agreed on status while diverging on shape (no `code`, ref always "-"), and
    a function-level test could not see it. Only a live request can.
    """
    import sys
    sys.path.insert(0, "tests")
    from aiohttp.test_utils import TestClient, TestServer

    from gateway.server import GatewayServer
    from test_route_sweep import SWEEP_CONFIG

    server = GatewayServer(SWEEP_CONFIG)
    seen = []
    async with TestClient(TestServer(server.create_app())) as client:
        for path in ("/chat", "/bridge/v1/chat"):
            resp = await client.post(
                path,
                json={"message": "hi", "agent": "neo"},
                headers={"Authorization": "Bearer k"},
            )
            raw = await resp.text()
            body = json.loads(raw)
            assert not _leaks(raw), f"{path} leaked {_leaks(raw)}"
            assert body.get("ref") == resp.headers.get("X-Request-ID"), (
                f"{path}: ref does not correlate with the log line"
            )
            seen.append((path, resp.status, body.get("code")))

    statuses = {s for _, s, _ in seen}
    codes = {c for _, _, c in seen}
    assert statuses == {503}, f"channels disagree on status: {seen}"
    assert codes == {"upstream_unavailable"}, f"channels disagree on code: {seen}"


def test_sse_error_frame_carries_the_contract_in_the_payload():
    """A stream cannot set a status after its headers, so the code travels
    in the frame instead — same redaction, same ref."""
    frame = sse_error_frame(
        ConnectionRefusedError("Cannot connect to host localhost:11434"),
        "req-9", what="Stream",
    )
    text = frame.decode()
    assert text.startswith("event: error\ndata: ")
    assert text.endswith("\n\n"), "an SSE frame must terminate with a blank line"
    assert not _leaks(text), f"leaked {_leaks(text)}"

    payload = json.loads(text.split("data: ", 1)[1])
    assert is_redacted(payload)
    assert payload["status"] == 503
    assert payload["ref"] == "req-9"


# ── RUN-4 x RUN-5 composition — the seam the reviewer asked for ────────────

def test_redacted_body_is_parseable_by_the_swift_client_contract():
    """A RUN-5 body, sent through RUN-4's throwing client, must arrive as a
    usable error — never a decode failure.

    Swift's MTRXAPIClient.extractErrorMessage does exactly:
        (obj["error"] as? String) ?? (obj["message"] as? String)
    replicated here. If `error` were a dict, a list, or absent, the client
    would surface an empty message and the ref would be lost — swapping a leaky
    error for an uninformative one.
    """
    _, body = client_error(
        RuntimeError("All model providers failed: cannot connect to host x:1"),
        "req-compose", what="Chat",
    )
    raw = json.dumps(body).encode()

    # 1. It is valid JSON with a top-level object — Swift's JSONSerialization step.
    obj = json.loads(raw)
    assert isinstance(obj, dict), "a non-object body decodes to nil in Swift"

    # 2. extractErrorMessage finds a String.
    message = obj.get("error") if isinstance(obj.get("error"), str) else obj.get("message")
    assert isinstance(message, str) and message, (
        "extractErrorMessage would return nil — the user sees an empty error"
    )

    # 3. The correlation id survives into what the user can quote.
    assert "req-compose" in message

    # 4. And it is still redacted after the round trip.
    assert not _leaks(raw.decode())


def test_redacted_body_does_not_collide_with_the_run4_envelope():
    """RUN-4 keys off an inner `status` of error/unavailable. A RUN-5 body must
    not accidentally look like a service payload and get double-handled."""
    from gateway.service_routes import ServiceRoutes

    _, body = client_error(RuntimeError("boom"), "r")
    # The contract deliberately uses `code`, not `status`, for its machine value.
    assert "status" not in body, (
        "a top-level `status` would make a redacted error indistinguishable "
        "from a service payload to _ok()"
    )
    resp = ServiceRoutes(config={})._ok(body)
    assert resp.status == 200, (
        "a redacted error passed as data must not be re-classified as a failure"
    )


# ── the ref must be a REAL correlation handle ──────────────────────────────

async def test_error_ref_matches_the_response_request_id_header():
    """The whole value of redaction is that the operator can still find it.

    An earlier draft read `request.get("request_id")`, which is not where
    `_request_id_middleware` stores the id — it uses a contextvar. Every
    response therefore carried `ref: "-"` and the redaction gave the operator
    nothing to grep for. This pins ref == X-Request-ID so that regression is
    visible immediately.
    """
    import sys
    sys.path.insert(0, "tests")
    from aiohttp.test_utils import TestClient, TestServer

    from gateway.server import GatewayServer
    from test_route_sweep import SWEEP_CONFIG

    server = GatewayServer(SWEEP_CONFIG)
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post(
            "/chat",
            json={"message": "hi", "agent": "neo"},
            headers={"Authorization": "Bearer k"},
        )
        body = await resp.json()
        header_id = resp.headers.get("X-Request-ID")

        assert body.get("ref") not in (None, "-"), (
            "the correlation id never reached the response"
        )
        assert body["ref"] == header_id, (
            f"ref {body['ref']!r} does not match X-Request-ID {header_id!r} — "
            "the operator cannot correlate the client's error with the log line"
        )
