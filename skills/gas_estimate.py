"""
Gas Estimate — estimates gas costs for common operations on the current network.

Queries current gas prices and estimates costs for transfers, swaps,
contract deployments, and other common operations.
"""

SKILL_NAME = "gas_estimate"
SKILL_DESCRIPTION = (
    "Estimate current gas prices and costs for common blockchain operations. "
    "Shows ETH transfer cost, ERC-20 transfer cost, swap cost, and deploy cost. "
    "Use when the user asks about gas fees, transaction costs, or network congestion."
)
SKILL_PARAMETERS = {
    "type": "object",
    "properties": {
        "operation": {
            "type": "string",
            "description": "Specific operation to estimate (e.g. 'transfer', 'swap', 'deploy'). If omitted, shows all common operations.",
        },
    },
}

# Typical gas units for common operations
GAS_ESTIMATES = {
    "ETH Transfer": 21_000,
    "ERC-20 Transfer": 65_000,
    "ERC-20 Approve": 46_000,
    "Uniswap Swap": 150_000,
    "NFT Mint (ERC-721)": 120_000,
    "Contract Deploy (Simple)": 500_000,
    "Contract Deploy (Complex)": 2_000_000,
    "Aave Deposit": 250_000,
    "Aave Borrow": 350_000,
}


async def execute(operation: str = "", **kwargs) -> str:
    """Estimate gas costs."""
    try:
        from runtime.blockchain.interface import BlockchainInterface

        config = kwargs.get("config", {})
        blockchain = BlockchainInterface(config)
        w3 = blockchain.w3

        gas_price = w3.eth.gas_price
        gas_price_gwei = w3.from_wei(gas_price, "gwei")

        lines = [
            f"## Gas Estimates\n",
            f"**Current Gas Price**: {gas_price_gwei:.2f} Gwei\n",
            "| Operation | Gas Units | Cost (ETH) | Cost (USD*) |",
            "|-----------|-----------|------------|-------------|",
        ]

        estimates = GAS_ESTIMATES
        if operation:
            op_lower = operation.lower()
            estimates = {
                k: v for k, v in GAS_ESTIMATES.items()
                if op_lower in k.lower()
            }
            if not estimates:
                estimates = GAS_ESTIMATES

        for op_name, gas_units in estimates.items():
            cost_wei = gas_units * gas_price
            cost_eth = w3.from_wei(cost_wei, "ether")
            lines.append(
                f"| {op_name} | {gas_units:,} | {cost_eth:.6f} | — |"
            )

        lines.append("\n*USD estimates require a price feed oracle.*")
        return "\n".join(lines)
    except Exception as e:
        return f"Gas estimation failed: {e}"
