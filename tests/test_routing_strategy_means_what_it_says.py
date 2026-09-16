"""The router names four strategies. Three of the names did not describe the code.

`runtime/models/router.py` and `runtime/models/task_classifier.py` both open by
promising that "critical (irreversible / high-value) tasks always route to the
best available model regardless of cost", and the class docstring lists
``always_best`` and ``always_fast`` as strategies that always do a thing.

What the code did:

  * ``always_best`` returned an EMPTY kwargs dict — no override at all, so every
    provider used whatever model its own config named. The one strategy whose
    entire name is "best" was the only one that never asked for the best model.
  * ``always_fast`` overwrote the tier the classifier had just chosen, CRITICAL
    included. A transfer or a deploy — the two words at the top of the critical
    keyword set — went to the fast model, which is the exact trade the
    "regardless of cost" clause exists to forbid.
  * ``always_fast`` was also applied INSIDE the classification `try`, after an
    early `return extra`. A classifier that raised skipped the always_fast
    block entirely, so the strategy silently stopped applying on the path where
    the router already knew least about the turn.

`_is_unreachable` decides whether a failure is worth retrying, and answered
True for every `OSError` subclass. A connection RESET and an SSL failure are
OSErrors from a host that was reached and answered — retrying those is the
whole point of having retries, and they were being skipped.

These checks are about behaviour the caller can see: which model name the
serving provider is handed, and whether a second attempt is made.
"""

from __future__ import annotations

import socket
import ssl

import pytest

from runtime.models.model_interface import ModelResponse
from runtime.models.router import ModelRouter, _is_unreachable

TIERS = {"fast": "tier-fast", "balanced": "tier-balanced", "best": "tier-best"}


class _Recorder:
    """A provider that records the model_override it is handed."""

    def __init__(self, fail_times: int = 0, exc: Exception | None = None):
        self.overrides: list[str] = []
        self.attempts = 0
        self._fail_times = fail_times
        self._exc = exc or RuntimeError("boom")

    async def complete(self, messages, tools=None, **kwargs):
        self.attempts += 1
        self.overrides.append(kwargs.get("model_override", ""))
        if self.attempts <= self._fail_times:
            raise self._exc
        return ModelResponse(content="ok", provider="stub")

    async def health_check(self):
        return True


def _router(strategy: str) -> tuple[ModelRouter, _Recorder]:
    router = ModelRouter({"provider": "stub", "routing_strategy": strategy})
    rec = _Recorder()
    router.routing_strategy = strategy
    router.providers_config = {"anthropic": {"models": dict(TIERS)}}
    router.providers = {"stub": rec}
    router.primary_name = "stub"
    return router, rec


def _msgs(text: str):
    # classify_task reads .role/.content or the dict keys; dicts are the shape
    # the gateway already hands the router.
    return [{"role": "user", "content": text}]


CRITICAL = "please transfer 5000 USDC to 0xabc and deploy the escrow contract"
CHITCHAT = "hi"


# ── always_best ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_always_best_asks_for_the_best_model():
    router, rec = _router("always_best")
    await router.complete(_msgs(CHITCHAT), agent_name="t")
    assert rec.overrides == ["tier-best"], (
        "the strategy named always_best sent no tier at all: "
        f"{rec.overrides}")


# ── always_fast, and the promise that outranks it ───────────────────────────

@pytest.mark.asyncio
async def test_always_fast_uses_the_fast_model_for_ordinary_work():
    router, rec = _router("always_fast")
    await router.complete(_msgs(CHITCHAT), agent_name="t")
    assert rec.overrides == ["tier-fast"]


@pytest.mark.asyncio
async def test_always_fast_does_not_downgrade_a_critical_task():
    # "critical tasks always route to the best model regardless of cost" is a
    # promise about irreversible actions, and a cost strategy does not outrank
    # it. A transfer + a deploy in one turn is as critical as this gets.
    from runtime.models.task_classifier import classify_task
    assert classify_task(_msgs(CRITICAL), None).value == "critical"

    router, rec = _router("always_fast")
    await router.complete(_msgs(CRITICAL), agent_name="t")
    assert rec.overrides == ["tier-best"], (
        f"a critical turn was routed to {rec.overrides} under always_fast")


@pytest.mark.asyncio
async def test_always_fast_still_applies_when_classification_fails(monkeypatch):
    # The strategy is a standing instruction, not a consequence of
    # classification. It used to sit after an early return on this path.
    import runtime.models.task_classifier as tc

    def _boom(*a, **k):
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(tc, "classify_task", _boom)
    router, rec = _router("always_fast")
    await router.complete(_msgs(CHITCHAT), agent_name="t")
    assert rec.overrides == ["tier-fast"], (
        f"always_fast stopped applying when the classifier raised: {rec.overrides}")


# ── retry classification ────────────────────────────────────────────────────

def test_a_refused_connection_is_unreachable():
    assert _is_unreachable(ConnectionRefusedError(61, "Connection refused")) is True


def test_dns_failure_is_unreachable():
    assert _is_unreachable(socket.gaierror(8, "nodename nor servname provided")) is True


def test_a_timeout_is_not_unreachable():
    assert _is_unreachable(TimeoutError("timed out")) is False


@pytest.mark.parametrize("exc", [
    ConnectionResetError(54, "Connection reset by peer"),
    BrokenPipeError(32, "Broken pipe"),
    ssl.SSLError("decryption failed or bad record mac"),
])
def test_a_failure_mid_conversation_is_retryable(exc):
    # The host was reached and answered; the connection broke afterwards. That
    # is the transient failure retries exist for, and every one of these is an
    # OSError subclass that the old `isinstance(exc, OSError)` swallowed.
    assert _is_unreachable(exc) is False


@pytest.mark.asyncio
async def test_a_reset_is_actually_retried_by_the_router():
    # §EB: the classifier above is a function; this is the router acting on it.
    router, _ = _router("always_best")
    rec = _Recorder(fail_times=1, exc=ConnectionResetError(54, "reset by peer"))
    router.providers = {"stub": rec}
    await router.complete(_msgs(CHITCHAT), agent_name="t")
    assert rec.attempts == 2, (
        f"a reset mid-conversation was not retried (attempts={rec.attempts})")


@pytest.mark.asyncio
async def test_a_refusal_is_still_not_retried():
    # The RUN-5 guarantee must survive the narrowing: an unreachable host is
    # tried once, not three times.
    router, _ = _router("always_best")
    rec = _Recorder(fail_times=99, exc=ConnectionRefusedError(61, "refused"))
    router.providers = {"stub": rec}
    with pytest.raises(RuntimeError):
        await router.complete(_msgs(CHITCHAT), agent_name="t")
    assert rec.attempts == 1, f"a refused host was retried {rec.attempts} times"
