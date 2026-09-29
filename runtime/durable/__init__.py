"""Durable execution — the LIFECYCLE of a state-modifying action, and only that.

Four modules over four tables of the platform database (migration 10):

* ``journal`` — the run journal (``workflow_runs``, ``workflow_steps``): a run
  opened at dispatch, its steps, and its end in a terminal state;
* ``outbox`` — the transactional outbox (``outbox``) and the ONE loop that
  drains it, with retries and backoff: it replaces the attestation interval
  nothing ever started and the fire-and-forget feed publish;
* ``keys`` — the idempotency store (``idempotency_keys``): a replayed
  ``Idempotency-Key`` gets the first answer and runs nothing;
* ``wiring`` — the mode (``engines.durable.mode``: off | shadow | on, off by
  default), the canary, and the engine the service dispatcher consults.

The authority held here is lifecycle authority, in mode on, for the canary's
actions: when a run is recorded, who delivers its attestation and feed entry,
and what a replayed key is answered. No other. Whether an action is allowed is
decided by a gate before any of this runs; what its outcome was is not decided
here at all. Nothing here ever runs an action twice.
"""

from runtime.durable.wiring import (  # noqa: F401
    CANARY, MODES, DurableEngine, build_engine, caller_scope, current, durable_mode, install,
    keyed,
)
