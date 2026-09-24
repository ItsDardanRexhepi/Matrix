"""Durable Execution — the LIFECYCLE of a state-modifying action, and only that.

Four modules over four tables of the platform database (migration 10):

* ``journal`` — the run journal (``workflow_runs``, ``workflow_steps``): one
  run per journaled action, START → RUNNING → COMPLETE | FAIL, or ABORT, written
  before the effect call begins and after it answers;
* ``outbox`` — the transactional outbox (``outbox``) and the one loop that
  drains it, replacing the attestation batch timer nothing ever started and the
  fire-and-forget feed publish;
* ``keys`` — the idempotency store (``idempotency_keys``): a replayed
  ``Idempotency-Key`` gets the first answer and runs nothing;
* ``wiring`` — the mode (``engines.durable.mode``: off | shadow | on, off by
  default), the canary, and the engine the call sites consult.

The authority it holds is lifecycle authority, in mode on, for the actions in
its canary: when a run starts, what is recorded about it, who delivers its
attestation and feed entry, and what a replayed key answers. It holds no other.
Whether an action is allowed is decided by the gate before any of this runs;
what an action's outcome was is not decided here at all — a run's state says
whether its call began and whether it answered, never whether the world
changed. Nothing here ever runs an action twice.
"""

from runtime.durable.wiring import (  # noqa: F401
    CANARIES, MODES, DurableEngine, build_engine, current, durable_canary, durable_mode,
    install,
)
