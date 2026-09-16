"""The periodic sweep prunes every rate limiter the gateway keys buckets in.

``RateLimiter`` creates a bucket on first touch for whatever key it is handed
and keeps it until ``cleanup()`` removes it. 0771c71 introduced the sweep and
named two of the three limiters; ``rate_limiter_wallet`` — keyed by SIWE
address, where addresses are free to mint and /auth/nonce and /auth/verify are
public — kept a bucket for every address that ever signed in.

The limiters are derived from the server object, not listed, so a fourth
limiter cannot be added and forgotten the same way.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, "tests")

from gateway.server import GatewayServer, RateLimiter  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402


def _limiters(server) -> dict[str, RateLimiter]:
    return {name: v for name, v in vars(server).items() if isinstance(v, RateLimiter)}


async def _one_sweep(server) -> None:
    calls = {"n": 0}

    async def fake_sleep(_seconds):
        calls["n"] += 1
        if calls["n"] > 1:
            raise asyncio.CancelledError
    with patch("gateway.server.asyncio.sleep", fake_sleep):
        await server._cleanup_loop()


async def test_the_sweep_prunes_stale_buckets_in_every_limiter_the_server_holds():
    scratch = tempfile.mkdtemp(prefix="the-matrix-sweep-")
    server = GatewayServer({**SWEEP_CONFIG, "memory_dir": scratch,
                            "database": {"path": f"{scratch}/s.db"}})
    limiters = _limiters(server)
    assert "rate_limiter_wallet" in limiters and len(limiters) >= 3, sorted(limiters)

    stale = time.time() - 3600
    for name, limiter in limiters.items():
        for i in range(50):
            limiter.allow(f"{name}:minted-{i}")
            limiter._buckets[f"{name}:minted-{i}"][1] = stale
        limiter.allow(f"{name}:live")  # touched just now: must survive

    await _one_sweep(server)

    left = {name: sorted(l._buckets) for name, l in limiters.items()}
    for name, keys in left.items():
        assert keys == [f"{name}:live"], (name, len(keys))
