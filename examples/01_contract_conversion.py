from __future__ import annotations
#!/usr/bin/env python3
"""
01 — Contract Conversion: End-to-End Pipeline

Demonstrates the full 0pnMatrx contract conversion flow on Base Sepolia:

  1. Takes a plain English rental agreement description
  2. Converts it to optimised Solidity via ContractConversionService
  3. Runs Glasswing (Morpheus) security audit
  4. Deploys the compiled contract to Base Sepolia
  5. Creates an EAS attestation for the deployment

This is the core value proposition of 0pnMatrx: describe a contract in
plain English and the platform handles parsing, generation, auditing,
compilation, deployment, and attestation.

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

    # ── Step 4: Deploy to Base Sepolia ──────────────────────────────
    step(4, "Deploying to Base Sepolia...")
    bc = config.get("blockchain", {})
    rpc_url = bc.get("rpc_url", "")
    private_key = bc.get("demo_wallet_private_key", "")

    if not rpc_url or rpc_url.startswith("YOUR_"):
        warn("Skipping deployment: blockchain.rpc_url not configured.")
        warn("Set blockchain.rpc_url in openmatrix.config.json to deploy.")
    elif not private_key or private_key.startswith("YOUR_"):
        warn("Skipping deployment: blockchain.demo_wallet_private_key not configured.")
        warn("Set blockchain.demo_wallet_private_key in openmatrix.config.json to deploy.")
    else:
        try:
            deploy_result = await dispatcher.execute(
                action="deploy_contract",
                params={
                    "source_code": generated,
                    "source_lang": "solidity",
                    "target_chain": "base",
                },
            )
            deploy = json.loads(deploy_result)
            if deploy.get("status") == "ok":
                dep = deploy["result"]
                ok(f"Contract deployed at: {dep.get('contract_address', 'N/A')}")
                ok(f"Tx hash: {dep.get('tx_hash', 'N/A')}")
                ok(f"Block: {dep.get('block_number', 'N/A')}")
                ok(f"Gas used: {dep.get('gas_used', 'N/A')}")
                ok(f"Gas paid by: {dep.get('gas_paid_by', 'platform')}")

                contract_address = dep.get("contract_address", "")

                # ── Step 5: Create EAS attestation ──────────────────
                step(5, "Creating EAS attestation for deployment...")
                try:
                    attest_result = await dispatcher.execute(
                        action="create_attestation",
                        params={
                            "schema_name": "contract_deployment",
                            "data": {
                                "contract_address": contract_address,
                                "contract_name": conv.get("contract_name", "RentalAgreement"),
                                "deployer": bc.get("demo_wallet_address", ""),
                                "chain": "base-sepolia",
                                "audit_passed": audit_passed,
                            },
                            "recipient": bc.get("demo_wallet_address", "0x0"),
                        },
                    )
                    attest = json.loads(attest_result)
                    if attest.get("status") == "ok":
                        att = attest["result"]
                        ok(f"Attestation created: {att.get('uid', att.get('attestation_tx', 'N/A'))}")
                        ok(f"Attestation status: {att.get('status', 'ok')}")
                    else:
                        warn(f"Attestation: {attest.get('error', 'failed')}")
                except Exception as e:
                    warn(f"EAS attestation failed (non-critical): {e}")

                # ── Summary ─────────────────────────────────────────
                explorer = "https://sepolia.basescan.org"
                print(f"""
{GREEN}{BOLD}{'=' * 60}
  PIPELINE COMPLETE
{'=' * 60}{RESET}

  {BOLD}Input:{RESET}       Plain English rental agreement (pseudocode)
  {BOLD}Output:{RESET}      Deployed + Attested Solidity contract
  {BOLD}Contract:{RESET}    {contract_address}
  {BOLD}Explorer:{RESET}    {explorer}/address/{contract_address}
  {BOLD}Network:{RESET}     Base Sepolia (chain 84532)
  {BOLD}Audit:{RESET}       {"PASSED" if audit_passed else "COMPLETED"}

{GREEN}{'=' * 60}{RESET}
""")
            else:
                warn(f"Deployment returned: {deploy.get('error', 'unknown')}")
                warn("This may be expected if your wallet lacks Base Sepolia ETH.")
                warn("Get test ETH: https://www.alchemy.com/faucets/base-sepolia")
        except Exception as e:
            warn(f"Deployment failed: {e}")
            warn("Ensure you have Base Sepolia ETH in your demo wallet.")

    print(f"\n{DIM}Pipeline complete. This example demonstrated the full")
    print(f"contract conversion flow: pseudocode -> Solidity -> audit -> deploy -> attest.{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
