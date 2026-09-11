"""DOMAIN 19-A / 19-B / 19-C — who may act, who benefits, and what the chain did.

Three findings on one service, every one of them an input reaching a path that
moves the PLATFORM'S OWN treasury, signed by the platform paymaster.

19-A  `services.restaking.enabled` had ZERO READERS and was the only key the
      shipped example config sets for this service. An operator following our
      own documentation set `enabled: false`, believed the service was gated,
      and all seven value-moving methods executed normally.

19-B  `receiver = params.get("receiver") or get_account().address` went into
      arg 2 of ERC-4626 `Vault.deposit(assets, receiver)`. Platform collateral
      out, caller's shares in. The response asserted `acts_on:
      "platform_account"` — true of the SOURCE, false of the DESTINATION.

19-C  `status: "submitted"` meant only that a node accepted a raw transaction.
      No receipt was awaited, so a REVERTED transaction was indistinguishable
      from a successful one — and `submitted` is in _REAL_OUTCOME_STATUSES, so
      the dispatcher attested and published it. The same field carried the
      OPPOSITE error: a broadcast that then failed on read returned "error",
      which reads as a refusal, so the audit trail recorded "the platform
      declined" for a transaction that may be mined.

THE ORPHANED-REAL-MECHANISM PATTERN, FOURTH INSTANCE. 19-C is not "build
receipt settlement". `Web3Manager.wait_for_receipt` has existed at
web3_manager.py:191 the whole time, and `pending` was already in
`_NON_OUTCOME_STATUSES`. **The evidence was collectable all along and was not
being collected.** The fix is to call the thing that was already there — the
same shape as the census's earlier finds where a correct verifier sat
unreachable while a self-attesting path served every live request.

ON THIS FILE'S HARNESS, WHICH IS THE POINT OF IT.
Two harnesses died before reaching their subject while this domain was being
worked: one passed `"0xV"` as an address and failed checksumming; one omitted
`chain_id` and failed `build_transaction`. Both produced `status: "error"` —
**identical output to a fix that does not work.** Only the failure REASON
distinguished them. `_Web3Stub` below therefore implements the COMPLETE
surface the service uses, enumerated rather than discovered:

    available · chain_id · explorer_url · get_account · load_contract
    send_transaction · w3 · wait_for_receipt

and `test_the_harness_reaches_the_code_under_test` asserts the subject was
actually entered, so a future harness regression fails loudly instead of
silently reporting a broken fix.
"""

from __future__ import annotations

import pytest
from web3 import Web3

from runtime.blockchain.services.restaking._guards import settle_transaction
from runtime.blockchain.services.restaking.service import RestakingService
from runtime.blockchain.services.service_dispatcher import _outcome_is_real

PLATFORM = "0x1111111111111111111111111111111111111111"
VAULT = "0x2222222222222222222222222222222222222222"
ATTACKER = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"


class _Receipt:
    def __init__(self, status: int) -> None:
        self.status = status
        self.blockNumber = 42
        self.gasUsed = 21_000


class _Web3Stub:
    """The COMPLETE Web3Manager surface this service touches. Enumerated by
    `grep -o "self\\._web3\\.[a-z_]*"`, not discovered one AttributeError at a
    time — an incomplete stub fails early and looks exactly like a broken fix."""

    available = True
    chain_id = 8453
    w3 = Web3()

    def __init__(self, receipt_status: int = 1, receipt_fails: bool = False):
        self._receipt_status = receipt_status
        self._receipt_fails = receipt_fails
        self.reached_settle = False
        self.broadcasts: list[dict] = []

    def is_placeholder(self, _v):
        return False

    def get_account(self):
        return type("A", (), {"address": PLATFORM})()

    def explorer_url(self, h):
        return f"https://basescan.org/tx/{h}"

    def load_contract(self, addr, abi):
        class _Fn:
            @staticmethod
            def build_transaction(opts):
                return {"to": addr, "data": "0x", **opts}

        class _Functions:
            def __getattr__(self, _name):
                return lambda *a, **k: _Fn()

        return type("C", (), {"functions": _Functions()})()

    async def send_transaction(self, tx):
        self.broadcasts.append(tx)
        return "0x" + "ab" * 32

    async def wait_for_receipt(self, tx_hash, timeout=120):
        self.reached_settle = True
        if self._receipt_fails:
            raise TimeoutError("no receipt within window")
        return _Receipt(self._receipt_status)


