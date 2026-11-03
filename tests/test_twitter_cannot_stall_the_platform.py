"""`TwitterClient` says its methods "never crash the platform". Two ways they could.

The module opens with "All methods are fault-tolerant — they never crash the
platform even if credentials are missing or API calls fail." Every method does
catch its exceptions, so the crash half was nearly true. What was missing is
the two ways a third-party integration actually takes a platform down.

  1. `__init__` read `config.get("social", {}).get("twitter", {})`. A config
     with `"social": null` makes the first `.get` return None and the second
     one an AttributeError — raised from a constructor, outside every one of
     the try blocks the promise rests on.

  2. The API calls are synchronous `requests` calls with no timeout, made from
     inside `async def`. `session.post(...)` does not yield to the event loop,
     so an unresponsive api.twitter.com does not fail the tweet — it freezes
     every coroutine in the process, for as long as the socket stays open.
     Catching the exception is no help when there is no exception, only a wait.

"Cannot take the platform down" is a claim about the event loop as much as
about exceptions, so these checks hold the loop to it: while a tweet is in
flight, other work must still run.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from runtime.social.twitter import TwitterClient


def _client(**over):
    c = TwitterClient({})
    c.api_key = c.api_secret = c.access_token = c.access_secret = "x"  # noqa: S105
    c.available = True
    for k, v in over.items():
        setattr(c, k, v)
    return c


class _HangingSession:
    """A server that accepted the connection and then said nothing."""

    def __init__(self, seconds=0.6):
        self.seconds = seconds
        self.calls = 0

    def _hang(self, *a, **kw):
        self.calls += 1
        time.sleep(self.seconds)  # blocking on purpose — this is requests
        raise AssertionError("unreachable in these tests")

    post = delete = get = _hang


# ── construction ────────────────────────────────────────────────────────────

def test_a_null_social_block_does_not_raise_from_the_constructor():
    assert TwitterClient({"social": None}).available is False


def test_a_non_mapping_twitter_block_does_not_raise():
    assert TwitterClient({"social": {"twitter": "yes please"}}).available is False


def test_a_configured_client_is_still_available():
    # The guard must not turn into "never available".
    c = TwitterClient({"social": {"twitter": {
        "api_key": "k", "api_secret": "s",
        "access_token": "t", "access_secret": "ts"}}})
    assert c.available is True


# ── the event loop ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("call", [
    lambda c: c.post_tweet("hello"),
    lambda c: c.delete_tweet("1"),
    lambda c: c.get_me(),
])
async def test_a_hanging_api_does_not_freeze_the_event_loop(call):
    session = _HangingSession()
    client = _client(_session=session)

    async def heartbeat() -> float:
        # Nominally 0.05s of sleeping. Counting ticks proves nothing — they all
        # arrive eventually. What a blocked loop costs is TIME, so time it.
        start = time.monotonic()
        for _ in range(5):
            await asyncio.sleep(0.01)
        return time.monotonic() - start

    task = asyncio.ensure_future(call(client))
    elapsed = await heartbeat()
    assert elapsed < 0.3, (
        f"other coroutines were starved for {elapsed:.2f}s while a tweet was "
        "in flight — a blocking requests call inside async def takes the whole "
        "event loop with it")
    task.cancel()
    try:
        await task
    except BaseException:
        pass


@pytest.mark.asyncio
async def test_a_hanging_api_eventually_answers_rather_than_waiting_forever():
    # Not blocking the loop is not enough on its own: a call with no timeout
    # leaks a thread and a socket per attempt. The request must be bounded.
    class _Timeout:
        def __init__(self):
            self.timeouts = []

        def _call(self, *a, **kw):
            self.timeouts.append(kw.get("timeout"))
            raise TimeoutError("read timed out")

        post = delete = get = _call

    session = _Timeout()
    result = await _client(_session=session).post_tweet("hello")
    assert result["status"] == "error"
    assert session.timeouts and session.timeouts[0], (
        f"the request carried no timeout: {session.timeouts}")


@pytest.mark.asyncio
async def test_an_unconfigured_client_still_answers_not_configured():
    assert (await TwitterClient({}).post_tweet("x"))["status"] == "not_configured"
