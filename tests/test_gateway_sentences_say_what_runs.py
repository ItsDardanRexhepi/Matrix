"""Five gateway sentences, each checked against what the code beside it does.

  * "Nonce must be one we issued and still valid" (gateway/server.py). The
    store's membership test was bare; expiry happened only when the periodic
    sweep ran, so a nonce stayed acceptable for up to twice its TTL, and
    forever if the sweep died. The age is now compared at the moment of use.
  * "Only the two values that mean 'the operation did not happen' are
    failures" (service_routes._FAILURE_STATUSES). `not_deployed` means exactly
    that and is answered 503 by `refusal_http_status` — a correct behaviour
    described by a sentence that read as the complete list.
  * "The real handlers only touch request.json() and request.match_info"
    (_BatchSubRequest). Handlers read request.query and request.get(...), and
    the look-alike implements both, because they do.
  * "This backend only initializes the plugin marketplace, A2A, social,
    badges, certification, and professional services" (server._start_cleanup_task).
    Startup does more, and professional services are initialized nowhere.
  * "`set_rights` always carries params" (bridge). The params are the caller's
    and optional.

And one in the social feed: "Ingest is designed to never block the main
request path" — the ingest is not awaited by the caller, but its sqlite work
runs on the event loop and blocks every coroutine while it runs.
"""

from __future__ import annotations

import inspect
import re
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _prose(text: str) -> str:
    """Comment/docstring text with the comment markers and line breaks gone."""
    return re.sub(r"\s+", " ", re.sub(r"\s*#\s*", " ", text))


# ── the nonce ──────────────────────────────────────────────────────────────

async def test_an_expired_nonce_is_not_accepted_before_the_sweep_runs(tmp_path):
    from runtime.auth.session_store import NONCE_TTL_SECONDS, NonceStore
    from runtime.db.database import Database

    db = Database({"database": {"path": str(tmp_path / "n.db")}})
    store = NonceStore(db)
    await store.add("fresh")
    await store.add("stale")
    store._cache["stale"] = time.time() - NONCE_TTL_SECONDS - 1

    assert "fresh" in store
    assert "stale" not in store, (
        "a nonce past its TTL is still accepted until the sweep happens to run")


# ── the failure-status sentence ────────────────────────────────────────────

def test_the_failure_status_comment_does_not_read_as_the_complete_list():
    src = _prose(inspect.getsource(
        __import__("gateway.service_routes", fromlist=["x"])))
    i = src.find("_FAILURE_STATUSES = frozenset")
    comment = src[max(0, i - 1500):i]
    assert 'Only the two values that mean "the operation did not happen" are failures' \
        not in comment
    assert "not_deployed" in comment and "refusal_http_status" in comment


def test_not_deployed_is_answered_as_a_refusal_by_the_transport():
    """What the corrected sentence points at, pinned: the behaviour was right."""
    from gateway.error_contract import refusal_http_status

    assert refusal_http_status({"status": "not_deployed"}) == 503


# ── the batch look-alike ───────────────────────────────────────────────────

def test_the_batch_request_docstring_names_what_handlers_read():
    from gateway.service_routes import _BatchSubRequest

    doc = _prose(_BatchSubRequest.__doc__ or "")
    assert "only touch" not in doc
    assert "request.query" in doc and "request.get" in doc
    req = _BatchSubRequest(body={}, match_info={}, method="GET", path="/x")
    assert hasattr(req, "query") and callable(req.get)


# ── startup ────────────────────────────────────────────────────────────────

def test_the_startup_comment_does_not_list_a_subsystem_that_does_not_exist():
    from gateway.server import GatewayServer

    src = _prose(inspect.getsource(GatewayServer._start_cleanup_task))
    i = src.find("Initialize platform subsystems")
    comment = src[i:i + 800]
    assert "only initializes the plugin marketplace" not in comment
    assert "initialized nowhere" in comment


# ── the bridge premise ─────────────────────────────────────────────────────

def test_the_bridge_does_not_say_params_are_always_present():
    text = _prose((ROOT / "gateway" / "bridge.py").read_text(encoding="utf-8"))
    assert "`set_rights` always carries params" not in text


# ── the feed ingest ────────────────────────────────────────────────────────

def test_the_feed_engine_does_not_promise_ingest_never_blocks():
    from runtime.social import feed_engine

    doc = _prose(feed_engine.__doc__ or "")
    assert "never block the main request path" not in doc
    assert "event loop" in doc