def _svc(enabled: bool = True, **stub_kw) -> RestakingService:
    cfg = {"services": {"restaking": {
        "karak_vault_address": VAULT, "symbiotic_vault_address": VAULT,
        "lido_steth_address": VAULT, "strategy_manager_address": VAULT,
        "strategy_address": VAULT, "delegation_manager_address": VAULT,
        "rocketpool_deposit_address": VAULT,
    }}}
    if enabled:
        cfg["services"]["restaking"]["enabled"] = True
    svc = RestakingService(cfg)
    svc._web3 = _Web3Stub(**stub_kw)
    return svc


# ══════════════════════════════════════════════════════════════════════════
# The harness itself, asserted first
# ══════════════════════════════════════════════════════════════════════════


async def test_the_harness_reaches_the_code_under_test():
    """DEFECT-PROVER for the TEST, not the code — and it exists because two
    harnesses in this domain died before reaching their subject and returned
    `status: "error"`, which is byte-identical to a fix that does not work.

    If this fails, every 19-C assertion below is meaningless rather than
    failing. Assert entry, not just outcome."""
    svc = _svc()
    result = await svc.restake_karak(amount=1)
    assert svc._web3.reached_settle is True, (
        "the harness never reached settle_transaction — the 19-C results below "
        "would be measuring the stub, not the fix"
    )
    assert svc._web3.broadcasts, "nothing was broadcast"
    assert result.get("error") is None, f"harness fault: {result.get('error')}"


# ══════════════════════════════════════════════════════════════════════════
# 19-A · who may act
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("method,kwargs", [
    ("restake", {"amount": 1}),
    ("restake_symbiotic", {"amount": 1}),
    ("restake_karak", {"amount": 1}),
    ("delegate_to_operator", {"operator": ATTACKER}),
    ("withdraw_restake", {"shares": 1}),
    ("liquid_stake_lido", {"amount": 1}),
    ("liquid_stake_rocketpool", {"amount": 1}),
])
async def test_every_value_moving_method_refuses_until_explicitly_enabled(
    method, kwargs,
):
    """DEFECT-PROVER. `enabled` had zero readers, so setting it false disabled
    nothing. Asserted for ALL SEVEN rather than a sample — §AK.2: naming one
    call site while seven share the defect is a half-fix by construction."""
    svc = _svc(enabled=False)
    out = await getattr(svc, method)(**kwargs)
    assert out["status"] == "not_deployed"
    assert "enabled" in str(out.get("missing", ""))
    assert svc._web3.broadcasts == [], "a disabled service broadcast a transaction"


async def test_the_refusal_is_not_attested_as_an_outcome():
    """SCOPE PIN. `not_deployed` must remain a non-outcome, or the new gate
    would publish a refusal to the feed."""
    svc = _svc(enabled=False)
    assert _outcome_is_real(await svc.restake_karak(amount=1)) is False


async def test_populating_addresses_alone_does_not_enable_the_service():
    """DEFECT-PROVER, AND THE POINT OF THE FIX. Every contract address is set
    here; only `enabled` is absent. Populating credentials is NOT an opt-in to
    moving the treasury — that was the §AP defect, where the operator's own
    diligence was the delivery mechanism."""
    svc = _svc(enabled=False)
    out = await svc.liquid_stake_lido(amount=1e30)
    assert out["status"] == "not_deployed"


# ══════════════════════════════════════════════════════════════════════════
# 19-B · who benefits
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("method", ["restake_symbiotic", "restake_karak"])
async def test_a_caller_cannot_name_the_beneficiary(method):
    """DEFECT-PROVER. The platform paymaster signs and platform collateral is
    spent; the ERC-4626 shares are the claim on those assets. A caller-named
    receiver made the platform pay for a position the caller owned."""
    svc = _svc()
    out = await getattr(svc, method)(amount=1, receiver=ATTACKER)
    assert out["status"] == "error"
    assert "not the platform account" in str(out.get("error", ""))
    assert svc._web3.broadcasts == [], "a diverted deposit was broadcast"


