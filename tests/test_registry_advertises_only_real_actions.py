"""extensions/registry.json must not advertise actions the dispatcher lacks.

NEW-38 blast radius. The registry is served live at GET /extensions/registry
(gateway/server.py) and consumed + UserDefaults-cached by the iOS client
(MTRX/Extensions/ComponentRegistry.swift), so it is a real advertisement
surface — the third one, alongside `runtime/capabilities/catalog.py` and
`runtime/chat/intent_actions.py`.

When an action is removed from ACTION_MAP, all three have to be updated. Four
removals from this engagement had updated only the first two and left the
registry advertising actions the dispatcher answers with
"Unknown action '<name>'":

    contracts: deploy_contract                            (NEW-12)
    privacy:   execute_deletion                           (NEW-38)
               private_transfer                           (NEW-36)
               stealth_address                            (earlier removal)

"Inert means inert on all surfaces" — an advertisement is a surface. This test
is the check that makes the rule enforceable instead of remembered, and it
covers every component rather than the ones anyone thought to look at.

Deliberately NOT asserted here: that every ACTION_MAP action appears in the
registry. The registry is a curated product surface, not a mirror of the
dispatcher — under-advertising is a product choice, while over-advertising is
a lie. Only the lying direction fails.
"""

from __future__ import annotations

import json
from pathlib import Path

from runtime.blockchain.services.service_dispatcher import ACTION_MAP

_REGISTRY = Path(__file__).resolve().parents[1] / "extensions" / "registry.json"


def _components() -> list[dict]:
    data = json.loads(_REGISTRY.read_text())
    components = data["components"] if isinstance(data, dict) else data
    assert components, "registry has no components — the test would pass vacuously"
    return components


def test_every_advertised_action_exists_in_action_map():
    dangling: list[str] = []
    advertised = 0

    for component in _components():
        for action in component.get("gateway_actions", []) or []:
            advertised += 1
            if action not in ACTION_MAP:
                dangling.append(f"{component['id']}: {action!r}")

    # Guard the guard: if the shape of the file changes so nothing is
    # collected, this test must fail rather than silently approve.
    assert advertised > 100, (
        f"only {advertised} advertised actions collected — the registry shape "
        "changed and this check is no longer looking at anything"
    )

    assert not dangling, (
        "extensions/registry.json advertises actions the dispatcher cannot "
        "route (the iOS client caches this file):\n  " + "\n  ".join(dangling)
    )


def test_deletion_is_not_advertised_anywhere_in_the_registry():
    """NEW-38 specifically: no component offers data deletion as executable.

    `request_deletion` is allowed to remain — it is still routable and
    answers "not available" by design. `execute_deletion` must be absent.
    """
    offenders = []
    for component in _components():
        actions = component.get("gateway_actions", []) or []
        if "execute_deletion" in actions:
            offenders.append(component["id"])

    assert not offenders, (
        f"components still advertising execute_deletion: {offenders}"
    )
