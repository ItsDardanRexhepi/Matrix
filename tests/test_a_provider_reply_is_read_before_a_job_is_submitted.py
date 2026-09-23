"""A compute job is submitted when the provider accepted it, not when it was asked.

THE DEFECT. `compute.submit_compute_job`, `rent_device` and the provider-API
path of `claim_compute_reward` called the provider's REST API through
`_provider_request` and then answered "submitted", "reserved" or
"claim_submitted" whatever came back. `_provider_request` never raises: a
connection refused, a 401 for a bad key, a 503 — each came back as a dict,
went under `provider_result`, which no reader looks through, and the method
said its word over it. "submitted" is a broadcast word, so the dispatcher
recorded a broadcast for a request the provider had refused, and outcome
learning read it as a success.

THE THREE ANSWERS, the same three `classify_transport_fault` gives the
creator-platform publishers, which face the same question:

    never left, or the provider answered 4xx -> a refusal, in its words
    the provider answered 5xx, or the fault
    came after the request was out          -> unknown: not a refusal, not
                                               a submission, recorded as a
                                               broadcast under no hash
    the provider answered 2xx               -> the word, as before

WHAT THIS DOES NOT CLAIM. A 2xx is the provider accepting the request, not the
job running; the word stays a broadcast word and the gate keeps reading it as
one. Nothing here re-checks the provider later.
"""

from __future__ import annotations

import sys
import types

import pytest

from runtime.blockchain.services.compute.service import DecentralizedComputeService
from runtime.blockchain.services.service_dispatcher import (
    RECORD_BROADCAST,
    RECORD_REFUSED,
    RECORD_SETTLED,
    _record_verdict,
)
from runtime.protocols.outcome_truth import FAILURE, SUCCESS, UNKNOWN, report_of

ADDR = "0x" + "1" * 40
_CONFIG = {"services": {"compute": {
    "endpoint": "https://provider.example",
    "api_key": "k3y-" + "f" * 40,
    "provider": "akash",
}}}

#: The three provider calls, what to call them with, and the word each says.
_CALLS = [
    ("submit_compute_job", {"image": "render:1"}, "submitted"),
    ("rent_device", {"device_type": "gpu"}, "reserved"),
    ("claim_compute_reward", {"recipient": ADDR}, "claim_submitted"),
]
_IDS = [c[0] for c in _CALLS]


def _service(monkeypatch, reply):
    """A compute service whose provider answers *reply*, exactly as
    `_provider_request` would hand it back."""
    svc = DecentralizedComputeService(_CONFIG)
    calls: list = []

    async def _request(method, endpoint, api_key, path, json_body=None):
        calls.append((method, path, json_body))
        return reply

    monkeypatch.setattr(svc, "_provider_request", _request)
    return svc, calls


_REFUSALS = [
    # what `_provider_request` returns for a request that never left
    {"status": "error", "error": "[Errno 61] Connection refused", "fault": "not_sent"},
    # the provider answered, and refused
    {"http_status": 401, "ok": False, "response": {"message": "invalid api key"}},
    {"http_status": 422, "ok": False, "response": {"message": "sdl is required"}},
]


@pytest.mark.parametrize("method,kwargs,word", _CALLS, ids=_IDS)
@pytest.mark.parametrize("reply", _REFUSALS, ids=["never_left", "401", "422"])
async def test_a_request_the_provider_refused_is_not_a_submission(monkeypatch, method, kwargs, word, reply):
    """DEFECT-PROVER, one per call and per refusal. Before: the word, over
    the provider's error."""
    svc, calls = _service(monkeypatch, reply)
    out = await getattr(svc, method)(**kwargs)
    assert len(calls) == 1, f"premise changed — {method} never asked the provider: {out}"
    assert out.get("status") != word, f"{method} said {word!r} over a provider refusal: {out}"
    assert report_of(out) is FAILURE, f"{method}: a provider refusal was reported as {report_of(out)}: {out}"
    assert _record_verdict(out) == RECORD_REFUSED, out
    assert out["provider_result"] == reply, "the provider's own words were dropped"
    if "http_status" in reply:
        assert str(reply["http_status"]) in out["error"] and "invalid api key" in out["error"] or "sdl" in out["error"], out


