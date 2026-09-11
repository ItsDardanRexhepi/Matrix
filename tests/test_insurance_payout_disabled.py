"""NEW-76 — the unauthenticated insurance payout primitive, disabled.

THE FINDING. `runtime/blockchain/insurance.py::_process_payout` took
`beneficiary` and `coverage_amount` FROM THE CALLER, signed with
`blockchain.paymaster_private_key`, and broadcast a real ETH transfer:

    tx = {"to": Web3.to_checksum_address(beneficiary),
          "value": self.web3.to_wei(float(amount), "ether"), ...}
    signed  = account.sign_transaction(tx)
    tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)

No policy lookup. No claim verification. No attestation check. No ownership
check. `policy_id` was accepted and used ONLY to decorate the attestation
written AFTER the money left — a receipt naming a policy nobody read.

This is not insurance with weak verification. It is an unauthenticated
withdrawal on the platform treasury, wearing an insurance name, callable with
an arbitrary destination and an arbitrary amount.

WHY SEVEN DOMAINS OF SURFACE-TRACING MISSED IT. `process_payout` is on NONE of
the five surfaces this audit had been tracing — not ACTION_MAP, the capability
catalog, the gateway route tables, the intent table, or
extensions/registry.json. It is reachable through the AGENT TOOL surface
(`runtime/blockchain/registry.py` registers this class for ToolDispatcher), a
different dispatcher entirely. Tracing one dispatcher is not tracing
reachability — recorded as a standing correction to the census method.

WHY IT WAS NOT LIVE, and why that is thin. `_require_config` rejects the
shipped `YOUR_`-prefixed placeholders, so it raised rather than sent —
armed-on-CREDENTIAL. Credentials land earlier in a deployment than contracts
do, so this was closer to live than any prior armed-on-deployment finding.

DISPOSITION: disabled at the LEAF, not merely unadvertised, because an
unregistered path is still a callable path. The action is ALSO removed from
the tool's parameter enum so the model is not offered it. Both, because either
alone leaves a hole: enum-only leaves it callable by explicit action string,
leaf-only leaves it advertised.

The three sibling actions (create_policy, file_claim, get_policy) are honest
EAS-attestation clients and are deliberately untouched.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from runtime.blockchain.insurance import Insurance

REPO = Path(__file__).resolve().parent.parent

# Credentials that would have PASSED _require_config — i.e. the ARMED case.
# The disable must hold here, not merely where credentials are missing.
ARMED_CONFIG = {
    "blockchain": {
        # Deliberately UNROUTABLE. It is not a "YOUR_" placeholder, so it
        # passes _require_config and exercises the armed path — but it cannot
        # reach a network. Without this, running the pre-fix proof against the
        # ORIGINAL code would attempt outbound RPC (gas_price / nonce) toward
        # a real testnet before failing. A proof-of-failure for a money path
        # must be provably network-free, not incidentally so.
        "rpc_url": "http://127.0.0.1:1",
        "paymaster_private_key": "0x" + "11" * 32,
        "platform_wallet": "0x000000000000000000000000000000000000dEaD",
        "chain_id": 84532,
        "network": "base-sepolia",
    }
}


async def test_payout_refuses_even_with_credentials_configured():
    """THE REPRODUCTION. Fully armed, it must send nothing.

    Asserted with working credentials on purpose: a disable that only holds
    because config is missing is not a disable, it is the pre-existing
    accident that made the hole latent.
    """
    result = json.loads(
        await Insurance(ARMED_CONFIG).execute(
            action="process_payout",
            beneficiary="0x000000000000000000000000000000000000BEEF",
            coverage_amount="100",
            policy_id="anything",
        )
    )

    assert result["status"] == "error"
    assert result["value_moved"] is False
    assert result["disabled_by"] == "NEW-76"
    assert "tx_hash" not in result, "a transaction hash was produced"
    assert "paid" not in str(result.get("status", "")).lower()


def test_no_signing_or_sending_survives_in_the_live_payout_body():
    """Proves the transfer is REMOVED, not guarded.

    A guarded-but-present send is one refactor from being live again — the
    lesson from the milestone fallback, which became the live path exactly
    that way. Comment-quoted occurrences (the docstring records what the code
    used to do) are excluded; live code must contain none.
    """
    src = inspect.getsource(Insurance._process_payout)
    live = "\n".join(
        line for line in src.splitlines()
        if not line.strip().startswith("#")
    )
    # strip the docstring, which deliberately quotes the removed code
    if '"""' in live:
        first = live.index('"""')
        last = live.index('"""', first + 3) + 3
        live = live[:first] + live[last:]

    for token in (
        "send_raw_transaction",
        "sign_transaction",
        "to_wei",
        "paymaster_private_key",
        "send_transaction",
    ):
        assert token not in live, (
            f"live payout body still contains {token} — the transfer is "
            "guarded rather than removed"
        )


def test_the_action_is_no_longer_advertised_to_the_model():
    """Surface half. The enum is what the agent is offered."""
    enum = Insurance(ARMED_CONFIG).parameters["properties"]["action"]["enum"]
    assert "process_payout" not in enum
    assert enum == ["create_policy", "file_claim", "get_policy"]


async def test_the_action_still_refuses_when_called_by_explicit_name():
    """Leaf half — the reason enum removal alone is insufficient.

    A caller who ignores the schema and passes the string directly must still
    be refused, not fall through to an unknown-action message that a future
    reader might 'fix' by re-adding the branch.
    """
    raw = await Insurance(ARMED_CONFIG).execute(action="process_payout")
    assert "NEW-76" in raw
    assert "disabled" in raw.lower()


def test_the_lifting_condition_names_all_four_clauses():
    """A security disable states what would license lifting it, and this one
    is compound: fixing the destination without the authority, or the
    authority without the amount, still leaves a drainable primitive."""
    doc = inspect.getdoc(Insurance._process_payout) or ""
    assert "LIFTING CONDITION" in doc
    for clause in ("verifies it exists", "APPROVED claim", "FROM the policy",
                   "remaining coverage"):
        assert clause in doc, f"lifting condition missing clause: {clause}"


@pytest.mark.parametrize("action", ["create_policy", "file_claim", "get_policy"])
def test_the_honest_sibling_actions_are_untouched(action):
    """These are real EAS-attestation clients (attest / verify on-chain).
    The disable must not collaterally remove working capability."""
    enum = Insurance(ARMED_CONFIG).parameters["properties"]["action"]["enum"]
    assert action in enum
    src = inspect.getsource(Insurance)
    assert f'action == "{action}"' in src


def test_payout_is_absent_from_every_audited_surface():
    """Records the reachability fact that made this a tool-surface finding.

    If `process_payout` ever appears on one of these, it has been re-exposed
    on a surface this audit does trace, and the lifting condition applies.
    """
    surfaces = [
        "runtime/blockchain/services/service_dispatcher.py",
        "runtime/capabilities/catalog.py",
        "gateway/service_routes.py",
        "runtime/chat/intent_actions.py",
        "extensions/registry.json",
    ]
    for rel in surfaces:
        text = (REPO / rel).read_text()
        assert "process_payout" not in text, (
            f"process_payout now appears in {rel} — it has been exposed on an "
            "audited surface; see the NEW-76 lifting condition"
        )
