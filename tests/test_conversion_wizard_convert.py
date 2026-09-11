"""`ConversionWizard.convert()` — the method a deletion killed in silence.

WHY THIS FILE EXISTS. Commit 3e931d4 removed `migrate_members`. The deletion
hunk ended on the `@staticmethod` decorator belonging to the NEXT method,
`_calculate_voting_power`, and took it along. `convert()` calls it as
`self._calculate_voting_power(shares, total, governance_type)` — three arguments
plus the implicit `self` — so an undecorated three-parameter function received
four and raised `TypeError` on every single call.

THE SUITE STAYED GREEN AT 2000 TESTS. `convert()` had no coverage at all; the
only test naming `ConversionWizard` asserted `not hasattr(..., "migrate_members")`,
which is exactly the property the broken commit satisfied. A removal was verified
by checking that something was gone, and nothing checked that everything else
still worked.

Five independent adversarial lenses found it. None of the 2000 tests did.

So this file covers the METHOD, and tests/test_bound_call_arity.py covers the
SHAPE across every class in the tree — because the next lost decorator will be
somewhere else, and a test that only pins this one symbol would not see it.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.dao_management.conversion_wizard import ConversionWizard

_ORG = {
    "name": "Acme",
    "members": [
        {"name": "a", "address": "0x1", "role": "ceo", "shares": 10},
        {"name": "b", "address": "0x2", "role": "member", "shares": 5},
    ],
}


def test_the_helper_is_still_a_staticmethod():
    """THE DIRECT PIN. `self.f(a, b, c)` against a three-parameter function is
    only valid while the decorator is present."""
    assert isinstance(
        ConversionWizard.__dict__["_calculate_voting_power"], staticmethod
    ), (
        "the @staticmethod decorator is gone again — every convert() call will "
        "raise TypeError, and only this test will say so"
    )


async def test_convert_produces_a_migration_plan():
    """THE BEHAVIOURAL COVER. This is what nothing exercised, which is why the
    break shipped."""
    result = await ConversionWizard({}).convert(
        _ORG, {"governance_type": "token_weighted", "dao_name": "AcmeDAO"}
    )

    plan = result["migration_plan"]
    assert len(plan) == 2
    assert plan[0]["voting_power"] == pytest.approx(66.6667)
    assert plan[1]["voting_power"] == pytest.approx(33.3333)
    assert plan[0]["dao_role"] == "admin"
    assert plan[1]["dao_role"] == "member"


@pytest.mark.parametrize(
    "governance_type",
    ["token_weighted", "one_member_one_vote", "quadratic", "unrecognised", None],
)
async def test_every_governance_branch_reaches_the_helper(governance_type):
    """The TypeError was UNCONDITIONAL — the call sits in the per-member loop
    with no branch above it, so every governance type raised. Each is driven
    rather than assuming one case covers the rest."""
    config = {"dao_name": "AcmeDAO"}
    if governance_type is not None:
        config["governance_type"] = governance_type

    result = await ConversionWizard({}).convert(_ORG, config)

    assert len(result["migration_plan"]) == 2
    for row in result["migration_plan"]:
        assert isinstance(row["voting_power"], float)


async def test_the_auto_analyse_path_works_too():
    """`dao_config={}` takes a different entry path into the same loop."""
    result = await ConversionWizard({}).convert(_ORG, {})

    assert len(result["migration_plan"]) == 2


async def test_analyze_org_was_never_affected():
    """SCOPE PIN, inverted. `analyze_org` does not call the helper and worked
    throughout — recorded so a future reader does not over-attribute the break."""
    analysis = await ConversionWizard({}).analyze_org(_ORG)

    assert analysis is not None