@pytest.mark.parametrize("method", ["restake_symbiotic", "restake_karak"])
async def test_naming_the_platform_itself_is_accepted(method):
    """SCOPE PIN. The parameter is refused only when it DIVERGES — an explicit,
    correct receiver must not be treated as an attack."""
    svc = _svc()
    out = await getattr(svc, method)(amount=1, receiver=PLATFORM)
    assert out["status"] == "submitted"


@pytest.mark.parametrize("method", ["restake_symbiotic", "restake_karak"])
async def test_the_default_path_is_unchanged(method):
    """SCOPE PIN. Omitting `receiver` was always correct and must stay so."""
    svc = _svc()
    assert (await getattr(svc, method)(amount=1))["status"] == "submitted"


# ══════════════════════════════════════════════════════════════════════════
# 19-C · what actually happened — BOTH HALVES (17-D)
# ══════════════════════════════════════════════════════════════════════════


async def test_a_mined_transaction_is_a_real_outcome():
    """SCOPE PIN on the honest path, DEFECT-PROVER on the fields. `submitted`
    still reads as a real outcome — but now only after a receipt said so."""
    svc = _svc(receipt_status=1)
    out = await svc.restake_karak(amount=1)
    assert out["status"] == "submitted"
    assert out["settled"] is True and out["value_moved"] is True
    assert out["block_number"] == 42
    assert _outcome_is_real(out) is True


async def test_a_reverted_transaction_is_not_reported_as_success():
    """DEFECT-PROVER — THE OVER-CLAIM HALF. Pre-fix a revert was
    indistinguishable from success: no receipt was awaited, `submitted` was
    returned regardless, and the dispatcher attested it and published it to the
    public feed as an action that happened."""
    svc = _svc(receipt_status=0)
    out = await svc.restake_karak(amount=1)
    assert out["status"] == "failed"
    assert out["value_moved"] is False
    assert "REVERTED" in out["disclosure"]
    assert _outcome_is_real(out) is False, "a reverted transaction was attested"


async def test_a_broadcast_without_a_receipt_is_not_recorded_as_a_refusal():
    """DEFECT-PROVER — THE UNDER-CLAIM HALF, AND THE WORSE ONE. Pre-fix this
    returned bare `error`, which `_outcome_is_real` reads as a refusal, so the
    audit trail said 'the platform declined' about a transaction that was
    broadcast and may be mined.

    An over-claim is visible to the claimant; an under-claim is visible to
    nobody. `pending` is correct — attesting now would assert the future — but
    it must carry `broadcast: True` and the hash so it is distinguishable from
    a refusal that never touched the chain."""
    svc = _svc(receipt_fails=True)
    out = await svc.restake_karak(amount=1)
    assert out["status"] == "pending"
    assert out["broadcast"] is True
    assert out["tx_hash"]
    assert out["value_moved"] is None, "unknown must not be reported as False"
    assert "NOT a refusal" in out["disclosure"]
    assert _outcome_is_real(out) is False


async def test_both_halves_are_distinguishable_from_each_other():
    """DEFECT-PROVER (§AC's completed form). The three outcomes must be told
    apart BY SHAPE, since that is all a downstream control has. Pre-fix two of
    them were the same string."""
    shapes = {}
    for label, kw in (("mined", {}), ("reverted", {"receipt_status": 0}),
                      ("unknown", {"receipt_fails": True})):
        out = await _svc(**kw).restake_karak(amount=1)
        shapes[label] = (out["status"], out.get("settled"), out.get("value_moved"))
    assert len(set(shapes.values())) == 3, f"outcomes collapse: {shapes}"


def test_the_service_no_longer_hardcodes_a_success_status():
    """DEFECT-PROVER, STRUCTURAL. Seven methods each returned a literal
    `"status": "submitted"` immediately after broadcast. If one returns,
    §AK.2's half-fix has happened."""
    import pathlib
    src = pathlib.Path(
        "runtime/blockchain/services/restaking/service.py").read_text()
    assert '"status": "submitted"' not in src
    assert src.count("settle_transaction") >= 8
