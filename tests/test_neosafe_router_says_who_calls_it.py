"""What the texts say about NeoSafeRouter is what it does and who calls it.

`NeoSafeRouter.route_revenue`, with no chain configured, appended an entry to
the router's in-memory ledger and answered "Revenue routing queued — will
execute when blockchain is configured". Nothing executes that entry later: no
code reads the ledger to send it, and it is lost on restart. The module's own
docstring says so; the answer said the opposite.

The same texts named the callers wrong. The module docstring said `route_fee`
and `route_revenue` "are reached only from examples/07_revenue_to_neosafe.py",
examples/README.md that they "have no caller outside" that example, and the
example that "nothing outside this example calls NeoSafeRouter.route_fee or
route_revenue". The example calls `route_fee` and never `route_revenue`, which
nothing outside the tests calls (ServiceDispatcher._get_neosafe builds a router
and has no caller).

The callers are measured here from the tracked source, not typed in. A
sentence that names both methods beside the example is the grouped claim the
texts made, so each text states the two callers in separate sentences.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = "examples/07_revenue_to_neosafe.py"
TEXTS = ["runtime/blockchain/services/neosafe.py", "examples/README.md", EXAMPLE]


def _callers(method: str) -> set[str]:
    out = subprocess.check_output(["git", "ls-files", "*.py"], cwd=ROOT, text=True)
    found = set()
    for rel in out.splitlines():
        if rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        if any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") == method
               for n in ast.walk(tree)):
            found.add(rel)
    return found


def _sentences(text: str) -> list[str]:
    # A blank line, a list item, a heading or a table row starts a new block. A
    # period inside an identifier or a path (`NeoSafeRouter.route_fee`,
    # `neosafe.py`) is not followed by whitespace, so it does not end a sentence.
    blocks = re.split(r"\n\s*\n|\n(?=\s*(?:[-*#|>]|\d+\.)\s)", text)
    return [re.sub(r"\s+", " ", s) for b in blocks for s in re.split(r"(?<=[.!?])\s+", b)]


def _grouped_caller_claims(text: str) -> list[str]:
    return [s for s in _sentences(text)
            if "route_fee" in s and "route_revenue" in s
            and re.search(r"examples/07|this example", s)
            and re.search(r"\bcall|\breach", s)]


def test_the_caller_measurement_sees_the_example():
    assert _callers("route_fee") >= {EXAMPLE}
    assert _grouped_caller_claims(
        "No service calls it: `route_fee` and `route_revenue` are reached only from\n"
        "examples/07_revenue_to_neosafe.py. The platform contracts pay fees.")
    assert not _grouped_caller_claims(
        "`route_fee` is called only by examples/07_revenue_to_neosafe.py. Nothing "
        "outside the tests calls `route_revenue`.")


def test_the_router_has_the_callers_the_texts_name():
    assert _callers("route_fee") == {EXAMPLE}
    assert _callers("route_revenue") == set()
    problems = []
    for rel in TEXTS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        problems += [f"{rel}: {s!r}" for s in _grouped_caller_claims(text)]
        flat = re.sub(r"\s+", " ", text)
        if not re.search(r"(?:[Nn]othing outside the tests calls|no caller outside the tests)"
                         r"[^.]{0,40}route_revenue|route_revenue`*[^.]{0,60}"
                         r"(?:nothing|no caller) outside the tests", flat):
            problems.append(f"{rel}: does not say that nothing outside the tests calls "
                            "route_revenue")
    assert not problems, "\n".join(problems)


@pytest.mark.asyncio
async def test_an_unsent_revenue_routing_does_not_say_it_will_execute():
    from runtime.blockchain.services.neosafe import NeoSafeRouter

    router = NeoSafeRouter({"blockchain": {"rpc_url": ""}})
    assert not router._web3.available
    result = await router.route_revenue(amount_eth=0.01, source_action="probe")
    assert result["status"] == "recorded_unqueued", result
    assert result["sent"] is False, result
    message = result["message"].lower()
    assert "will execute" not in message and "not sent" in message, result
    assert "nothing sends" in message, result
    assert router._ledger[-1]["sent"] is False and "queued" not in router._ledger[-1]
