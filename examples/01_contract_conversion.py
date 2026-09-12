#!/usr/bin/env python3
from __future__ import annotations
"""
01 — Contract Conversion: End-to-End Pipeline

Demonstrates the 0pnMatrx contract conversion flow, targeting Base:

  1. Takes a plain English rental agreement description
  2. Estimates the conversion cost
  3. Converts it to Solidity via ContractConversionService, which runs the
     Glasswing (Morpheus) security audit on the result
  4. Hands the Solidity back to you — 0pnMatrx does not deploy it

This example needs no private key and signs nothing. demo.py is the script
that deploys, with a dedicated testnet wallet of your own.

Usage:
    python examples/01_contract_conversion.py
"""

import asyncio
import json
import os
import sys
import time

# Ensure repo root is importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

# ── Colours ──────────────────────────────────────────────────────────
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
        fail("Copy openmatrix.config.json.example to openmatrix.config.json and fill in your credentials.")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


# ── The rental agreement we want to convert ─────────────────────────

RENTAL_AGREEMENT_PSEUDOCODE = """\
contract RentalAgreement

    state landlord: address
    state tenant: address
    state monthlyRent: uint256
    state deposit: uint256
    state leaseStart: uint256
    state leaseEnd: uint256
    state isActive: bool
    state rentPaid: map

    event LeaseCreated(address indexed landlord, address indexed tenant, uint256 rent)
    event RentPaid(address indexed tenant, uint256 month, uint256 amount)
    event DepositReturned(address indexed tenant, uint256 amount)
    event LeaseTerminated(address indexed by, uint256 timestamp)

    function constructor(tenantAddr: address, rent: uint256, durationMonths: uint256)
        landlord = msg.sender
        tenant = tenantAddr
        monthlyRent = rent
        deposit = rent * 2
        leaseStart = block.timestamp
        leaseEnd = block.timestamp + (durationMonths * 30 days)
        isActive = true
        emit LeaseCreated(landlord, tenant, rent)

    payable function payRent(month: uint256)
        require(msg.sender == tenant, "Only tenant can pay rent")
        require(isActive, "Lease not active")
        require(msg.value == monthlyRent, "Must pay exact rent")
        require(!rentPaid[month], "Already paid")
        rentPaid[month] = true
        payable(landlord).transfer(msg.value)
        emit RentPaid(tenant, month, msg.value)

    function terminateLease()
        require(msg.sender == landlord || msg.sender == tenant, "Unauthorized")
        require(isActive, "Already terminated")
        isActive = false
        emit LeaseTerminated(msg.sender, block.timestamp)

    function returnDeposit()
        require(msg.sender == landlord, "Only landlord")
        require(!isActive, "Lease still active")
        payable(tenant).transfer(deposit)
        emit DepositReturned(tenant, deposit)

    view function getLeaseInfo() -> (address, address, uint256, uint256, bool)
        return (landlord, tenant, monthlyRent, leaseEnd, isActive)
"""


