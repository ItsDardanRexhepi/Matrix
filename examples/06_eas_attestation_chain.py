#!/usr/bin/env python3
from __future__ import annotations
"""
06 — EAS Attestation Chain: Attesting Records Through the Capabilities

Demonstrates the attestation capabilities of Ethereum Attestation Service (EAS)
with sample records this example composes:

  1. A sample contract-deployment record -> create_attestation
  2. A sample ownership-transfer record -> create_attestation
  3. A sample insurance-policy record -> create_attestation
  4. Three sample records -> batch_attest
  5. Verify an attestation on-chain, when step 1 returned one

Nothing here deploys, transfers or insures anything; the records are sample
data, attested under the schema in blockchain.eas_schema. An attestation that is not time-critical is queued in memory and written
on-chain only when a batch of 50 fills in the same process: nothing drains the
queue on a timer, and what is queued is lost if the process exits first. So a
run of this example usually gets queue receipts rather than transaction hashes.
The dispatcher also records each state-modifying action that settles, the same
way. An attestation you ask for is refused when blockchain.eas_schema is not a
registered schema UID, and it is metered by the gas sponsorship policy like
any other operation, so where no sponsorship is configured the policy
refuses it.

Each step prints what the service answered, and a step counts as done only
when the dispatcher reports that it happened (its call_outcome is "success").

Usage:
    python examples/06_eas_attestation_chain.py
"""

import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
from examples._steps import BOLD, CYAN, RESET, Steps, fail, ok, shown, step, warn


def load_config() -> dict:
    config_path = os.path.join(ROOT, "matrix.config.json")
    if not os.path.exists(config_path):
        fail(f"Config not found: {config_path}")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


def _receipt(result) -> None:
    """Print what an attestation answered: a queue receipt or a transaction."""
    ok(f"Status: {shown(result, 'status')}"
       + (f", tx {result['attestation_tx']}" if isinstance(result, dict) and result.get("attestation_tx") else ""))


async def main():
    print(f"""
{CYAN}{BOLD}{'=' * 60}
  The Matrix Example 06: EAS Attestation Chain
{'=' * 60}{RESET}

  Attests sample records through the attestation capabilities
  (Ethereum Attestation Service on Base Sepolia). A record that is not
  time-critical is queued in memory until a batch of 50 fills.
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)
    bc = config.get("blockchain", {})
    wallet = bc.get("demo_wallet_address", "0xDemoWallet")
    schema = bc.get("eas_schema", "")
    new_owner = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"
    steps = Steps(dispatcher)
    uids: list[str] = []

    records = [
        ("a sample contract-deployment record", {
            "action": "deploy_contract", "contract_name": "RentalAgreement",
            "contract_address": "0x1234567890abcdef1234567890abcdef12345678",
            "deployer": wallet, "chain_id": 84532, "audit_passed": True}, wallet),
        ("a sample ownership-transfer record", {
            "action": "transfer_rwa_ownership", "asset_id": "rwa-house-001",
            "from_owner": wallet, "to_owner": new_owner, "asset_type": "real_estate"}, new_owner),
        ("a sample insurance-policy record", {
            "action": "create_insurance", "policy_id": "policy-crop-001",
            "policyholder": wallet, "type": "crop"}, wallet),
    ]
    for n, (label, data, recipient) in enumerate(records, 1):
        step(n, f"Attesting {label}...")
        result = await steps.run(f"attest {label}", "create_attestation", {
            "schema_uid": schema, "data": data, "recipient": recipient,
        })
        if result is not None:
            _receipt(result)
            # The service answers with a transaction hash when it submitted the
            # attestation, or a queue receipt; it does not return an EAS UID.
            if isinstance(result, dict) and result.get("uid"):
                uids.append(result["uid"])

    step(4, "Attesting three sample records with batch_attest...")
    batch = await steps.run("attest three records in one call", "batch_attest", {
        "attestations": [
            {"schema_uid": schema, "data": {"action": "mint_nft", "token_id": 1, "collection": "GART"},
             "recipient": wallet},
            {"schema_uid": schema, "data": {"action": "create_loan", "loan_id": "loan-001", "amount": 100},
             "recipient": wallet},
            {"schema_uid": schema, "data": {"action": "stake", "amount": 10, "token": "USDC"},
             "recipient": wallet},
        ],
    })
    if isinstance(batch, list):
        # One result per entry: each is queued or, if time-critical, submitted
        # on its own. There is no single batch transaction.
        ok(f"batch_attest answered for {len(batch)} records")
        for entry in batch:
            _receipt(entry)

    step(5, "Verifying an attestation on-chain...")
    if uids:
        verified = await steps.run("verify the first attestation", "verify_attestation",
                                   {"attestation_uid": uids[0]})
        if verified is not None:
            ok(f"Exists on-chain: {shown(verified, 'exists')}")
            ok(f"Revoked: {shown(verified, 'revoked')}")
    else:
        warn("No attestation UID to verify: the service returns transaction hashes or queue "
             "receipts, not EAS UIDs")

    steps.summary("Attestation example")
    print(f"""
  When an action on the dispatcher's state-modifying list settles, the
  ServiceDispatcher hands the attestation service a record of it (action,
  service, actor, a parameter hash, a timestamp), queued like any record that
  is not time-critical. A refusal is logged, not attested.
""")


if __name__ == "__main__":
    asyncio.run(main())
