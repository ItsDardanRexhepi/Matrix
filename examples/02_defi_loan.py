#!/usr/bin/env python3
from __future__ import annotations
"""
02 — DeFi Loan: Collateralised Lending on Base Sepolia

Demonstrates the DeFi service (Component 2):

  1. Creates a collateralised loan (deposit ETH, borrow USDC)
  2. Queries the loan to check health factor
  3. Monitors the collateral ratio
  4. Repays the loan in full

This shows how 0pnMatrx wraps complex DeFi lending logic into simple
platform_action calls that any AI agent can invoke.

Usage:
    python examples/02_defi_loan.py
"""

import asyncio
import json
import os
import sys
import time

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
        fail("Copy openmatrix.config.json.example and configure it.")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


async def main():
    print(f"""
{CYAN}{BOLD}{'=' * 60}
  0pnMatrx Example 02: DeFi Collateralised Loan
{'=' * 60}{RESET}

  This example creates a DeFi loan on Base Sepolia:
  - Deposit 0.1 ETH as collateral
  - Borrow 100 USDC against it
  - Monitor health factor
  - Repay the loan
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)
    bc = config.get("blockchain", {})
    wallet = bc.get("demo_wallet_address", "0xDemoWallet")

    # ── Step 1: Create the loan ─────────────────────────────────────
    step(1, "Creating collateralised loan...")
    print(f"  {DIM}Collateral: 0.1 ETH | Borrow: 100 USDC | LTV: 75%{RESET}")

    try:
        result = await dispatcher.execute(
            action="create_loan",
            params={
                "borrower": wallet,
                "collateral_token": "ETH",
                "collateral_amount": 0.1,
                "borrow_token": "USDC",
                "borrow_amount": 100.0,
                "ltv_ratio": 0.75,
            },
        )
        loan_data = json.loads(result)

        if loan_data.get("status") == "ok":
            loan = loan_data["result"]
            loan_id = loan.get("loan_id", loan.get("id", "N/A"))
            ok(f"Loan created: {loan_id}")
            ok(f"Collateral locked: {loan.get('collateral_amount', 0.1)} ETH")
            ok(f"Borrowed: {loan.get('borrow_amount', 100.0)} USDC")
            ok(f"Health factor: {loan.get('health_factor', 'N/A')}")
            ok(f"Interest rate: {loan.get('interest_rate', 'N/A')}")
            if loan.get("tx_hash"):
                ok(f"Tx: https://sepolia.basescan.org/tx/{loan['tx_hash']}")
        else:
            warn(f"Loan creation returned: {loan_data.get('error', 'check config')}")
            loan_id = "demo-loan-001"
            warn(f"Using demo loan ID: {loan_id}")
    except Exception as e:
        warn(f"Loan creation: {e}")
        loan_id = "demo-loan-001"
        warn("Continuing with demo loan ID for subsequent steps...")

    # ── Step 2: Query loan status ───────────────────────────────────
    step(2, "Querying loan status and health factor...")

    try:
        result = await dispatcher.execute(
            action="get_loan",
            params={"loan_id": loan_id, "borrower": wallet},
        )
        status_data = json.loads(result)

        if status_data.get("status") == "ok":
            info = status_data["result"]
            ok(f"Loan status: {info.get('status', 'active')}")
            ok(f"Health factor: {info.get('health_factor', 'N/A')}")
            ok(f"Collateral value: ${info.get('collateral_value_usd', 'N/A')}")
            ok(f"Outstanding debt: {info.get('outstanding_debt', 'N/A')} USDC")
            ok(f"Accrued interest: {info.get('accrued_interest', 'N/A')} USDC")

            health = info.get("health_factor", 1.5)
            if isinstance(health, (int, float)):
                if health > 1.5:
                    ok(f"Position is HEALTHY (health > 1.5)")
                elif health > 1.0:
                    warn(f"Position is AT RISK (health between 1.0 and 1.5)")
                else:
                    fail(f"Position is LIQUIDATABLE (health < 1.0)")
        else:
            warn(f"Query returned: {status_data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Loan query: {e}")

    # ── Step 3: Simulate health factor monitoring ───────────────────
    step(3, "Monitoring health factor (simulated price movements)...")

    scenarios = [
        ("ETH at $2,500 (current)", 2500, 1.875),
        ("ETH drops to $2,000",      2000, 1.500),
        ("ETH drops to $1,500",      1500, 1.125),
        ("ETH drops to $1,333",      1333, 1.000),
        ("ETH recovers to $3,000",   3000, 2.250),
    ]

    for label, price, health in scenarios:
        if health > 1.5:
            icon = f"{GREEN}+{RESET}"
            status = "SAFE"
        elif health > 1.0:
            icon = f"{YELLOW}!{RESET}"
            status = "WARNING"
        else:
            icon = f"{RED}x{RESET}"
            status = "LIQUIDATION RISK"
        print(f"  {icon} {label}: health={health:.3f} [{status}]")

    print(f"\n  {DIM}Health factor = (collateral_value * liquidation_threshold) / debt")
    print(f"  If health < 1.0, the position can be liquidated.{RESET}")

    # ── Step 4: Repay the loan ──────────────────────────────────────
    step(4, "Repaying loan in full...")

    try:
        result = await dispatcher.execute(
            action="repay_loan",
            params={
                "loan_id": loan_id,
                "borrower": wallet,
                "repay_amount": 100.0,
                "repay_token": "USDC",
            },
        )
        repay_data = json.loads(result)

        if repay_data.get("status") == "ok":
            repay = repay_data["result"]
            ok(f"Loan repaid: {repay.get('repaid_amount', 100.0)} USDC")
            ok(f"Interest paid: {repay.get('interest_paid', 'N/A')} USDC")
            ok(f"Collateral returned: {repay.get('collateral_returned', 0.1)} ETH")
            ok(f"Loan status: {repay.get('status', 'closed')}")
            if repay.get("tx_hash"):
                ok(f"Tx: https://sepolia.basescan.org/tx/{repay['tx_hash']}")
        else:
            warn(f"Repayment returned: {repay_data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Repayment: {e}")

    # ── Summary ─────────────────────────────────────────────────────
    print(f"""
{GREEN}{BOLD}{'=' * 60}
  DEFI LOAN LIFECYCLE COMPLETE
{'=' * 60}{RESET}

  {BOLD}Actions demonstrated:{RESET}
    1. create_loan   - Deposit collateral, borrow tokens
    2. get_loan      - Query position and health factor
    3. (monitoring)  - Health factor under price scenarios
    4. repay_loan    - Repay debt, recover collateral

  {BOLD}Services used:{RESET}
    - DeFi Service (Component 2)
    - Oracle Gateway (Component 11) for price feeds
    - Attestation Service (Component 8) for on-chain receipts

{GREEN}{'=' * 60}{RESET}
""")


if __name__ == "__main__":
    asyncio.run(main())
