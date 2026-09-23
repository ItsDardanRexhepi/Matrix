#!/usr/bin/env python3
from __future__ import annotations
"""
07 — Revenue to NeoSafe: Platform Fee Routing and Tracking

Demonstrates the NeoSafe router, called directly by this example:

  1. The RevenueEnforcer injects fee logic into a sample contract
  2. NeoSafeRouter.route_fee records sample fees on its in-memory ledger and
     hands each one to the attestation service, which queues it
  3. Revenue totals are read back from that ledger
  4. Where the platform's fees actually go
  5. What the injected fee logic does on-chain

No service follows this pattern today. This example is the only caller of
NeoSafeRouter.route_fee, which records a fee and moves no value. Nothing outside
the tests calls `route_revenue`, the method that sends ETH to the multisig
when a chain is configured. The platform's fees go where docs/blockchain.md
lists them under Fees (each contract's platformFeeRecipient,
blockchain.platform_wallet for injected conversion fees, service ledgers).
The canonical NeoSafe address is
``0x46fF491D7054A6F500026B3E81f358190f8d8Ec5``.

Usage:
    python examples/07_revenue_to_neosafe.py
"""

import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from runtime.blockchain.services.service_dispatcher import ServiceDispatcher  # noqa: F401  (patched by the example tests)

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
  The Matrix Example 07: Revenue Routing to NeoSafe
{'=' * 60}{RESET}

  The platform contracts pay their fees to platformFeeRecipient, which
  scripts/deploy_all.py sets to the configured NeoSafe address. The router
  shown here records fees in memory and moves no value; this example is the
  only caller of its route_fee.
""")

    config = load_config()
    bc = config.get("blockchain", {})
    platform_wallet = bc.get("platform_wallet", "0xNeoSafeWallet")
    fee_bps = int(bc.get("platform_fee_bps", 250))

    print(f"  {BOLD}NeoSafe wallet:{RESET} {platform_wallet}")
    print(f"  {BOLD}Injected fee:{RESET} {fee_bps} bps ({fee_bps / 100:g}%)")

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
            ok(f"Fee bps: {fee_bps}")

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
            print(f"    - platformFeeBps = {fee_bps} ({fee_bps / 100:g}%)")
            print(f"    - collectPlatformFee modifier on payable functions")
            print(f"    - Owner-only setters for fee config")
    except Exception as e:
        warn(f"RevenueEnforcer demo: {e}")

    # ── Step 2: Record sample fees with route_fee ───────────────────
    step(2, "Recording sample fees with NeoSafeRouter.route_fee (in memory; nothing moves)...")

    # Sample amounts for five of the fees docs/blockchain.md lists under Fees.
    fees = [
        (0.025, "ETH",  "contract_conversion", "Injected fee: 2.5% of 1 ETH sent to a payable function"),
        (5.00,  "USDC", "marketplace",         "Marketplace sale: 5% of a 100 USDC sale"),
        (0.10,  "USDC", "stablecoin",          "Stablecoin transfer: 0.1% of 100 USDC"),
        (2.50,  "USDC", "cross_border",        "Cross-border payment: 0.5% of 500 USDC"),
        (0.05,  "ETH",  "staking",             "Staking rewards: 5% of 1 ETH of rewards"),
    ]

    try:
        from runtime.blockchain.services.neosafe import NeoSafeRouter

        router = NeoSafeRouter(config)

        for amount, token, source, desc in fees:
            receipt = await router.route_fee(
                amount=amount,
                token=token,
                source=source,
                description=desc,
            )
            if receipt.get("status") == "ok":
                fee = receipt["fee"]
                attestation = fee.get("attestation_uid")
                ok(f"{amount:8.4f} {token:4s} from {source:25s} "
                   f"(attestation tx: {attestation or 'none; queued, not submitted'})")
            else:
                warn(f"Fee routing: {receipt.get('reason', 'N/A')}")

    except Exception as e:
        warn(f"NeoSafeRouter: {e}")
        print(f"\n  {DIM}The sample fees this step would have recorded:{RESET}")
        for amount, token, source, _desc in fees:
            print(f"    {amount:8.4f} {token:4s} <- {source}")

    # ── Step 3: Read back the router's ledger ───────────────────────
    step(3, "Reading the router's in-memory ledger totals...")

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

    # ── Step 4: Where the platform's fees go ────────────────────────
    step(4, "Where the platform's fees go (docs/blockchain.md, Fees)")

    print(f"""
  {BOLD}Platform contracts{RESET} (marketplace, staking, DAO, NFT, insurance)
       |  each pays its fee on-chain to its platformFeeRecipient,
       |  which scripts/deploy_all.py sets to the NeoSafe address
       v
  {GREEN}NeoSafe Multisig Wallet{RESET}

  {BOLD}Generated contracts{RESET} (RevenueEnforcer)
       |  pay the injected fee on-chain
       v
  blockchain.platform_wallet {DIM}({platform_wallet}){RESET}

  {BOLD}Service-ledger fees{RESET} (stablecoin, cross-border, service staking, ...)
       computed and recorded on the service's own ledger; nothing moves them

  {BOLD}NeoSafeRouter.route_fee{RESET} (this example only)
       records a fee in memory and queues its attestation; moves no value
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
        // 0.025 ETH (2.5%) goes to platformFeeRecipient (blockchain.platform_wallet)
        // 0.975 ETH goes to the contract
        balanceOf[msg.sender] += msg.value - fee;
    }}
  {RESET}""")

    print(f"""
{GREEN}{BOLD}{'=' * 60}
  EXAMPLE 07 COMPLETE
{'=' * 60}{RESET}

  {BOLD}Components demonstrated:{RESET}
    1. RevenueEnforcer  - Injects fee logic into a generated contract
    2. NeoSafeRouter    - Records a fee in memory and queues its attestation,
                          when called directly, as here; it moves no value

  {BOLD}Every fee and where it goes:{RESET} docs/blockchain.md, under Fees

  {BOLD}NeoSafe wallet:{RESET} {platform_wallet}

{GREEN}{'=' * 60}{RESET}
""")


if __name__ == "__main__":
    asyncio.run(main())
