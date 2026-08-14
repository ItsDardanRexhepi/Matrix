"""21-I — `wait_for_receipt` was an `async def` that never awaited.

`w3.eth.wait_for_transaction_receipt` is SYNCHRONOUS: it polls and sleeps. The
method was declared `async` and called it directly, so awaiting it BLOCKED THE
WHOLE EVENT LOOP for up to `timeout` seconds (default 120).

THIS ENGAGEMENT INTRODUCED THE STALL. Enumerated: `wait_for_receipt` had ZERO
callers until 19-C and 21-C added the only two — both ours, both added to stop
a service claiming an outcome it had not confirmed. The mechanism was real and
orphaned; we called it, correctly, and activated a latent defect inside it.

§AG's after-form: a fix that reaches for an unused facility inherits whatever
is wrong with it, and the facility's own history cannot warn you — it had no
callers precisely because nobody had exercised it.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from runtime.blockchain.web3_manager import Web3Manager


class _Eth:
    def __init__(self, delay):
        self.delay = delay
        self.calls = []

    def wait_for_transaction_receipt(self, tx_hash, timeout=120):
        self.calls.append((tx_hash, timeout))
        time.sleep(self.delay)          # what web3 actually does: a sync poll
        return type("R", (), {"status": 1, "blockNumber": 7})()


def _manager(delay=0.4):
    w = Web3Manager.__new__(Web3Manager)
    w.available = True
    w.w3 = type("W3", (), {"eth": _Eth(delay)})()
    return w


@pytest.mark.asyncio
async def test_the_event_loop_keeps_running_during_the_receipt_wait():
    """Measures RESPONSIVENESS, not the implementation. A test asserting
    `asyncio.to_thread` appears in the source would pass for a rewrite that
    reintroduced the stall a different way."""
    w = _manager(delay=0.4)
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    hb = asyncio.create_task(heartbeat())
    try:
        receipt = await w.wait_for_receipt("0xabc", timeout=5)
    finally:
        hb.cancel()

    assert receipt.status == 1
    assert ticks > 5, (
        f"only {ticks} event-loop ticks during a 0.4s receipt wait — the loop "
        f"was blocked, which is the defect this test exists for"
    )


@pytest.mark.asyncio
async def test_the_timeout_is_still_passed_through():
    """§AQ class 3: fixing the blocking must not change what the call does."""
    w = _manager(delay=0.01)
    await w.wait_for_receipt("0xdead", timeout=42)
    assert w.w3.eth.calls == [("0xdead", 42)]


@pytest.mark.asyncio
async def test_an_unavailable_manager_still_raises():
    w = Web3Manager.__new__(Web3Manager)
    w.available = False
    w.w3 = None
    with pytest.raises(RuntimeError, match="not available"):
        await w.wait_for_receipt("0xabc")


@pytest.mark.asyncio
async def test_concurrent_receipt_waits_overlap():
    """The consequence in production terms: two value-moving calls waiting on
    receipts must not serialise behind each other."""
    w = _manager(delay=0.3)
    t = time.monotonic()
    await asyncio.gather(*(w.wait_for_receipt(f"0x{i}", timeout=5) for i in range(3)))
    elapsed = time.monotonic() - t
    assert elapsed < 0.75, (
        f"three 0.3s waits took {elapsed:.2f}s — they serialised"
    )
