"""
Explain Transaction — decodes and explains a blockchain transaction in plain English.

Takes a transaction hash and returns a human-readable explanation of
what the transaction did, who was involved, and how much was transferred.
"""

SKILL_NAME = "explain_transaction"
SKILL_DESCRIPTION = (
    "Look up a transaction by hash and explain it in plain English. "
    "Shows sender, receiver, value, gas, and decoded function call. "
    "Use when the user asks about a specific transaction or wants to "
    "understand what happened on-chain."
)
SKILL_PARAMETERS = {
    "type": "object",
    "properties": {
        "tx_hash": {
            "type": "string",
            "description": "The transaction hash to look up.",
        },
    },
    "required": ["tx_hash"],
}


async def execute(tx_hash: str = "", **kwargs) -> str:
    """Look up and explain a transaction."""
    if not tx_hash.strip():
        return "Please provide a transaction hash."

    try:
        from runtime.blockchain.interface import BlockchainInterface

        config = kwargs.get("config", {})
        blockchain = BlockchainInterface(config)
        w3 = blockchain.w3

        tx = w3.eth.get_transaction(tx_hash)
        receipt = w3.eth.get_transaction_receipt(tx_hash)

        value_eth = w3.from_wei(tx["value"], "ether")
        gas_price_gwei = w3.from_wei(tx.get("gasPrice", 0), "gwei")
        gas_cost_eth = w3.from_wei(
            receipt["gasUsed"] * tx.get("gasPrice", receipt.get("effectiveGasPrice", 0)),
            "ether",
        )

        status = "Success" if receipt["status"] == 1 else "Failed"

        lines = [
            f"## Transaction Explanation\n",
            f"- **Status**: {status}",
            f"- **From**: `{tx['from'][:6]}...{tx['from'][-4:]}`",
            f"- **To**: `{tx['to'][:6]}...{tx['to'][-4:]}`" if tx.get("to") else "- **To**: Contract Creation",
            f"- **Value**: {value_eth:.6f} ETH",
            f"- **Gas Used**: {receipt['gasUsed']:,}",
            f"- **Gas Price**: {gas_price_gwei:.2f} Gwei",
            f"- **Gas Cost**: {gas_cost_eth:.6f} ETH",
            f"- **Block**: {receipt['blockNumber']:,}",
        ]

        # Check if it's a contract interaction
        if tx.get("input") and tx["input"] != "0x":
            func_sig = tx["input"][:10]
            lines.append(f"- **Function**: `{func_sig}`")
            lines.append(f"- **Input Data**: {len(tx['input'])} bytes")

        if not tx.get("to"):
            if receipt.get("contractAddress"):
                lines.append(f"- **Contract Created**: `{receipt['contractAddress']}`")

        return "\n".join(lines)
    except Exception as e:
        return f"Could not fetch transaction: {e}"
