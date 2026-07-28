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
   `extractErrorMessage` reads `obj["error"] as? String` and nothing else.
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


def test_missing_correlation_id_still_yields_the_same_shape():
    """A client parses one shape; it must not vary because a ref was absent."""
    _, body = client_error(RuntimeError("x"), None)
    assert is_redacted(body)
    assert body["ref"] == "-"


# ── one contract across channels ───────────────────────────────────────────

def test_all_channels_agree_on_the_same_condition():
    """/chat and /bridge/v1/chat disagreed: 503 vs 500 for one event.

    Both now derive their status from the same function, so the disagreement
    cannot recur without changing the contract itself.
    """
    exc = RuntimeError("All model providers failed: cannot connect to host x:1")
    chat_status, chat_body = client_error(exc, "r", what="Chat")
    bridge_status, bridge_body = client_error(exc, "r", what="Bridge")

    assert chat_status == bridge_status == 503
    assert chat_body["code"] == bridge_body["code"]


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
