"""RUN-5 — one error contract for every channel.

The gateway leaked raw exception text to clients from 13 sites across three
files. In the sandbox that text read `Cannot connect to host localhost:11434`;
in production, with Anthropic or OpenAI configured, the same field carries
upstream endpoint URLs, org IDs, key prefixes and quota detail. Worse, the
channels disagreed: `/chat` answered 503 for an unreachable model while
`/bridge/v1/chat` answered 500 for the identical condition, so two clients
observing the same event drew different conclusions.

This module is the single place that decides both halves — what status a failure
gets, and what the client is allowed to see.

    status, body = client_error(exc, req_id, what="Chat")

**The body shape is load-bearing** and is constrained by the clients, not chosen
freely:

    {"error": "<stable sentence> (ref: <req_id>)",
     "code":  "<stable machine code>",
     "ref":   "<req_id>"}

`error` must be a top-level STRING because the Swift client's
`extractErrorMessage` reads `obj["error"] as? String`, falling back only to a
top-level `obj["message"] as? String`; anything richer in `error` would arrive
as nil and the user would see an empty message. The
correlation id is repeated INSIDE that sentence so it survives even where a
client keeps only the message — which is what makes a redacted error still
actionable. This is also what lets a RUN-5 body pass cleanly through RUN-4's
now-throwing client path: it decodes as ordinary JSON and becomes a typed
error carrying the ref, never a decode failure.

The full exception, with its traceback, is logged server-side against the same
`req_id`. Nothing is lost — it just stops being the client's business.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Failures that mean "a dependency we call is not reachable". These are 503:
# the request was fine, the thing behind us is not.
_UNREACHABLE = (
    ConnectionError,
    ConnectionRefusedError,
    OSError,
    asyncio.TimeoutError,
    TimeoutError,
)

# Substrings that identify an unreachable upstream even when the exception type
# has been flattened into a generic Exception on the way up (the model-provider
# aggregator does exactly this: "All model providers failed: ...").
_UNREACHABLE_MARKERS = (
    "model providers failed",
    "cannot connect to host",
    "connection refused",
    "connect call failed",
    "name or service not known",
)

# Checked BEFORE the unreachable markers. A timeout that arrives typed gets 504
# from the isinstance branch; a timeout that has been flattened into a generic
# Exception on the way up must get 504 too, or the same real condition answers
# differently depending on how far it travelled — which is the exact
# channel-disagreement this module exists to remove.
_TIMEOUT_MARKERS = (
    "timed out",
    "timeout",
)

# code -> (http status, the sentence a client may see)
_CONTRACT: dict[str, tuple[int, str]] = {
    "upstream_unavailable": (
        503,
        "A service this request depends on is unreachable right now. "
        "Please try again shortly.",
    ),
    "upstream_timeout": (
        504,
        "A service this request depends on did not respond in time. "
        "Please try again shortly.",
    ),
    "invalid_request": (400, "That request could not be understood."),
    "not_found": (404, "That resource does not exist."),
    "internal_error": (500, "That request could not be completed."),
}


# The ServiceDispatcher reports its own failures as a payload with an
# ``error_category``; this is the HTTP status each category means, shared by
# every route that relays a dispatcher or service payload (ServiceRoutes._ok,
# the bridge's /bridge/v1/action). Unknown categories are 422: the request was
# well-formed but the operation could not be completed.
DISPATCHER_CATEGORY_HTTP: dict[str, int] = {
    "validation": 400,
    "bad_request": 400,
    "not_found": 404,
    "forbidden": 403,
    "not_implemented": 501,
    "service_unavailable": 503,
    "service_error": 502,
    "timeout": 504,
}

#: Categories whose dispatcher message is a sentence written for the caller.
#: Every other category's message carries raw exception text (a Python binding
#: message, a service's own exception), which stays server-side against a ref.
DISPATCHER_CALLER_MESSAGES = frozenset({"not_found", "not_implemented", "forbidden"})


def classify(exc: BaseException) -> str:
    """Return the stable machine code for *exc*. Never raises."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "upstream_timeout"
    if isinstance(exc, _UNREACHABLE):
        return "upstream_unavailable"
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        # A bad argument reaching this far is our fault, not the caller's —
        # a genuinely invalid request should have been rejected at validation.
        return "internal_error"

    text = str(exc).lower()
    if any(marker in text for marker in _TIMEOUT_MARKERS):
        return "upstream_timeout"
    if any(marker in text for marker in _UNREACHABLE_MARKERS):
        return "upstream_unavailable"
    return "internal_error"


