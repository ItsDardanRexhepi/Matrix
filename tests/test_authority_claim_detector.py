"""D11 — the AUTHORITY-CLAIM detector. A method that says a decision was made,
and keeps no record that would make it so.

WHY A NEW DETECTOR AND NOT AN EXTENSION OF D7 — the measurement reversed the
plan, so it is recorded here rather than in a commit message.

Domain 11 found four fabrications that write NOTHING: `treasury_transfer`,
`approve_multisig`, `snapshot_vote`, `migrate_members`. D6 cannot see any of
them, and the reason is structural rather than a narrow clause: D6's shape has
"records its lie into a store" as a PREMISE. Widening its write clause from
assignments to calls admits `queue_timelock` and leaves the other three exactly
as invisible.

The obvious move was to extend D7, which already detects on a claims axis. The
measurement said no:

    approve_multisig   status='approved'     in DELIVERY_VOCABULARY? NO
    snapshot_vote      status='cast'         in DELIVERY_VOCABULARY? NO
    migrate_members    (count key)           in DELIVERY_VOCABULARY? NO
    treasury_transfer  status='transferred'  in DELIVERY_VOCABULARY? YES
                                             — exempted by its own gate

D7's vocabulary is ten words and every one is about VALUE MOVING: sent, paid,
settled, delivered, transferred, bridged, disbursed, remitted, completed,
bridging. Three of the four never reach D7's first clause at all, and they
should not: "approved" and "cast" are not delivery words. Only
`treasury_transfer` gets far enough for D7's whitelist to matter, and that one
IS a genuine D7 gap — it belongs there, not here.

So the two detectors sit on different axes, and conflating them would produce a
control that cannot be reasoned about:

    D7  — a DELIVERY claim: value moved.
    D11 — an AUTHORITY claim: a decision was made, a permission granted, an
          instruction accepted.

Both can be fabricated. Both need detecting. Merging them would give D7 a name
that overstates its scope, which is the defect its own docstring warns about
and the reason D6 was renamed.

THE CLAUSES. A method is flagged when all four hold:

    1. it returns a hardcoded ``"status": "<authority word>"``;
    2. it mutates NO service state — so nothing it wrote could make the claim
       true (alias-aware, via tests/state_mutation.py);
    3. it contains no registered refusal primitive and no `is_placeholder` —
       it neither refuses honestly nor gates;
    4. it carries no RECORDED_UNSETTLED-style disclosure.

Clause 2 is the axis that makes this detector worth having. D6 asks what a
method LACKS (an await). D7 asks what it CLAIMS (delivery). D11 asks whether
anything it did could POSSIBLY substantiate the claim it makes.

KNOWN MISS, MEASURED AND DELIBERATE. `ConversionWizard.migrate_members` reports
``"migrated": N`` as a COUNT KEY rather than a status literal, so clause 1 does
not reach it. Broadening clause 1 to authority-named count keys was measured:
it gains that one true positive and at least four false ones — `"approved"` on
`ComplianceScaffold.check_compliance`, `"granted"` on
`RightsManagement.check_rights`, `.get_all_rights` and `NFTService.mint`, all
of which are record FIELDS rather than claims. Worse, it also fires on
`PrivacyService.request_deletion` and `.execute_pending_deletion`, which return
honest `"error"/"not_implemented"` — methods a previous domain already REPAIRED.
A detector that fires on correct fixes creates pressure to revert them, which is
the `process_sale` failure mode. One true positive against four-plus false ones
is not a trade worth making; `migrate_members` is carried in the domain-11
findings instead.
"""

from __future__ import annotations

import ast
import pathlib

from tests import refusal_primitives
from tests.state_mutation import mutates_service_state

ROOT = pathlib.Path(__file__).resolve().parent.parent / "runtime/blockchain"

#: Status literals asserting that a DECISION was made — distinct from D7's
#: vocabulary, which asserts that VALUE MOVED.
AUTHORITY_VOCABULARY = frozenset({
    "approved", "cast", "queued", "migrated", "ratified",
    "executed", "authorized", "accepted",
})

#: The honest idiom. Present means the method already discloses.
_DISCLOSES = ("value_moved", "disclosure", "RECORDED_UNSETTLED", "settled")


def _authority_claims(fn: ast.AST) -> set[str]:
    """Hardcoded ``"status": "<authority word>"`` literals in the body."""
    found: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant) and key.value == "status"
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and value.value in AUTHORITY_VOCABULARY
            ):
                found.add(value.value)
    return found


