#!/usr/bin/env python3
from __future__ import annotations
"""
07 — Revenue to NeoSafe: Platform Fee Routing and Tracking

Demonstrates how 0pnMatrx routes revenue to the NeoSafe multisig wallet:

  1. A contract conversion generates a platform fee
  2. The RevenueEnforcer injects fee logic into the contract
  3. The NeoSafeRouter records and routes the fee
  4. An EAS attestation is created for the payment
  5. Revenue totals are queried from the ledger

Every fee-generating action across all 30 services follows this pattern.
The platform wallet (NeoSafe) is the single point of revenue collection.

Usage:
    python examples/07_revenue_to_neosafe.py
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
  0pnMatrx Example 07: Revenue Routing to NeoSafe
{'=' * 60}{RESET}

  All platform fees flow to the NeoSafe multisig wallet.
  Every payment is attested on-chain for full transparency.
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)
    bc = config.get("blockchain", {})
    platform_wallet = bc.get("platform_wallet", "0xNeoSafeWallet")

    print(f"  {BOLD}NeoSafe wallet:{RESET} {platform_wallet}")
    print(f"  {BOLD}Fee basis points:{RESET} {bc.get('platform_fee_bps', 250)} (2.5%)")

    # ── Step 1: Show RevenueEnforcer injection ──────────────────────
    step(1, "RevenueEnforcer: Injecting fee logic into a contract...")

    try:
        from runtime.blockchain.services.contract_conversion.revenue_enforcer import RevenueEnforcer

        enforcer = RevenueEnforcer(config)

        sample_contract = """\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract SimpleToken {
    address public owner;
    mapping(address => uint256) public balanceOf;

    constructor() {
        owner = msg.sender;
    }

    function mint(address to, uint256 amount) external {
        require(msg.sender == owner, "Not owner");
        balanceOf[to] += amount;
    }
}"""

        ok("Original contract: 13 lines, no fee logic")

        # Check if platform_wallet is configured
        if platform_wallet and not platform_wallet.startswith("YOUR_"):
            injected = enforcer.inject_fee_logic(sample_contract)
            injected_lines = len(injected.splitlines())
            ok(f"After injection: {injected_lines} lines with fee logic")
            ok(f"Fee recipient: {platform_wallet}")
            ok(f"Fee bps: {bc.get('platform_fee_bps', 250)}")

            print(f"\n  {DIM}Injected elements:{RESET}")
            print(f"    - platformFeeRecipient state variable")
            print(f"    - platformFeeBps state variable")
            print(f"    - collectPlatformFee modifier")
            print(f"    - _collectERC20Fee internal helper")
            print(f"    - setPlatformFeeRecipient (owner-only)")
            print(f"    - Constructor initialisation")
        else:
            warn("platform_wallet not configured — showing injection pattern only")
            print(f"\n  {DIM}The RevenueEnforcer would inject:{RESET}")
            print(f"    - platformFeeRecipient = <NeoSafe address>")
            print(f"    - platformFeeBps = 250 (2.5%)")
            print(f"    - collectPlatformFee modifier on payable functions")
            print(f"    - Owner-only setters for fee config")
    except Exception as e:
        warn(f"RevenueEnforcer demo: {e}")

    # ── Step 2: Simulate fee-generating actions ─────────────────────
    step(2, "Simulating fee-generating platform actions...")

    # Use NeoSafeRouter directly to demonstrate fee routing
    try:
        from runtime.blockchain.services.neosafe import NeoSafeRouter

        router = NeoSafeRouter(config)

        fees = [
            (0.005, "ETH",  "contract_conversion", "Contract conversion: RentalAgreement"),
            (0.001, "ETH",  "nft_services",        "NFT collection deployment: GART"),
            (2.50,  "USDC", "marketplace",          "Marketplace sale: ERC-20 template"),
            (0.25,  "ETH",  "insurance",            "Insurance premium: crop policy"),
            (0.002, "ETH",  "defi",                 "DeFi loan origination fee"),
        ]

        for amount, token, source, desc in fees:
            receipt = await router.route_fee(
                amount=amount,
                token=token,
                source=source,
                description=desc,
            )
            if receipt.get("status") == "ok":
                fee = receipt["fee"]
                attestation = fee.get("attestation_uid", "pending")
                ok(f"{amount:8.4f} {token:4s} from {source:25s} (attested: {attestation or 'N/A'})")
            else:
                warn(f"Fee routing: {receipt.get('reason', 'N/A')}")

    except Exception as e:
        warn(f"NeoSafeRouter: {e}")
        # Show the fees conceptually
        print(f"\n  {DIM}Fee routing pattern (conceptual):{RESET}")
        print(f"    0.0050 ETH  <- contract_conversion")
        print(f"    0.0010 ETH  <- nft_services")
        print(f"    2.5000 USDC <- marketplace")
        print(f"    0.2500 ETH  <- insurance")
        print(f"    0.0020 ETH  <- defi")

    # ── Step 3: Query total revenue ─────────────────────────────────
    step(3, "Querying accumulated revenue totals...")

    try:
        totals = await router.get_total_revenue()
        ok(f"Platform wallet: {totals.get('platform_wallet', platform_wallet)}")
        ok(f"Total fees recorded: {totals.get('total_fee_count', 'N/A')}")

        by_token = totals.get("totals_by_token", {})
        if by_token:
            print(f"\n  {BOLD}Revenue by token:{RESET}")
            print(f"  {DIM}{'─' * 35}{RESET}")
            for token, total in by_token.items():
                print(f"    {token:6s}: {total:.4f}")
            print(f"  {DIM}{'─' * 35}{RESET}")
    except Exception as e:
        warn(f"Revenue query: {e}")

    # ── Step 4: Show the fee flow diagram ───────────────────────────
    step(4, "Platform fee flow architecture")

    print(f"""
  {BOLD}Fee Flow:{RESET}

  User Action (any of 30 services)
       |
       v
  ServiceDispatcher.execute()
       |
       +---> Service Method (e.g., defi.create_loan)
       |         |
       |         v
       |     RevenueEnforcer (injects fee logic into contracts)
       |
       +---> _attest_action() (EAS attestation)
       |
       v
  NeoSafeRouter.route_fee()
       |
       +---> Record in ledger
       +---> Attest fee payment (EAS)
       +---> Route to NeoSafe wallet
       |
       v
  {GREEN}NeoSafe Multisig Wallet{RESET}
  {DIM}({platform_wallet}){RESET}
