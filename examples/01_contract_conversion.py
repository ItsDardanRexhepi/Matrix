#!/usr/bin/env python3
from __future__ import annotations
"""
01 — Contract Conversion: End-to-End Pipeline

Demonstrates the Matrix contract conversion flow, targeting Base:

  1. Takes a rental agreement written as pseudocode (the converter reads
     structured pseudocode, not free prose)
  2. Estimates the conversion cost
  3. Converts it to Solidity via ContractConversionService, which runs the
     Glasswing security audit on the result
  4. Hands the Solidity back to you — this example does not deploy it

This example reads no private key and does not deploy. The platform CAN deploy
a conversion: with `conversion.auto_deploy` on, ContractConversionService
compiles the result and deploys it with the platform's paymaster account, on
whatever network is configured. So this example runs the platform with
auto_deploy OFF whatever your config says, and tells you if it was on.
demo.py is the script that deploys, with a dedicated testnet wallet of your
own.

What it does not switch off: ServiceDispatcher attests state-modifying actions
such as convert_contract through the attestation service. Where EAS is set up,
that service submits attestations (immediately, or once its batch fills) signed
with the platform's paymaster account (see examples/README.md).

Usage:
    python examples/01_contract_conversion.py
"""

import asyncio
import json
import os
import sys

# Ensure repo root is importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
from examples._steps import BOLD, CYAN, DIM, RESET, Steps, fail, ok, shown, step, warn


def load_config() -> dict:
    config_path = os.path.join(ROOT, "matrix.config.json")
    if not os.path.exists(config_path):
        fail(f"Config not found: {config_path}")
        fail("Copy matrix.config.json.example to matrix.config.json and fill in your credentials.")
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
  The Matrix Example 01: Contract Conversion Pipeline
{'=' * 60}{RESET}
""")

    config = load_config()
    # conversion.auto_deploy makes convert_contract deploy with the platform's
    # paymaster account. An operator may want that for the gateway; running an
    # example must not do it. The dispatcher gets a copy with it off.
    conversion = dict(config.get("conversion") or {})
    if conversion.get("auto_deploy"):
        warn("conversion.auto_deploy is on in your config. This example turns it OFF for its own run,")
        warn("so nothing is deployed with the platform's paymaster account.")
    conversion["auto_deploy"] = False
    dispatcher = ServiceDispatcher({**config, "conversion": conversion})

    # ── Step 1: Show the input ──────────────────────────────────────
    step(1, "Input: Rental Agreement, written as pseudocode")
    print(f"{DIM}")
    for line in RENTAL_AGREEMENT_PSEUDOCODE.strip().splitlines():
        print(f"    {line}")
    print(f"{RESET}")

    steps = Steps(dispatcher)

    # ── Step 2: Estimate conversion cost ────────────────────────────
    step(2, "Estimating conversion cost...")
    est = await steps.run("estimate the cost", "estimate_contract_cost",
                          {"source_code": RENTAL_AGREEMENT_PSEUDOCODE})
    if est is not None:
        ok(f"Tier: {shown(est, 'tier')}")
        ok(f"Quoted fee: {shown(est, 'fee_display')} (a quote; nothing collects it)")
        ok(f"Lines: {shown(est, 'line_count')}")
        ok(f"Complexity: {shown(est, 'complexity_score')}")

    # ── Step 3: Convert to Solidity ─────────────────────────────────
    step(3, "Converting pseudocode to Solidity via ContractConversionService...")
    conv = await steps.run("convert the contract", "convert_contract", {
        "source_code": RENTAL_AGREEMENT_PSEUDOCODE,
        "source_lang": "pseudocode",
        "target_chain": "base",
    })
    if conv is not None:
        ok(f"Contract name: {shown(conv, 'contract_name')}")
        ok(f"Target chain: {shown(conv, 'target_chain')}")
        ok(f"Status: {shown(conv, 'status')}")

        audit = conv.get("audit") or {}
        ok(f"Glasswing verdict: {shown(audit, 'verdict')}")
        for finding in (audit.get("findings") or [])[:3]:
            print(f"    {DIM}[{finding.get('severity', '?')}] {finding.get('rule_id', '')} "
                  f"{finding.get('title', '')} (line {finding.get('line')}){RESET}")

        generated = conv.get("generated_source", "")
        if generated:
            print(f"\n{DIM}{'=' * 50}")
            print("Generated Solidity (a draft: read it and compile it yourself):")
            print(f"{'=' * 50}{RESET}")
            for i, line in enumerate(generated.splitlines()[:40], 1):
                print(f"  {DIM}{i:3d}{RESET}  {line}")
            if len(generated.splitlines()) > 40:
                print(f"  {DIM}... ({len(generated.splitlines()) - 40} more lines){RESET}")
            print(f"{DIM}{'=' * 50}{RESET}")

    # ── Step 4: What happens to the Solidity ────────────────────────
    # This step used to read blockchain.demo_wallet_private_key, print
    # "Deploying to Base Sepolia..." and dispatch `deploy_contract` — an action
    # the platform removed (NEW-4). It could never deploy anything, and it
    # explained the certain failure as an unfunded wallet. The dispatcher above
    # runs with conversion.auto_deploy off, so the service does not deploy
    # either: deploying the Solidity is yours to do, with your own tooling.
    step(4, "Deployment")
    warn("Not deployed. This example generates the contract; it does not deploy it.")
    if conv is None:
        warn("There is no Solidity to deploy: the conversion did not happen.")
    else:
        ok("Compile the Solidity above and deploy it with your own tooling (Foundry, Hardhat, Remix).")
        ok("demo.py shows one way, using a dedicated TESTNET wallet you configure —")
        ok("never a wallet holding real funds.")

    steps.summary("Contract conversion")


if __name__ == "__main__":
    asyncio.run(main())
