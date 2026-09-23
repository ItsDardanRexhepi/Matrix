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
data. An attestation that is not time-critical is queued in memory and written
on-chain only when a batch of 50 fills in the same process, so a run of this
example usually gets queue receipts rather than transaction hashes. The
dispatcher also records each state-modifying action that settles, the same way.

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

CYAN = "\033[96m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
RED = "\033[91m"; BOLD = "\033[1m"; DIM = "\033[2m"; RESET = "\033[0m"

def step(n, text):  print(f"\n{CYAN}{BOLD}[Step {n}]{RESET} {text}")
def ok(text):       print(f"  {GREEN}+{RESET} {text}")
def warn(text):     print(f"  {YELLOW}!{RESET} {text}")
def fail(text):     print(f"  {RED}x{RESET} {text}")


def load_config() -> dict:
    config_path = os.path.join(ROOT, "matrix.config.json")
    if not os.path.exists(config_path):
        fail(f"Config not found: {config_path}")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


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
    attestation_uids = []

    # ── Step 1: Create attestation for contract deployment ──────────
    step(1, "Attesting a sample contract-deployment record...")

    try:
        result = await dispatcher.execute(
            action="create_attestation",
            params={
                "schema_name": "contract_deployment",
                "data": {
                    "action": "deploy_contract",
                    "contract_name": "RentalAgreement",
                    "contract_address": "0x1234567890abcdef1234567890abcdef12345678",
                    "deployer": wallet,
                    "chain_id": 84532,
                    "bytecode_hash": "0xabc123def456...",
                    "audit_passed": True,
                    "compiler_version": "solc-0.8.24",
                },
                "recipient": wallet,
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            att = data["result"]
            # The service answers with a transaction hash when it submitted
            # the attestation, or a queue receipt; it never returns an EAS UID.
            if att.get("uid"):
                attestation_uids.append(att["uid"])
            ok(f"Status: {att.get('status', 'unknown')}"
               + (f", tx {att['attestation_tx']}" if att.get("attestation_tx") else ""))
            ok(f"Action: deploy_contract")
            ok(f"Schema: contract_deployment")
            ok(f"Recipient: {wallet}")
            if att.get("block_number"):
                ok(f"Block: {att['block_number']}")
        else:
            warn(f"Attestation: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Attestation: {e}")

    # ── Step 2: Attest ownership transfer ───────────────────────────
    step(2, "Attesting a sample ownership-transfer record...")

    new_owner = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"

    try:
        result = await dispatcher.execute(
            action="create_attestation",
            params={
                "schema_name": "platform_action",
                "data": {
                    "action": "transfer_rwa_ownership",
                    "asset_id": "rwa-house-001",
                    "from_owner": wallet,
                    "to_owner": new_owner,
                    "asset_type": "real_estate",
                    "valuation_eth": 150.0,
                },
                "recipient": new_owner,
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            att = data["result"]
            # The service answers with a transaction hash when it submitted
            # the attestation, or a queue receipt; it never returns an EAS UID.
            if att.get("uid"):
                attestation_uids.append(att["uid"])
            ok(f"Status: {att.get('status', 'unknown')}"
               + (f", tx {att['attestation_tx']}" if att.get("attestation_tx") else ""))
            ok(f"Action: transfer_rwa_ownership")
            ok(f"From: {wallet[:12]}...")
            ok(f"To: {new_owner[:12]}...")
        else:
            warn(f"Attestation: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Attestation: {e}")

    # ── Step 3: Attest insurance creation ───────────────────────────
    step(3, "Attesting a sample insurance-policy record...")

    try:
        result = await dispatcher.execute(
            action="create_attestation",
            params={
                "schema_name": "platform_action",
                "data": {
                    "action": "create_insurance",
                    "policy_id": "policy-crop-001",
                    "policyholder": wallet,
                    "coverage_eth": 5.0,
                    "premium_eth": 0.25,
                    "type": "parametric_crop",
                    "trigger": "rainfall_below_50mm",
                },
                "recipient": wallet,
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            att = data["result"]
            # The service answers with a transaction hash when it submitted
            # the attestation, or a queue receipt; it never returns an EAS UID.
            if att.get("uid"):
                attestation_uids.append(att["uid"])
            ok(f"Status: {att.get('status', 'unknown')}"
               + (f", tx {att['attestation_tx']}" if att.get("attestation_tx") else ""))
            ok(f"Action: create_insurance")
            ok(f"Policy: policy-crop-001")
        else:
            warn(f"Attestation: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Attestation: {e}")

    # ── Step 4: Batch attestation ───────────────────────────────────
    step(4, "Attesting three sample records with batch_attest...")

    try:
        result = await dispatcher.execute(
            action="batch_attest",
            params={
                "attestations": [
                    {
                        "schema_name": "platform_action",
                        "data": {"action": "mint_nft", "token_id": 1, "collection": "GART"},
                        "recipient": wallet,
                    },
                    {
                        "schema_name": "platform_action",
                        "data": {"action": "create_loan", "loan_id": "loan-001", "amount": 100},
                        "recipient": wallet,
                    },
                    {
                        "schema_name": "platform_action",
                        "data": {"action": "stake", "amount": 10, "token": "USDC"},
                        "recipient": wallet,
                    },
                ],
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            # One result per entry: each is queued or, if time-critical,
            # submitted on its own. There is no single batch transaction.
            batch = data["result"] if isinstance(data["result"], list) else []
            ok(f"batch_attest processed {len(batch)} records")
            for entry in batch:
                ok(f"  {entry.get('status', 'unknown')}"
                   + (f": {entry['attestation_tx']}" if entry.get("attestation_tx") else ""))
        else:
            warn(f"Batch attestation: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Batch attestation: {e}")

    # (A "query all attestations for this address" step stood here. It
    # dispatched `query_attestations`, which NEW-48b removed: it returned the
    # GraphQL query TEXT as if it were results, and no EAS subgraph reader
    # exists in this repo. The example printed "Unknown action" and then listed
    # the query among the "Actions demonstrated".)

    # ── Step 5: Verify a specific attestation ───────────────────────
    step(5, "Verifying attestation on-chain...")

    if attestation_uids:
        uid_to_verify = attestation_uids[0]
        try:
            result = await dispatcher.execute(
                action="verify_attestation",
                params={"attestation_uid": uid_to_verify},
            )
            data = json.loads(result)
            if data.get("status") == "ok":
                verification = data["result"]
                ok(f"UID: {uid_to_verify}")
                ok(f"Verified: {verification.get('verified', 'N/A')}")
                ok(f"Exists on-chain: {verification.get('exists', 'N/A')}")
                ok(f"Revoked: {verification.get('revoked', False)}")
                ok(f"Attester: {verification.get('attester', 'N/A')}")
            else:
                warn(f"Verification: {data.get('error', 'N/A')}")
        except Exception as e:
            warn(f"Verification: {e}")
    else:
        warn("No attestation UID to verify: the service returned transaction hashes "
             "or queue receipts, not EAS UIDs")

    # ── Summary: the attestation chain ──────────────────────────────
    print(f"\n{BOLD}  The sample records this example asked to attest:{RESET}\n")

    chain = [
        ("deploy_contract",         "sample record: RentalAgreement deployment"),
        ("transfer_rwa_ownership",  "sample record: house ownership transfer"),
        ("create_insurance",        "sample record: crop insurance policy"),
        ("mint_nft",                "sample record: NFT #1 mint (batch)"),
        ("create_loan",             "sample record: DeFi loan (batch)"),
        ("stake",                   "sample record: staking (batch)"),
    ]

    for i, (action, desc) in enumerate(chain):
        uid = attestation_uids[i] if i < len(attestation_uids) else "none returned"
        uid_short = str(uid)[:20] + "..." if len(str(uid)) > 20 else uid
        connector = "|" if i < len(chain) - 1 else " "
        print(f"  [{i+1}] {action}")
        print(f"      {DIM}uid: {uid_short}{RESET}")
        print(f"      {DIM}{desc}{RESET}")
        if i < len(chain) - 1:
            print(f"      {DIM}|{RESET}")

    print(f"""
{GREEN}{BOLD}{'=' * 60}
  EAS ATTESTATION CHAIN COMPLETE
{'=' * 60}{RESET}

  {BOLD}Actions demonstrated:{RESET}
    1. create_attestation  - One record
    2. create_attestation  - One record
    3. create_attestation  - One record
    4. batch_attest        - Several records, each queued or submitted on its own
    5. verify_attestation  - Verify an attestation on-chain

  {BOLD}What the dispatcher adds:{RESET}
    When an action on its state-modifying list settles, the
    ServiceDispatcher hands the attestation service a record of it
    (action, service, actor, a parameter hash, a timestamp), queued
    like any record that is not time-critical. A refusal is logged,
    not attested.

  {BOLD}EAS contract:{RESET} {bc.get('eas_contract', 'see config')}
  {BOLD}Network:{RESET} Base Sepolia

{GREEN}{'=' * 60}{RESET}
""")


if __name__ == "__main__":
    asyncio.run(main())
