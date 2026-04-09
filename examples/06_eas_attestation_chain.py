#!/usr/bin/env python3
from __future__ import annotations
"""
06 — EAS Attestation Chain: Every Action Creates a Verifiable Record

Demonstrates how 0pnMatrx uses Ethereum Attestation Service (EAS) to
create permanent, verifiable on-chain records for every platform action:

  1. Deploy a contract -> attestation
  2. Transfer ownership -> attestation
  3. Create an insurance policy -> attestation
  4. Query all attestations for an address
  5. Verify a specific attestation on-chain

This is the trust layer of 0pnMatrx: every state-modifying action across
all 30 services is attested on-chain automatically.

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
    config_path = os.path.join(ROOT, "openmatrix.config.json")
    if not os.path.exists(config_path):
        fail(f"Config not found: {config_path}")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


async def main():
    print(f"""
{CYAN}{BOLD}{'=' * 60}
  0pnMatrx Example 06: EAS Attestation Chain
{'=' * 60}{RESET}

  Every action on 0pnMatrx creates an on-chain attestation
  via Ethereum Attestation Service (EAS) on Base Sepolia.
  This provides a permanent, verifiable audit trail.
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)
    bc = config.get("blockchain", {})
    wallet = bc.get("demo_wallet_address", "0xDemoWallet")
    attestation_uids = []

    # ── Step 1: Create attestation for contract deployment ──────────
    step(1, "Attesting a contract deployment...")

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
            uid = att.get("uid", att.get("attestation_tx", "N/A"))
            attestation_uids.append(uid)
            ok(f"Attestation UID: {uid}")
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
    step(2, "Attesting an ownership transfer...")

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
            uid = att.get("uid", att.get("attestation_tx", "N/A"))
            attestation_uids.append(uid)
            ok(f"Attestation UID: {uid}")
            ok(f"Action: transfer_rwa_ownership")
            ok(f"From: {wallet[:12]}...")
            ok(f"To: {new_owner[:12]}...")
        else:
            warn(f"Attestation: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Attestation: {e}")

    # ── Step 3: Attest insurance creation ───────────────────────────
    step(3, "Attesting an insurance policy creation...")

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
            uid = att.get("uid", att.get("attestation_tx", "N/A"))
            attestation_uids.append(uid)
            ok(f"Attestation UID: {uid}")
            ok(f"Action: create_insurance")
            ok(f"Policy: policy-crop-001")
        else:
            warn(f"Attestation: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Attestation: {e}")

    # ── Step 4: Batch attestation ───────────────────────────────────
    step(4, "Creating batch attestation (multiple actions at once)...")

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
                        "data": {"action": "stake", "amount": 10, "token": "0pnMTX"},
                        "recipient": wallet,
                    },
                ],
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            batch = data["result"]
            count = batch.get("count", batch.get("attested", 3))
            ok(f"Batch attested: {count} actions in one transaction")
            if isinstance(batch.get("uids"), list):
                for uid in batch["uids"]:
                    attestation_uids.append(uid)
                    ok(f"  UID: {uid}")
        else:
            warn(f"Batch attestation: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Batch attestation: {e}")

    # ── Step 5: Query attestations for address ──────────────────────
    step(5, "Querying all attestations for wallet address...")

    try:
        result = await dispatcher.execute(
            action="query_attestations",
            params={
                "recipient": wallet,
                "limit": 20,
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            attestations = data["result"]
            if isinstance(attestations, list):
                ok(f"Found {len(attestations)} attestations for {wallet[:12]}...")
                for att in attestations[:5]:
                    print(f"    {DIM}[{att.get('action', att.get('schema', 'N/A'))}] "
                          f"uid={str(att.get('uid', 'N/A'))[:16]}... "
                          f"time={att.get('timestamp', 'N/A')}{RESET}")
            elif isinstance(attestations, dict):
                items = attestations.get("attestations", attestations.get("items", []))
                ok(f"Found {len(items)} attestations")
        else:
            warn(f"Query: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Query: {e}")

    # ── Step 6: Verify a specific attestation ───────────────────────
    step(6, "Verifying attestation on-chain...")

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
        warn("No attestation UIDs to verify (attestation service may not be fully configured)")

    # ── Summary: the attestation chain ──────────────────────────────
    print(f"\n{BOLD}  Attestation Chain Visualisation:{RESET}\n")

    chain = [
        ("deploy_contract",         "RentalAgreement deployed"),
        ("transfer_rwa_ownership",  "House ownership transferred"),
        ("create_insurance",        "Crop insurance created"),
        ("mint_nft",                "NFT #1 minted (batch)"),
        ("create_loan",             "DeFi loan created (batch)"),
        ("stake",                   "Tokens staked (batch)"),
    ]

    for i, (action, desc) in enumerate(chain):
        uid = attestation_uids[i] if i < len(attestation_uids) else "pending..."
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
    1. create_attestation  - Individual action attestation
    2. create_attestation  - Ownership transfer attestation
    3. create_attestation  - Insurance policy attestation
    4. batch_attest        - Multiple attestations in one tx
    5. query_attestations  - Find all attestations for address
    6. verify_attestation  - Verify attestation on-chain

  {BOLD}Key insight:{RESET}
    Every state-modifying action across all 30 services
    automatically creates an EAS attestation. The ServiceDispatcher
    handles this transparently — no extra code needed.

  {BOLD}EAS contract:{RESET} {bc.get('eas_contract', 'see config')}
  {BOLD}Network:{RESET} Base Sepolia

{GREEN}{'=' * 60}{RESET}
""")


if __name__ == "__main__":
    asyncio.run(main())
