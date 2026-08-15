"""22-A — the royalty destination could be redirected by anyone.

MEASURED at pin 84a6c3e through the real ServiceDispatcher, under THE SHIPPED
CONFIG. `configure_nft_royalty` is one of only SIX of seventeen nft actions
that executes at all — the rest crash or refuse — so this was live in the
deployment we ship:

    1. creator configures   -> configured  recipient=0x1111  bps=500
    2. STRANGER, identity="" -> configured  recipient=0x2222  bps=2500
    3. get_royalty_info      -> receiver=0x2222
    4. buy_nft               -> royalty split computed for 0x2222

The stored entry carried NO attribution field, so after the overwrite nothing
in the platform's own store distinguished the creator's configuration from the
stranger's except the recipient value — the thing under dispute.

WHY THIS IS FIXABLE IN-DOMAIN AND THE OWNERSHIP CHECK IS NOT: the package
justifies having no authority check with "this platform has no ownership record
to check against". True of TOKEN ownership, which lives on-chain. FALSE of this
record — the royalty config is the platform's own store, written by this method,
which knows who wrote it first. §AI.1: an absence established at the ownership
scope, stated at the whole-domain scope.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.blockchain.services.nft_services.service import NFTService
from runtime.blockchain.services.service_dispatcher import _outcome_is_real

_A = "0x1111111111111111111111111111111111111111"
_B = "0x2222222222222222222222222222222222222222"


def _shipped():
    """The config we actually ship — not a fixture invented for the test."""
    return json.loads(Path("openmatrix.config.json.example").read_text())


@pytest.mark.asyncio
async def test_a_stranger_cannot_redirect_a_configured_royalty():
    """THE REPRODUCTION."""
    svc = NFTService(_shipped())
    await svc.configure_royalty("0xC", -1, _A, 500)
    out = await svc.configure_royalty("0xC", -1, _B, 2500)

    assert out.get("refused") is True
    info = svc.get_royalty_info("0xC", 42, 10.0)
    if hasattr(info, "__await__"):
        info = await info
    assert info["receiver"] == _A, "the original recipient did not survive"


@pytest.mark.asyncio
async def test_the_refusal_is_returned_so_the_attempt_is_recorded():
    """Domain 21's AQ::9 lesson, transferred. A RAISED refusal unwinds past the
    dispatcher's attestation block — measured there — so the hijack attempt
    leaves no record and is reported as an internal fault of ours."""
    svc = NFTService(_shipped())
    await svc.configure_royalty("0xC", -1, _A, 500)
    out = await svc.configure_royalty("0xC", -1, _B, 2500)   # must NOT raise
    assert isinstance(out, dict)
    assert out.get("refused") is True
    assert _outcome_is_real(out) is False
    assert "reason" in out and "disclosure" in out


@pytest.mark.asyncio
async def test_the_record_says_who_set_it_and_how_we_know():
    """17-J's form: WHO, and separately HOW WE KNOW. `set_by: ""` alone cannot
    distinguish "nobody was authenticated" from "we did not look"."""
    svc = NFTService(_shipped())
    out = await svc.configure_royalty("0xC", -1, _A, 500,
                                      caller_identity=_A,
                                      caller_source="authenticated")
    assert out["set_by"] == _A
    assert out["set_by_source"] == "authenticated"

    svc2 = NFTService(_shipped())
    anon = await svc2.configure_royalty("0xD", -1, _A, 500)
    assert anon["set_by"] == ""
    assert anon["set_by_source"] == "unauthenticated"


@pytest.mark.asyncio
async def test_the_identified_setter_may_still_change_their_own_royalty():
    """§AQ class 3 — the guard must still permit what it permitted."""
    svc = NFTService(_shipped())
    await svc.configure_royalty("0xC", -1, _A, 500,
                                caller_identity=_A, caller_source="authenticated")
    out = await svc.configure_royalty("0xC", -1, _A, 700,
                                      caller_identity=_A, caller_source="authenticated")
    assert out["status"] == "configured"
    assert out["bps"] == 700


@pytest.mark.asyncio
async def test_a_first_configuration_is_never_refused():
    """§AQ class 3, and the flow the in-package writers depend on:
    `create_collection` (service.py:188) and `mint` (service.py:242) each write
    a FRESH key, so neither is refused by this guard. Checked, not assumed."""
    svc = NFTService(_shipped())
    assert (await svc.configure_royalty("0xNEW", -1, _A, 500))["status"] == "configured"
    assert (await svc.configure_royalty("0xNEW", 7, _A, 500))["status"] == "configured"


@pytest.mark.asyncio
async def test_a_different_identity_cannot_take_over_an_owned_royalty():
    svc = NFTService(_shipped())
    await svc.configure_royalty("0xC", -1, _A, 500,
                                caller_identity=_A, caller_source="authenticated")
    out = await svc.configure_royalty("0xC", -1, _B, 2500,
                                      caller_identity=_B, caller_source="authenticated")
    assert out.get("refused") is True


# ─────────────────────────────── 22-G ───────────────────────────────

@pytest.mark.parametrize("cfg,capped", [
    ({"nft": {"max_royalty_bps": 100}}, True),          # factory.py:30's key
    ({"nft": {"royalty": {"max_bps": 100}}}, True),     # this class's key
    ({"nft": {"max_royalty_bps": 2500, "royalty": {"max_bps": 100}}}, True),
    ({}, False),                                         # default 2500
])
@pytest.mark.asyncio
async def test_both_documented_cap_keys_govern_the_live_path(cfg, capped):
    """22-G. TWO CONFIG KEYS FOR ONE CONCEPT, and the documented one did not
    govern the live path.

    `factory.py:30` documents `nft.max_royalty_bps` and factory.py:44 reads it,
    governing deploy/mint — which REFUSE under the shipped config. This class
    read only `nft.royalty.max_bps`, and this class is what
    `configure_nft_royalty` uses: one of only SIX of seventeen nft actions that
    executes at all.

    MEASURED before: `nft.max_royalty_bps = 100` and a request for 2500 was
    CONFIGURED AT 2500. An operator who read the factory's documentation and
    set the cap it names capped only the paths that already refuse."""
    svc = NFTService(cfg)
    if capped:
        with pytest.raises(ValueError):
            await svc.configure_royalty("0xC", -1, _A, 2500)
    else:
        out = await svc.configure_royalty("0xC", -1, _A, 2500)
        assert out["bps"] == 2500


@pytest.mark.asyncio
async def test_the_nested_key_wins_when_both_are_set():
    """§AQ class 3 — an operator who already set `nft.royalty.max_bps` must not
    silently get a different cap because a second key is now honoured."""
    svc = NFTService({"nft": {"max_royalty_bps": 2500, "royalty": {"max_bps": 100}}})
    with pytest.raises(ValueError):
        await svc.configure_royalty("0xC", -1, _A, 500)
