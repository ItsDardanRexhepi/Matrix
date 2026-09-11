"""D5 / NEW-13 — the LLM-facing action contract must match reality.

This is the D2 of the intent layer.

`runtime/chat/intent_actions.py` is what Trinity is TOLD it can do: for each
action it declares required and optional parameters, and the dispatcher passes
those through untranslated to a real service method. Nothing has ever checked
that the declared parameters are the ones the method actually accepts.

When they disagree, the failure is invisible in review and total at runtime: the
model constructs a perfectly reasonable call from its instructions, the
dispatcher forwards it, and Python raises TypeError on an unexpected keyword.
The action simply never works, and the only symptom is an agent that seems bad
at its job.

This is a wider surface than the route sweep. Routes are called by clients that
get a status code back; the action table is read by a language model that has no
way to discover it was lied to.

The check:
  ACTION (intent_actions) -> ACTION_MAP (dispatcher) -> service.method
and then: is every declared param a real parameter of that method?
"""

from __future__ import annotations

import inspect

import pytest

from runtime.blockchain.services.service_dispatcher import ACTION_MAP
from runtime.chat.intent_actions import INTENT_ACTION_MAP


def _declared_params(guide: dict) -> set[str]:
    out: set[str] = set()
    for key in ("required_params", "optional_params"):
        for p in guide.get(key, []) or []:
            name = p.get("name") if isinstance(p, dict) else p
            if name:
                out.add(name)
    return out


def _resolve_method(service_name: str, method_name: str):
    """Return the unbound method for service.method, or None if unresolvable.

    Mirrors the registry's real mechanism rather than guessing at it: its
    ``_SERVICE_MAP`` is ``{name: (relative_module, ClassName)}`` resolved
    against the services package. An earlier version of this helper assumed a
    class object or a dotted path and therefore resolved NOTHING — reporting
    218 of 219 actions broken, which was the detector failing, not the code.
    A detector that reports everything as broken is as useless as one that
    reports nothing.
    """
    import importlib

    from runtime.blockchain.services.registry import _PACKAGE, _SERVICE_MAP

    entry = _SERVICE_MAP.get(service_name)
    if entry is None:
        return None
    rel_module, cls_name = entry
    try:
        module = importlib.import_module(rel_module, package=_PACKAGE)
        service_cls = getattr(module, cls_name)
    except Exception:
        return None
    return getattr(service_cls, method_name, None)


def _mismatches() -> list[str]:
    """Every action whose declared params the target method cannot accept."""
    problems: list[str] = []

    for action_name, guide in sorted(INTENT_ACTION_MAP.items()):
        if guide.get("unavailable"):
            continue  # honestly declared as not available (NEW-12)

        target = ACTION_MAP.get(action_name)
        if target is None:
            problems.append(
                f"{action_name}: declared to the model but not in ACTION_MAP — "
                "the model can be told to call something the dispatcher cannot route"
            )
            continue

        service_name, method_name = target
        method = _resolve_method(service_name, method_name)
        if method is None:
            problems.append(
                f"{action_name}: -> {service_name}.{method_name} does not resolve"
            )
            continue

        try:
            sig = inspect.signature(method)
        except (TypeError, ValueError):
            continue

        # **kwargs absorbs anything; such a method cannot be mismatched.
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            continue

        accepted = {
            n for n, p in sig.parameters.items()
            if n != "self"
            and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                           inspect.Parameter.KEYWORD_ONLY)
        }
        declared = _declared_params(guide)
        unknown = sorted(declared - accepted)
        if unknown:
            problems.append(
                f"{action_name}: -> {service_name}.{method_name} does not accept "
                f"{unknown} (accepts: {sorted(accepted)})"
            )

        # A required parameter the model is never told about is the mirror
        # failure: the call binds but is missing something mandatory.
        required_by_method = sorted(
            n for n, p in sig.parameters.items()
            if n != "self"
            and p.default is inspect.Parameter.empty
            and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                           inspect.Parameter.KEYWORD_ONLY)
        )
        undeclared = [n for n in required_by_method if n not in declared]
        if undeclared:
            problems.append(
                f"{action_name}: -> {service_name}.{method_name} REQUIRES "
                f"{undeclared}, which the model is never told to supply"
            )

    return problems


def test_report_head_count(capsys):
    """Emit the raw mismatch count. This number is the finding."""
    problems = _mismatches()
    total = len(INTENT_ACTION_MAP)
    with capsys.disabled():
        print(f"\n── NEW-13: {len(problems)} mismatches across {total} declared actions ──")
        for p in problems:
            print(f"  {p}")
        print("──")


# Measured on HEAD at the time this detector was written, BEFORE any fix:
# 297 problems across 173 distinct actions (78% of the 219 declared).
# The ratchet below is what protects the interim — see the two tests.
NEW_13_HEAD_PROBLEMS = 297
NEW_13_HEAD_ACTIONS = 173


def test_mismatch_count_does_not_increase():
    """RATCHET — the real protection while NEW-13 is being worked through.

    The full assertion below is xfailed (173 broken actions is a triage job, not
    a single commit), so on its own it would let NEW breakage hide among the
    known set. This test closes that: the count may fall, never rise. Adding a
    new action whose params do not match its method fails here immediately.

    Lower these constants as fixes land. They only go down.
    """
    problems = _mismatches()
    actions = {p.split(":")[0] for p in problems}
    assert len(problems) <= NEW_13_HEAD_PROBLEMS, (
        f"intent/action mismatches rose to {len(problems)} (was "
        f"{NEW_13_HEAD_PROBLEMS}). A new action declares a contract its target "
        "method does not honour."
    )
    assert len(actions) <= NEW_13_HEAD_ACTIONS, (
        f"broken actions rose to {len(actions)} (was {NEW_13_HEAD_ACTIONS})"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "NEW-13: 173 of 219 declared actions (78%) declare parameters their "
        "target method cannot accept, or omit ones it requires. Every one is an "
        "action the model will construct a call for and Python will reject with "
        "TypeError. Being fixed in triage batches; test_mismatch_count_does_not_"
        "increase ratchets the interim so new breakage cannot hide here."
    ),
)
def test_every_declared_action_matches_its_target_signature():
    """No action may declare parameters its target method cannot accept."""
    problems = _mismatches()
    assert not problems, (
        f"{len(problems)} action(s) declare a contract the target method does not "
        "honour. The model builds calls from these declarations, so each one is "
        "an action that silently cannot work:\n  " + "\n  ".join(problems)
    )