def find_unbacked_authority_claims() -> set[str]:
    """Every method claiming an authoritative act it recorded nowhere."""
    found: set[str] = set()
    for path in sorted(ROOT.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        rel = str(path.relative_to(ROOT))
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            for fn in cls.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if fn.name.startswith("_"):
                    continue
                if not _authority_claims(fn):
                    continue
                body = ast.unparse(fn)
                # honest refusal or a deployment gate -> not this detector's class
                if refusal_primitives.mentions_refusal(body) or "is_placeholder" in body:
                    continue
                if any(d in body for d in _DISCLOSES):
                    continue
                if mutates_service_state(fn):
                    continue
                found.add(f"{rel}::{cls.name}.{fn.name}")
    return found


# ── The frozen inventory (measured 2026-08-12; ratchet: may only shrink) ──
#
# 2 at introduction. BOTH ADJUDICATED INDIVIDUALLY before being listed — raw
# detector output has never entered a ratchet in this engagement, and the
# NFTService.process_sale rejection under NEW-99 is why.
#
#   GovernanceService.approve_multisig — CATEGORY 4, reachability re-derived.
#     Mints msa_<uuid>, returns "approved", and touches no store: driven, every
#     dict and list on the service is byte-identical before and after. It never
#     checks the signer is among the multisig's signers, never appends to an
#     approvals list, never reads self._proposals. LIVE: ACTION_MAP
#     "multisig_approve", in _STATE_MODIFYING_ACTIONS, catalog available=True,
#     so it is reachable through POST /api/v1/capabilities/{id}/invoke. The
#     gateway route is an honest 501 (NEW-89) — but a route was never the only
#     door, which is what treasury_transfer taught.
#
#   GovernanceService.snapshot_vote — CATEGORY 4, reachability re-derived.
#     Mints sv_<uuid>, returns "cast", touches no store. LIVE by the same three
#     surfaces. A vote reported as cast that is recorded nowhere and can be
#     counted by nothing.
#
# NOT LISTED, and each for a stated reason:
#   treasury_transfer — belongs to D7 (delivery vocabulary); its own gate
#     exempts it there, which is a genuine D7 whitelist gap, not a D11 case.
#   migrate_members  — count-key form, see the module docstring's KNOWN MISS.
#   queue_timelock   — it DOES write a store, so it is D6's case (call-form),
#     not this detector's.

KNOWN_UNBACKED_AUTHORITY = {
    "services/governance/service.py::GovernanceService.approve_multisig",
    "services/governance/service.py::GovernanceService.snapshot_vote",
}


def test_no_new_unbacked_authority_claims():
    """A decision reported but recorded nowhere cannot be audited, appealed or
    reversed — there is nothing to point at."""
    current = find_unbacked_authority_claims()

    new = current - KNOWN_UNBACKED_AUTHORITY
    assert not new, (
        "method(s) claiming an authoritative act while mutating no service "
        f"state: {sorted(new)}. Nothing they did could make the claim true."
    )

    fixed = KNOWN_UNBACKED_AUTHORITY - current
    assert not fixed, (
        f"remove from KNOWN_UNBACKED_AUTHORITY to tighten the ratchet: {sorted(fixed)}"
    )


def test_the_inventory_is_at_the_measured_baseline():
    """2 at introduction, both adjudicated. BURN-DOWN starts here."""
    assert len(KNOWN_UNBACKED_AUTHORITY) == 2
    assert find_unbacked_authority_claims() == KNOWN_UNBACKED_AUTHORITY


def test_it_fires_on_the_shape_it_exists_for_and_not_on_neighbours():
    """Proven in BOTH directions (rule 35) — it must DISCRIMINATE, not trip."""
    def fires(src: str) -> bool:
        fn = ast.parse(src.strip()).body[0]
        if not _authority_claims(fn):
            return False
        body = ast.unparse(fn)
        if refusal_primitives.mentions_refusal(body) or "is_placeholder" in body:
            return False
        if any(d in body for d in _DISCLOSES):
            return False
        return not mutates_service_state(fn)

    # FIRES — the shape it exists for
    assert fires('''
async def f(self, mid, signer):
    return {"id": uuid.uuid4().hex, "status": "approved", "signer": signer}
'''), "D11 does not fire on the shape it exists for"

    # NOT — it recorded the decision
    assert not fires('''
async def f(self, mid, signer):
    self._approvals.setdefault(mid, []).append(signer)
    return {"status": "approved", "signer": signer}
'''), "D11 fires on a method that DID record the decision"

    # NOT — recorded through an alias
    assert not fires('''
async def f(self, mid, signer):
    ms = self._multisigs[mid]
    ms["approvals"].append(signer)
    return {"status": "approved"}
'''), "D11 is blind to an alias write — use tests/state_mutation.py"

    # NOT — it refuses honestly
    assert not fires('''
async def f(self, mid, signer):
    if not self._web3.available:
        return not_deployed_response("governance", {})
    return {"status": "approved"}
'''), "D11 fires on a method that honestly refuses"

    # NOT — it discloses
    assert not fires('''
async def f(self, mid, signer):
    return {"status": "approved", "settled": False,
            "disclosure": "RECORDED, NOT EXECUTED."}
'''), "D11 fires on a method that already discloses"

    # NOT — a DELIVERY claim; that is D7's axis, not this one
    assert not fires('''
async def f(self, to, amt):
    return {"status": "transferred", "to": to, "amount": amt}
'''), "D11 has drifted onto D7's delivery axis"


def test_the_two_axes_do_not_overlap():
    """D7 asks whether value moved; D11 asks whether a decision was recorded.
    A shared word would make both counts unreadable."""
    from tests.test_fake_delivery_detector import DELIVERY_VOCABULARY

    assert not (AUTHORITY_VOCABULARY & DELIVERY_VOCABULARY), (
        "the vocabularies overlap — a method would appear on both ratchets and "
        "neither count could be reasoned about"
    )


def test_the_refusal_vocabulary_comes_from_the_registry():
    """The standing rule after NEW-94c: every name-matching control sources its
    refusal vocabulary from one registry, or the next wrapper blinds it alone."""
    src = pathlib.Path(__file__).read_text()
    assert "from tests import refusal_primitives" in src
    tree = ast.parse(src)
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    skip.add(id(inner))
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) \
           and body and isinstance(body[0], ast.Expr) \
           and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            skip.add(id(body[0].value))
    hardcoded = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and id(n) not in skip
        and n.value in refusal_primitives.REFUSAL_PRIMITIVES
    ]
    assert not hardcoded, f"D11 hardcodes a refusal primitive: {hardcoded}"
