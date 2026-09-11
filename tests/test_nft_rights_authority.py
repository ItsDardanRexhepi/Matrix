"""22-C — `created_by`/`set_by` were written and never compared.

MEASURED at pin 84a6c3e through the real ServiceDispatcher, under THE SHIPPED
CONFIG (`set_nft_rights` is one of only 6 of 17 nft actions that executes):

    grant #1, caller_identity='0xVICTIM'
        -> created_by='0xVICTIM', rights.commercial.holder='0xVICTIM'
    grant #2, caller_identity=''                  <-- UNAUTHENTICATED
        -> rights.commercial.holder='0xATTACKER', status 'rights_set'
    check_nft_rights -> granted=true, holder=ATTACKER, source='explicit'

17-D threaded WHO and recorded it. It did not COMPARE it. The platform was
holding the record it declines to read, one dict lookup away.

GRANULARITY WAS CORRECTED, NOT CHOSEN. The first version of this guard was
record-level. `test_each_right_records_who_granted_it` (17-D) deliberately
drives a SECOND caller adding `derivative` to a token whose `commercial` the
first caller set, and asserts the first caller's attribution survives —
MULTI-PARTY RIGHTS ON ONE TOKEN ARE A DESIGNED BEHAVIOUR. §AQ class 3: the
record-level rule stopped permitting what the code already permitted, and the
test encoding that intent caught it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.blockchain.services.nft_services.service import NFTService
from runtime.blockchain.services.service_dispatcher import _outcome_is_real

_V = "0x1111111111111111111111111111111111111111"
_A = "0x2222222222222222222222222222222222222222"


def _shipped():
    return json.loads(Path("openmatrix.config.json.example").read_text())


async def _granted(svc, coll="0xCOLL", tok=7):
    return await svc.set_rights(
        coll, tok, {"commercial": {"granted": True, "holder": _V}},
        caller_identity=_V, caller_source="authenticated")


@pytest.mark.asyncio
async def test_a_stranger_cannot_rewrite_a_granted_right():
    """THE REPRODUCTION."""
    svc = NFTService(_shipped())
    await _granted(svc)
    out = await svc.set_rights(
        "0xCOLL", 7, {"commercial": {"granted": True, "holder": _A}},
        caller_identity="")
    assert out.get("refused") is True
    chk = await svc.check_rights("0xCOLL", 7, "commercial")
    assert chk["holder"] == _V, "the victim's grant did not survive"


@pytest.mark.asyncio
async def test_a_different_identity_cannot_rewrite_a_granted_right():
    svc = NFTService(_shipped())
    await _granted(svc)
    out = await svc.set_rights(
        "0xCOLL", 7, {"commercial": {"granted": False, "holder": _A}},
        caller_identity=_A, caller_source="authenticated")
    assert out.get("refused") is True


@pytest.mark.asyncio
async def test_the_refusal_is_returned_so_the_attempt_is_recorded():
    """21-E/AQ::9 — a raised refusal unwinds past the attestation block."""
    svc = NFTService(_shipped())
    await _granted(svc)
    out = await svc.set_rights(
        "0xCOLL", 7, {"commercial": {"granted": True, "holder": _A}},
        caller_identity="")
    assert isinstance(out, dict)
    assert _outcome_is_real(out) is False
    assert out.get("reason") and out.get("disclosure")


@pytest.mark.asyncio
async def test_another_party_may_still_add_a_DIFFERENT_right():
    """§AQ CLASS 3, and the behaviour 17-D deliberately tests. Multi-party
    rights on one token are the design: a creator holds display, a licensee is
    granted commercial by someone else."""
    svc = NFTService(_shipped())
    await _granted(svc)
    out = await svc.set_rights(
        "0xCOLL", 7, {"derivative": {"granted": True, "holder": _A}},
        caller_identity=_A, caller_source="authenticated")
    assert out["status"] == "rights_set"
    chk = await svc.check_rights("0xCOLL", 7, "commercial")
    assert chk["holder"] == _V, "adding a right rewrote another's attribution"


@pytest.mark.asyncio
async def test_the_granting_party_may_still_change_their_own_right():
    """§AQ class 3."""
    svc = NFTService(_shipped())
    await _granted(svc)
    out = await svc.set_rights(
        "0xCOLL", 7, {"commercial": {"granted": False, "holder": _V}},
        caller_identity=_V, caller_source="authenticated")
    assert out["status"] == "rights_set"


@pytest.mark.asyncio
async def test_a_first_grant_on_a_fresh_token_is_never_refused():
    """The flow `mint` depends on: it sets default rights on a newly minted
    token, a FRESH key, so this guard cannot refuse it."""
    svc = NFTService(_shipped())
    out = await svc.set_rights(
        "0xNEW", 1, {"display": {"granted": True, "holder": _V}})
    assert out["status"] == "rights_set"