""")

    # ── Step 5: Show contract-level fee collection ──────────────────
    step(5, "Contract-level fee collection example")

    print(f"""  {DIM}When a user interacts with a deployed contract that has
  fee logic injected by RevenueEnforcer:{RESET}

  {BOLD}Solidity (injected):{RESET}
  {DIM}
    modifier collectPlatformFee(uint256 amount) {{
        uint256 fee = (amount * platformFeeBps) / 10000;
        if (fee > 0) {{
            payable(platformFeeRecipient).transfer(fee);
        }}
        _;
    }}

    function deposit() external payable collectPlatformFee(msg.value) {{
        // User deposits 1 ETH
        // 0.025 ETH (2.5%) goes to NeoSafe automatically
        // 0.975 ETH goes to the contract
        balanceOf[msg.sender] += msg.value - fee;
    }}
  {RESET}""")

    print(f"""
{GREEN}{BOLD}{'=' * 60}
  REVENUE TO NEOSAFE COMPLETE
{'=' * 60}{RESET}

  {BOLD}Components demonstrated:{RESET}
    1. RevenueEnforcer  - Injects fee logic into contracts
    2. NeoSafeRouter    - Routes fees with attestation
    3. EAS              - Every payment attested on-chain
    4. ServiceDispatcher - Automatic attestation on every action

  {BOLD}Revenue sources:{RESET}
    - Contract conversions (Component 1)
    - NFT deployments (Component 3)
    - Marketplace sales (Component 24)
    - Insurance premiums (Component 13)
    - DeFi origination (Component 2)
    - ... and all other fee-generating services

  {BOLD}NeoSafe wallet:{RESET} {platform_wallet}

{GREEN}{'=' * 60}{RESET}
""")


if __name__ == "__main__":
    asyncio.run(main())