async def main():
    print(f"""
{CYAN}{BOLD}{'=' * 60}
  0pnMatrx Example 01: Contract Conversion Pipeline
{'=' * 60}{RESET}
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)

    # ── Step 1: Show the input ──────────────────────────────────────
    step(1, "Input: Plain English Rental Agreement (pseudocode)")
    print(f"{DIM}")
    for line in RENTAL_AGREEMENT_PSEUDOCODE.strip().splitlines():
        print(f"    {line}")
    print(f"{RESET}")

    # ── Step 2: Estimate conversion cost ────────────────────────────
    step(2, "Estimating conversion cost...")
    try:
        estimate_result = await dispatcher.execute(
            action="estimate_contract_cost",
            params={"source_code": RENTAL_AGREEMENT_PSEUDOCODE},
        )
        estimate = json.loads(estimate_result)
        if estimate.get("status") == "ok":
            est = estimate["result"]
            ok(f"Tier: {est.get('tier', 'N/A')}")
            ok(f"Estimated fee: {est.get('fee_display', 'N/A')}")
            ok(f"Lines: {est.get('line_count', 'N/A')}")
            ok(f"Complexity: {est.get('complexity_score', 'N/A')}")
        else:
            warn(f"Estimate returned: {estimate.get('error', 'unknown error')}")
    except Exception as e:
        warn(f"Cost estimation failed (non-critical): {e}")

    # ── Step 3: Convert to Solidity ─────────────────────────────────
    step(3, "Converting pseudocode to optimised Solidity via ContractConversionService...")
    t0 = time.monotonic()
    try:
        convert_result = await dispatcher.execute(
            action="convert_contract",
            params={
                "source_code": RENTAL_AGREEMENT_PSEUDOCODE,
                "source_lang": "pseudocode",
                "target_chain": "base",
            },
        )
        elapsed = (time.monotonic() - t0) * 1000
        result = json.loads(convert_result)

        if result.get("status") != "ok":
            fail(f"Conversion failed: {result.get('error', 'unknown')}")
            sys.exit(1)

        conv = result["result"]
        ok(f"Contract name: {conv.get('contract_name', 'N/A')}")
        ok(f"Target chain: {conv.get('target_chain', 'N/A')}")
        ok(f"Conversion time: {conv.get('conversion_time_ms', elapsed):.1f}ms")
        ok(f"Tier: {conv.get('tier', {}).get('tier', 'N/A')}")

        # Show audit results
        audit = conv.get("audit", {})
        audit_passed = conv.get("audit_passed", None)
        if audit_passed is True:
            ok(f"Security audit: PASSED")
        elif audit_passed is False:
            warn(f"Security audit: FAILED — {audit.get('summary', 'see details')}")
        else:
            ok("Security audit: completed")

        if audit.get("findings"):
            for finding in audit["findings"][:3]:
                severity = finding.get("severity", "info")
                msg = finding.get("message", finding.get("description", ""))
                print(f"    {DIM}[{severity}] {msg}{RESET}")

        # Show generated Solidity
        generated = conv.get("generated_source", "")
        if generated:
            print(f"\n{DIM}{'=' * 50}")
            print("Generated Solidity:")
            print(f"{'=' * 50}{RESET}")
            for i, line in enumerate(generated.splitlines()[:40], 1):
                print(f"  {DIM}{i:3d}{RESET}  {line}")
            if len(generated.splitlines()) > 40:
                print(f"  {DIM}... ({len(generated.splitlines()) - 40} more lines){RESET}")
            print(f"{DIM}{'=' * 50}{RESET}")

    except Exception as e:
        fail(f"Conversion failed: {e}")
        fail("Make sure all dependencies are installed: pip install web3 eth-account py-solc-x")
        sys.exit(1)

    # ── Step 4: What happens to the Solidity ────────────────────────
    # This step used to read blockchain.demo_wallet_private_key, print
    # "Deploying to Base Sepolia..." and dispatch `deploy_contract` — an action
    # the platform removed (NEW-4). It could never deploy anything, and it
    # explained the certain failure as an unfunded wallet. The platform
    # generates Solidity; deploying it is yours to do, with your own tooling.
    step(4, "Deployment")
    deployment = conv.get("deployment") if isinstance(conv, dict) else None
    if isinstance(deployment, dict):
        # Only present when the operator turned on contract_conversion.auto_deploy.
        # Relayed exactly as the conversion service reported it.
        detail = deployment.get("contract_address") or deployment.get("reason") or deployment.get("error", "")
        warn(f"Conversion service deployment status: {deployment.get('status', 'unknown')} {detail}".rstrip())
    else:
        ok("Not deployed. 0pnMatrx generates the contract; it does not deploy it for you.")
        ok("Deploy the Solidity above with your own tooling (Foundry, Hardhat, Remix).")
        ok("demo.py shows one way, using a dedicated TESTNET wallet you configure —")
        ok("never a wallet holding real funds.")

    print(f"\n{DIM}Pipeline complete. This example demonstrated the contract")
    print(f"conversion flow: pseudocode -> Solidity -> audit.{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