def client_error(
    exc: BaseException,
    req_id: str | None,
    *,
    what: str = "Request",
    code: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Log *exc* in full, return ``(http_status, redacted_body)``.

    ``req_id`` may be omitted: the id is already carried in a contextvar set by
    ``_request_id_middleware`` (``runtime.logging.json_formatter``), which is
    also what the server-side log line is tagged with. Reading it here is what
    makes the ref a REAL correlation handle rather than a placeholder — an
    earlier draft passed ``request.get("request_id")``, which is not where the
    middleware stores it, so every response carried ``ref: "-"`` and the
    redaction gave the operator nothing to grep for.

    When there genuinely is no id the body still carries ``ref: "-"`` rather
    than omitting the key, so the shape a client parses never varies.
    """
    if not req_id:
        try:
            from runtime.logging.json_formatter import get_request_id

            req_id = get_request_id()
        except Exception:  # logging must never break error handling
            req_id = None
    ref = req_id or "-"
    resolved = code or classify(exc)
    status, message = _CONTRACT.get(resolved, _CONTRACT["internal_error"])

    # Full detail, server-side only, correlated by ref.
    logger.error(
        "%s failed [ref=%s code=%s]: %s", what, ref, resolved, exc, exc_info=True
    )

    return status, {
        "error": f"{message} (ref: {ref})",
        "code": resolved,
        "ref": ref,
    }


def dispatcher_failure(result: Any, *, what: str) -> tuple[int, dict[str, Any]] | None:
    """``(status, body)`` when *result* is a ServiceDispatcher failure payload
    (its JSON string or the decoded dict), else None.

    The status is DISPATCHER_CATEGORY_HTTP's. The body is this module's shape:
    the dispatcher's own sentence where it wrote one for the caller
    (DISPATCHER_CALLER_MESSAGES), otherwise the contract sentence with a ref,
    the dispatcher's text logged server-side against it — a binding message
    names internal signatures, and a service's exception text is RUN-5's leak.
    ``code`` is the dispatcher's category, so a client can still branch on it.
    """
    import json

    try:
        payload = json.loads(result) if isinstance(result, (str, bytes)) else result
    except ValueError:
        return None
    if not (isinstance(payload, dict) and payload.get("status") == "error"):
        return None
    category = str(payload.get("error_category") or "")
    status = DISPATCHER_CATEGORY_HTTP.get(category, 422)
    if category in DISPATCHER_CALLER_MESSAGES:
        return status, {"error": str(payload.get("error") or "the action failed"), "code": category}
    contract_code = {"validation": "invalid_request",
                     "bad_request": "invalid_request",
                     "service_unavailable": "upstream_unavailable",
                     "timeout": "upstream_timeout"}.get(category, "internal_error")
    _st, body = client_error(RuntimeError(str(payload.get("error") or category)), None,
                             what=what, code=contract_code)
    body["code"] = category or contract_code
    return status, body


def sse_error_frame(exc: BaseException, req_id: str | None, *, what: str) -> bytes:
    """The same contract, shaped as a Server-Sent Events frame.

    A stream cannot carry an HTTP status once its headers are out, so the code
    travels in the payload instead. Same redaction, same ref.
    """
    import json

    status, body = client_error(exc, req_id, what=what)
    body["status"] = status
    return b"event: error\ndata: " + json.dumps(body).encode() + b"\n\n"


def is_redacted(body: Any) -> bool:
    """True when *body* already conforms to the contract.

    Used by tests to assert a response is redacted rather than merely
    non-empty.
    """
    return (
        isinstance(body, dict)
        and isinstance(body.get("error"), str)
        and isinstance(body.get("code"), str)
        and "ref" in body
    )
