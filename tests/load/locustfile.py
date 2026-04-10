"""
tests/load/locustfile.py
========================

Locust load scenarios for the 0pnMatrx gateway. Targets the two
cross-cutting endpoints the MTRX iOS ``MTRXPackager`` hammers hardest
in a real session:

* ``POST /api/v1/batch`` — multi-service dispatch; the packager coalesces
  everything it can into these.
* ``GET  /api/v1/events/stream`` — the live SSE feed each active device
  holds open.

Plus the three one-shot endpoints every iOS boot hits
(``/bridge/v1/session/create``, ``/bridge/v1/dashboard``,
``/api/v1/dashboard/{address}``) so we exercise the full mobile warm-up
path under load.

Usage::

    # Normal interactive run (web UI on :8089)
    locust -f tests/load/locustfile.py --host http://localhost:8000

    # Headless 50-user soak for 5 minutes
    locust -f tests/load/locustfile.py --headless \
        --users 50 --spawn-rate 5 --run-time 5m \
        --host http://localhost:8000

Environment variables:

* ``MTRX_LOAD_API_KEY`` — Bearer token sent on every request. Defaults
  to an empty string for gateways running with auth disabled.
* ``MTRX_LOAD_ADDRESS`` — Ethereum-style address used for dashboard
  lookups. Defaults to a throwaway stub.

The batch payloads only hit read-only endpoints (``dashboard``,
``oracle`` price feeds, ``attestation`` verify) so a load run doesn't
litter real state.
"""

from __future__ import annotations

import json
import os
import random
import uuid
from typing import Any, Dict, List

from locust import HttpUser, between, events, task


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_KEY = os.environ.get("MTRX_LOAD_API_KEY", "")
ADDRESS = os.environ.get(
    "MTRX_LOAD_ADDRESS",
    "0x0000000000000000000000000000000000000001",
)

READ_ONLY_BATCH_TEMPLATES: List[Dict[str, Any]] = [
    {
        "method": "GET",
        "path": f"/api/v1/dashboard/{ADDRESS}",
        "body": None,
    },
    {
        "method": "GET",
        "path": "/api/v1/oracle/price/ETH-USD",
        "body": None,
    },
    {
        "method": "GET",
        "path": "/api/v1/oracle/price/BTC-USD",
        "body": None,
    },
    {
        "method": "GET",
        "path": "/api/v1/attestation/verify/stub-uid",
        "body": None,
    },
]


def _auth_headers() -> Dict[str, str]:
    if not API_KEY:
        return {}
    return {"Authorization": f"Bearer {API_KEY}"}


def _make_batch(size: int) -> Dict[str, Any]:
    """Return a batch payload with *size* read-only sub-requests."""

    items = []
    for _ in range(size):
        template = random.choice(READ_ONLY_BATCH_TEMPLATES)
        items.append({
            "id": uuid.uuid4().hex[:8],
            "method": template["method"],
            "path": template["path"],
            "body": template["body"],
        })
    return {"requests": items, "sequential": False, "abort_on_failure": False}


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class MobilePackagerUser(HttpUser):
    """Simulates one MTRX iOS device driving the Packager.

    Each user keeps a session alive, occasionally reloads the
    dashboard, and periodically fires 5-item batch calls the way the
    Packager does when the user navigates between component screens.
    """

    wait_time = between(1.0, 3.0)

    def on_start(self) -> None:
        self.session_id = ""
        resp = self.client.post(
            "/bridge/v1/session/create",
            json={"device_id": f"load-{uuid.uuid4().hex[:6]}", "app_version": "1.0.0"},
            headers=_auth_headers(),
            name="POST /bridge/v1/session/create",
        )
        if resp.status_code == 200:
            try:
                payload = resp.json()
                self.session_id = (
                    payload.get("data", {}).get("session_id", "")
                    if isinstance(payload, dict)
                    else ""
                )
            except json.JSONDecodeError:
                self.session_id = ""

    @task(6)
    def batch_read(self) -> None:
        """Biggest share of traffic — the iOS home screen refresh."""

        body = _make_batch(size=5)
        self.client.post(
            "/api/v1/batch",
            json=body,
            headers=_auth_headers(),
            name="POST /api/v1/batch (5 items)",
        )

    @task(2)
    def batch_read_large(self) -> None:
        """Component deep-link; the packager sends one large batch."""

        body = _make_batch(size=15)
        self.client.post(
            "/api/v1/batch",
            json=body,
            headers=_auth_headers(),
            name="POST /api/v1/batch (15 items)",
        )

    @task(3)
    def dashboard_direct(self) -> None:
        self.client.get(
            f"/api/v1/dashboard/{ADDRESS}",
            headers=_auth_headers(),
            name="GET /api/v1/dashboard/{address}",
        )

    @task(1)
    def oracle_price(self) -> None:
        self.client.get(
            "/api/v1/oracle/price/ETH-USD",
            headers=_auth_headers(),
            name="GET /api/v1/oracle/price/{pair}",
        )

    @task(2)
    def bridge_dashboard(self) -> None:
        if not self.session_id:
            return
        self.client.get(
            "/bridge/v1/dashboard",
            headers={**_auth_headers(), "X-MTRX-Session": self.session_id},
            name="GET /bridge/v1/dashboard",
        )


class SSESubscriberUser(HttpUser):
    """Simulates a device that keeps the live SSE stream open.

    Locust's HttpUser is request/response oriented, so we use a
    non-streaming GET with a short per-request timeout — the goal here
    is to exercise the reconnect + replay path, not to hold a real
    long-lived connection. For genuine SSE soak tests run the
    `sse_soak.py` helper under `locust --class-picker`.
    """

    wait_time = between(10.0, 30.0)

    @task
    def reconnect_cycle(self) -> None:
        headers = _auth_headers()
        # Include a Last-Event-ID on half the reconnects to exercise
        # the replay buffer path.
        if random.random() < 0.5:
            headers["Last-Event-ID"] = uuid.uuid4().hex[:12]
        with self.client.get(
            "/api/v1/events/stream?components=3,13",
            headers=headers,
            stream=True,
            catch_response=True,
            timeout=2.0,
            name="GET /api/v1/events/stream (reconnect)",
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"bad status {resp.status_code}")
                return
            try:
                # Read the stream.opened hello frame (up to ~1 KB) then
                # drop the connection — the gateway side should clean
                # up quickly, which is what we're measuring.
                chunk = next(resp.iter_content(chunk_size=1024), b"")
                if b"event: stream.opened" not in chunk:
                    resp.failure("missing stream.opened hello frame")
                    return
                resp.success()
            except Exception as exc:  # pragma: no cover
                resp.failure(f"stream read error: {exc}")


# ---------------------------------------------------------------------------
# Hooks — print a load summary at the end of headless runs
# ---------------------------------------------------------------------------


@events.quitting.add_listener
def _log_summary(environment, **_kwargs) -> None:  # pragma: no cover
    stats = environment.stats
    print("\n=== Load summary ===")
    for name in (
        "POST /api/v1/batch (5 items)",
        "POST /api/v1/batch (15 items)",
        "GET /api/v1/dashboard/{address}",
        "GET /api/v1/events/stream (reconnect)",
    ):
        entry = stats.get(name, "POST" if name.startswith("POST") else "GET")
        if entry is None or entry.num_requests == 0:
            continue
        print(
            f"  {name}: n={entry.num_requests} "
            f"p50={entry.get_response_time_percentile(0.5):.0f}ms "
            f"p95={entry.get_response_time_percentile(0.95):.0f}ms "
            f"fail={entry.num_failures}"
        )
