"""`gateway/paymaster.py` opened with a claim about a key it does not own.

  "Non-custodial: the signer key is a PLATFORM key that only authorizes gas
   sponsorship — it never signs anything the user's account does, never moves
   user funds."

The first half is a statement about the CONTRACT's role for the key, and there
it is true: MatrixVerifyingPaymaster recovers this signer only over the
sponsorship digest. The sentence is written as a statement about the KEY, and
about the key it is false, because `paymaster_config` falls back to
`blockchain.paymaster_private_key` when no dedicated `paymaster.signer_key` is
set — and that is the shipped shape. Around twenty modules under
`runtime/blockchain/` sign and broadcast arbitrary value-moving transactions
with that same value: defi supply/borrow, dao treasury calls, ERC-20 approvals
to a caller-named spender, contract deployment.

So on the default configuration the sponsorship signer IS the platform's
general signing key, and the module says the opposite in its first paragraph.

Two things follow. The prose has to say which of the two facts it is stating.
And the fallback — which is silent, and which is where the divergence enters —
has to say so where an operator will see it.
"""

from __future__ import annotations

import logging

import gateway.paymaster as paymaster

SIGNER_KEY = "0x" + "11" * 32
OTHER_KEY = "0x" + "22" * 32


# ── 1. the fallback announces itself ───────────────────────────────────────

def test_falling_back_to_the_general_signing_key_is_not_silent(caplog):
    with caplog.at_level(logging.WARNING, logger="gateway.paymaster"):
        resolved = paymaster.paymaster_config(
            {"blockchain": {"paymaster_private_key": SIGNER_KEY}})
    assert resolved["signer_key"] == SIGNER_KEY
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "paymaster_private_key" in text, (
        "the sponsorship signer silently became the platform's general "
        "signing key and nothing said so:\n" + text)


def test_a_dedicated_signer_key_warns_about_nothing(caplog):
    for cfg in ({"paymaster": {"signer_key": SIGNER_KEY}},
                {"blockchain": {"paymaster": {"signer_key": SIGNER_KEY}}}):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="gateway.paymaster"):
            assert paymaster.paymaster_config(cfg)["signer_key"] == SIGNER_KEY
        assert not [r for r in caplog.records
                    if r.name == "gateway.paymaster"], cfg


def test_the_warning_does_not_carry_the_key(caplog):
    with caplog.at_level(logging.WARNING, logger="gateway.paymaster"):
        paymaster.paymaster_config({"blockchain": {"paymaster_private_key": SIGNER_KEY}})
    for record in caplog.records:
        assert SIGNER_KEY not in record.getMessage(), record.getMessage()
        assert SIGNER_KEY[2:] not in record.getMessage(), record.getMessage()


def test_the_resolver_still_resolves_every_documented_home():
    """The direction this must not move: precedence and no-mutation are P4."""
    src = {"paymaster": {"signer_key": "TOP"},
           "blockchain": {"paymaster_private_key": "FLAT"}}
    assert paymaster.paymaster_config(src)["signer_key"] == "TOP"
    assert "signer_key" not in src["blockchain"]
    assert paymaster.paymaster_config({})== {}
    assert paymaster.signer_configured(
        {"blockchain": {"paymaster_private_key": SIGNER_KEY}}) is True
    assert paymaster.signer_configured({}) is False


# ── 2. the prose states which fact it is stating ───────────────────────────

def test_the_module_does_not_call_the_shared_key_gas_only():
    head = paymaster.__doc__ or ""
    assert "only authorizes gas\nsponsorship" not in head, head
    assert "never signs anything the user's account does, never moves user" \
        not in head, head
    assert "paymaster_private_key" in head, (
        "the first paragraph describes the signer without ever naming the "
        "config slot it usually comes from")
