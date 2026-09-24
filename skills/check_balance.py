"""
Check Balance — reads a wallet's native balance on the configured network.

This skill queries the blockchain node the platform is configured for
(``blockchain.rpc_url``) and returns the address's ETH balance. It reads one
network, the configured one, and the native balance only.
"""

SKILL_NAME = "check_balance"
SKILL_DESCRIPTION = (
    "Check the native (ETH) balance of a wallet address on the network this "
    "platform is configured for. "
    "Use when the user asks about a wallet's ETH balance."
)
SKILL_PARAMETERS = {
    "type": "object",
    "properties": {
        "address": {
            "type": "string",
            "description": "A 0x wallet address. If omitted, the platform wallet is used.",
        },
    },
}


async def execute(address: str = "", **kwargs) -> str:
    """Execute the balance check."""
    try:
        # The platform's shared connection, whose `.w3` this skill was written
        # against. It used to build `BlockchainInterface(config)` — an abstract
        # class, which cannot be instantiated — and read `.w3`, which that class
        # does not have, so every call answered "Failed to check balance".
        from runtime.blockchain.web3_manager import Web3Manager

        config = kwargs.get("config") or {}
        if not address:
            address = config.get("blockchain", {}).get("platform_wallet", "")
            if not address:
                return "No wallet address provided and no default wallet configured."

        chain = Web3Manager.get_shared(config)
        # Raises when nothing was read (no RPC configured, or the read failed):
        # an unread balance is not zero.
        balance_eth = chain.get_balance_eth(address)

        lines = [
            "**Wallet Balance**",
            f"- **Address**: `{address[:6]}...{address[-4:]}`",
            f"- **Network**: {chain.network}",
            f"- **ETH Balance**: {balance_eth:.6f} ETH",
        ]
        requested = kwargs.get("network")
        if requested and str(requested).lower() != str(chain.network).lower():
            lines.append(
                f"- This is the balance on {chain.network}, the configured "
                f"network; {requested} was not read."
            )
        return "\n".join(lines) + "\n"
    except Exception as e:
        return f"Failed to check balance: {e}"
