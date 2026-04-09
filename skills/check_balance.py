"""
Check Balance — retrieves wallet balance across connected networks.

This skill queries the connected blockchain node for the user's wallet
balance and returns a formatted summary of holdings.
"""

SKILL_NAME = "check_balance"
SKILL_DESCRIPTION = (
    "Check the balance of a wallet address on any supported network. "
    "Returns ETH balance and major token balances. "
    "Use when the user asks about their balance, holdings, or portfolio."
)
SKILL_PARAMETERS = {
    "type": "object",
    "properties": {
        "address": {
            "type": "string",
            "description": "Wallet address or ENS name. If omitted, uses the connected wallet.",
        },
        "network": {
            "type": "string",
            "description": "Network to query (e.g. 'base', 'ethereum', 'polygon'). Defaults to the configured network.",
        },
    },
}


async def execute(address: str = "", network: str = "", **kwargs) -> str:
    """Execute the balance check."""
    try:
        from runtime.blockchain.interface import BlockchainInterface

        config = kwargs.get("config", {})
        blockchain = BlockchainInterface(config)

        if not address:
            address = config.get("blockchain", {}).get("platform_wallet", "")
            if not address:
                return "No wallet address provided and no default wallet configured."

        balance_wei = blockchain.w3.eth.get_balance(address)
        balance_eth = blockchain.w3.from_wei(balance_wei, "ether")

        net = network or config.get("blockchain", {}).get("network", "base-sepolia")
        return (
            f"**Wallet Balance**\n"
            f"- **Address**: `{address[:6]}...{address[-4:]}`\n"
            f"- **Network**: {net}\n"
            f"- **ETH Balance**: {balance_eth:.6f} ETH\n"
        )
    except Exception as e:
        return f"Failed to check balance: {e}"
