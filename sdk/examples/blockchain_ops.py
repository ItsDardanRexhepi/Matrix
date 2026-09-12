#!/usr/bin/env python3
"""
0pnMatrx SDK — Blockchain Operations Example

Demonstrates all blockchain capabilities through the SDK.
Gas is paid by the platform within the deployment's sponsorship policy
(a per-identity daily cap when one is configured).
"""

import asyncio
import sys
sys.path.insert(0, ".")

from sdk import OpenMatrixClient


async def main():
    client = OpenMatrixClient("http://localhost:18790")

    # 1. Check price feed
    print("── Oracle: ETH/USD Price ──")
    result = await client.get_price("ETH/USD")
    print(f"Result: {result['response'][:200]}")

    # 2. Deploy a smart contract
    print("\n── Deploy Contract ──")
    contract_source = '''
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract Hello0pnMatrx {
    string public message = "Hello from 0pnMatrx!";

    function setMessage(string memory _msg) public {
        message = _msg;
    }
}
'''
    # NEW-12: this called client.deploy_contract(), which now raises
    # NotImplementedError — the platform does not deploy contracts. The real
    # capability is conversion: it returns Solidity scaffolding you deploy
    # yourself with your own tooling and signer.
    result = await client.convert_contract(contract_source, source_lang="solidity")
    print(f"Result: {str(result)[:200]}")

    # 3. Send a payment
    print("\n── Send Payment ──")
    result = await client.send_payment(
        to="0x0000000000000000000000000000000000000001",
        amount="0.001",
    )
    print(f"Result: {result['response'][:200]}")

    # 4. Create an attestation
    print("\n── EAS Attestation ──")
    result = await client.create_attestation(
        action="sdk_test",
        agent="neo",
        details="Blockchain operations example completed",
    )
    print(f"Result: {result['response'][:200]}")

    # 5. Platform dashboard
    print("\n── Dashboard ──")
    result = await client.ablockchain("dashboard", action="platform_stats")
    print(f"Result: {result['response'][:200]}")

    print("\nAll gas fees were covered by the platform.")


if __name__ == "__main__":
    asyncio.run(main())
