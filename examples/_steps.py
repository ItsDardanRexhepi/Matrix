"""Shared by the numbered examples: dispatch an action and say whether it happened.

ServiceDispatcher.execute answers with an envelope. Its ``status`` is about the
DISPATCH: ``"ok"`` means the action resolved and the service's method returned,
and it says exactly that when the service answered ``{"status": "not_deployed"}``.
Whether the action happened is the envelope's ``call_outcome``: ``"success"``,
``"failure"`` or ``"unknown"`` (runtime/protocols/outcome_truth.py). A step here
counts as done only when the envelope says ``"success"``; an ``"unknown"`` is
reported as not confirmed, with what the service's answer says.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.protocols.outcome_truth import OUTCOME_FIELD, SUCCESS, UNKNOWN

CYAN = "\033[96m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
RED = "\033[91m"; BOLD = "\033[1m"; DIM = "\033[2m"; RESET = "\033[0m"


def step(n, text):  print(f"\n{CYAN}{BOLD}[Step {n}]{RESET} {text}")
def ok(text):       print(f"  {GREEN}+{RESET} {text}")
def warn(text):     print(f"  {YELLOW}!{RESET} {text}")
def fail(text):     print(f"  {RED}x{RESET} {text}")


def reason_of(envelope: dict) -> str:
    """What the envelope says about a call that did not happen."""
    if envelope.get("status") != "ok":
        return str(envelope.get("error") or envelope.get("error_category") or "refused")
    result = envelope.get("result")
    if isinstance(result, dict):
        status = result.get("status")
        detail = (result.get("message") or result.get("error") or result.get("reason")
                  or result.get("disclosure") or "")
        if status or detail:
            return ": ".join(str(x) for x in (status, detail) if x)
    outcome = envelope.get(OUTCOME_FIELD)
    if outcome == UNKNOWN:
        return "the service's answer does not say whether it happened"
    return f"call_outcome {outcome!r}" if outcome else "the answer carries no outcome"


def shown(result: Any, *keys: str) -> Any:
    """The first of *keys* the service's answer carries, or 'not reported'."""
    if isinstance(result, dict):
        for key in keys:
            if result.get(key) not in (None, ""):
                return result[key]
    return "not reported"


def dispatcher_record_note(config: dict) -> str:
    """What happens, under *config*, to the record the service dispatcher
    hands the attestation service for each state-modifying action that
    happened. The attestation service resolves its schema before it queues
    anything, and refuses the record when ``blockchain.eas_schema`` is not a
    well-formed bytes32 UID (the shipped example config's placeholder is not
    one); the dispatcher logs that refusal. The batch size is the service's."""
    import inspect

    from runtime.blockchain.services.attestation.service import AttestationService

    batch = inspect.signature(AttestationService.__init__).parameters["batch_size"].default
    try:
        AttestationService(config)._resolve_schema("")
    except ValueError:
        return ("blockchain.eas_schema is not a well-formed bytes32 UID in this config, so the "
                "attestation service refused the service dispatcher's record of each action "
                "that happened; the dispatcher logged each refusal, and nothing was queued.")
    return ("When a state-modifying action completes, the service dispatcher queues an EAS "
            f"attestation of it; the queue is written to the chain once {batch} have gathered in "
            "the same process, and what is queued is lost if the process exits first.")


class Steps:
    """Runs an example's actions and keeps the record of which happened."""

    def __init__(self, dispatcher, *, dry_run: bool = False):
        self._dispatcher = dispatcher
        self._dry_run = dry_run
        # (label, "done" | "not done" | "not confirmed" | "skipped", why)
        self.record: list[tuple[str, str, str]] = []

    async def run(self, label: str, action: str, params: dict, needs=()) -> Any:
        """Dispatch *action*; return the service's answer if it happened, else None."""
        missing = [name for name, value in needs if not value]
        if missing:
            why = f"no {', '.join(missing)} from an earlier step"
            warn(f"Skipped: {why}")
            self.record.append((label, "skipped", why))
            return None
        if self._dry_run:
            warn(f"[dry-run] would call {action}({', '.join(sorted(params))})")
            self.record.append((label, "skipped", "dry run"))
            return None
        try:
            envelope = json.loads(await self._dispatcher.execute(action=action, params=params))
        except Exception as exc:  # the dispatcher itself failed; say so, do not guess
            warn(f"Not done: {exc}")
            self.record.append((label, "not done", str(exc)))
            return None
        if envelope.get("status") == "ok" and envelope.get(OUTCOME_FIELD) == SUCCESS:
            self.record.append((label, "done", ""))
            return envelope.get("result")
        why = reason_of(envelope)
        state = ("not confirmed" if envelope.get("status") == "ok"
                 and envelope.get(OUTCOME_FIELD) == UNKNOWN else "not done")
        warn(f"{state.capitalize()}: {why}")
        self.record.append((label, state, why))
        return None

    def summary(self, title: str) -> None:
        happened = [r for r in self.record if r[1] == "done"]
        print(f"\n{BOLD}{'=' * 60}\n  {title}: {len(happened)} of {len(self.record)} steps happened"
              f"\n{'=' * 60}{RESET}")
        for label, state, why in self.record:
            (ok if state == "done" else warn)(f"{label}: {state}" + (f" ({why})" if why else ""))
