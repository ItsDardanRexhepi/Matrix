#!/usr/bin/env python3
"""
The Matrix SDK — Blockchain Operations Example

Five blockchain calls through the SDK: a price read, a contract conversion,
a payment, an attestation and the platform dashboard. Every one of them is a
chat message to Neo (MatrixClient.ablockchain sends POST /chat naming him),
so what comes back is his reply.

Naming Neo takes the operator key on a gateway that has one set. The
example passes MATRIX_API_KEY from the environment as MatrixClient's
api_key; without it, against a gateway with a key set, the first call is
refused with a 403 and the example stops there. A gateway with no key set
(development) treats whoever runs it as the operator.

Whether the platform pays the gas depends on the deployment: with no
paymaster key configured nothing is sponsored, and with one, the operator's
sponsorship policy decides, and may refuse an operation (docs/blockchain.md,
Gas). An attestation you ask for is metered like any other operation. The
example prints the dashboard reply whole and, under Gas, the statement of a
gas_policy object Neo's reply quotes; when his reply quotes none, it says that
it cannot read the policy from the reply. It does not look in a tool call's
result_preview: the gateway cuts a preview to 200 characters, and the
dashboard's platform_stats result puts gas_policy after that, so a preview
never carries it.
"""

import asyncio
import json
import os
import sys
sys.path.insert(0, ".")

from sdk import MatrixClient


async def main():
    client = MatrixClient("http://localhost:18790", api_key=os.environ.get("MATRIX_API_KEY"))

    # 1. Check price feed
    print("── Oracle: ETH/USD Price ──")
    result = await client.get_price("ETH/USD")
    print(f"Result: {result['response'][:200]}")

    # 2. Convert a smart contract (the platform does not deploy it)
    print("\n── Convert Contract ──")
    contract_source = '''
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract HelloMatrix {
    string public message = "Hello from The Matrix!";

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

    # 5. Platform dashboard, printed whole: its gas_policy comes last, and
    # cutting the reply short cuts it off.
    print("\n── Dashboard ──")
    result = await client.ablockchain("dashboard", action="platform_stats")
    print(f"Result: {result['response']}")

    # Gas: what the dashboard reply says about it, and nothing it does not say.
    policy = gas_policy_in(result)
    print("\n── Gas ──")
    if policy is None:
        print("Neo's reply does not quote the dashboard's gas_policy object, so this "
              "example cannot read the deployment's gas policy from it; his reply, "
              "printed above, may describe it in words.")
    else:
        print(policy.get("statement") or f"gas_policy: {json.dumps(policy)}")


def gas_policy_in(result: dict) -> dict | None:
    """The gas_policy object of the dashboard's platform_stats result, as Neo's
    reply quotes it, or None when his reply quotes none. His reply is text; a
    JSON object in it is read as he gave it. A tool call's result_preview is
    not read: it is cut to 200 characters, before gas_policy begins."""
    text = result.get("response") or ""
    decoder = json.JSONDecoder()
    for start in (i for i, ch in enumerate(text) if ch == "{"):
        try:
            value, _end = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get("gas_policy"), dict):
            return value["gas_policy"]
    return None


if __name__ == "__main__":
    asyncio.run(main())