_UNKNOWNS = [
    {"http_status": 503, "ok": False, "response": {"message": "try again"}},
    {"status": "error", "error": "read timed out", "fault": "unknown"},
]


@pytest.mark.parametrize("method,kwargs,word", _CALLS, ids=_IDS)
@pytest.mark.parametrize("reply", _UNKNOWNS, ids=["503", "fault_after_send"])
async def test_a_reply_that_establishes_nothing_is_neither_refused_nor_submitted(monkeypatch, method, kwargs, word, reply):
    """DEFECT-PROVER, the other half: a 5xx, or a fault after the request was
    out, is the third answer. Before: the word."""
    svc, calls = _service(monkeypatch, reply)
    out = await getattr(svc, method)(**kwargs)
    assert len(calls) == 1, out
    assert out.get("status") != word, f"{method} said {word!r} over an answer that establishes nothing: {out}"
    assert report_of(out) is UNKNOWN, f"{method}: {report_of(out)}: {out}"
    assert _record_verdict(out) == RECORD_BROADCAST, out
    assert out.get("settled") is False and out.get("tx_hash") is None, out
    assert "NOT a refusal" in out["disclosure"] and "NOT a submission" in out["disclosure"]


#: What the gate recorded for each word before this change, and still does:
#: "submitted" and "claim_submitted" are broadcast words; "reserved" is not —
#: a 2xx on the lease endpoint is the provider saying the lease is reserved,
#: which is the record `rent_device` exists to make.
_VERDICT_OF_THE_WORD = {"submitted": RECORD_BROADCAST, "claim_submitted": RECORD_BROADCAST,
                        "reserved": RECORD_SETTLED}


@pytest.mark.parametrize("method,kwargs,word", _CALLS, ids=_IDS)
async def test_an_accepted_request_still_says_its_word(monkeypatch, method, kwargs, word):
    """SCOPE PIN: a 2xx keeps the word, and the gate reads the word exactly
    as it did before — the provider accepted the request, and that is all
    this change lets the method say."""
    svc, calls = _service(monkeypatch, {"http_status": 201, "ok": True, "response": {"id": "dep-1"}})
    out = await getattr(svc, method)(**kwargs)
    assert len(calls) == 1
    assert out["status"] == word, out
    assert report_of(out) is SUCCESS
    assert _record_verdict(out) == _VERDICT_OF_THE_WORD[word], (
        f"the gate reads {word!r} differently than it did: {_record_verdict(out)}")


# ── the fault's kind travels with the error ───────────────────────────────


def _httpx_that_raises(exc_type):
    """A stand-in for the lazily imported httpx whose client raises."""
    fake = types.ModuleType("httpx")

    class _Client:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def request(self, *_a, **_k):
            raise exc_type("boom")

    fake.AsyncClient = _Client
    return fake


@pytest.mark.parametrize("exc_name,kind", [
    ("ConnectError", "not_sent"),
    ("ConnectTimeout", "not_sent"),
    ("ReadTimeout", "unknown"),
    ("RemoteProtocolError", "unknown"),
])
async def test_a_transport_fault_says_whether_the_request_was_out(monkeypatch, exc_name, kind):
    """`_provider_request` swallows every exception into a dict; the dict now
    carries the one fact the caller needs from the exception type."""
    monkeypatch.setitem(sys.modules, "httpx", _httpx_that_raises(type(exc_name, (Exception,), {})))
    svc = DecentralizedComputeService(_CONFIG)
    reply = await svc._provider_request("POST", "https://provider.example", "k", path="/v1/x")
    assert reply["status"] == "error" and reply["fault"] == kind, reply


async def test_a_missing_client_library_is_a_request_that_never_left(monkeypatch):
    monkeypatch.setitem(sys.modules, "httpx", None)
    svc = DecentralizedComputeService(_CONFIG)
    reply = await svc._provider_request("POST", "https://provider.example", "k", path="/v1/x")
    assert reply["fault"] == "not_sent", reply
    out = svc._provider_refused(reply, method="submit_compute_job", endpoint="e", provider="p")
    assert out is not None and report_of(out) is FAILURE
