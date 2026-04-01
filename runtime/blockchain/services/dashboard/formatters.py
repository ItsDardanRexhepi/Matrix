"""
Plain English formatters for the 0pnMatrx unified dashboard.

All output is human-readable. No hex addresses shown to users
(truncated to 0x...1234 format). No jargon.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _truncate_address(address: str) -> str:
    """Truncate a hex address to 0x...1234 format for display."""
    if not address:
        return "Unknown"
    if len(address) <= 10:
        return address
    return f"{address[:4]}...{address[-4:]}"


def _format_amount(amount: float, decimals: int = 2) -> str:
    """Format a numeric amount for display."""
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:,.{decimals}f}M"
    if amount >= 1_000:
        return f"{amount / 1_000:,.{decimals}f}K"
    return f"{amount:,.{decimals}f}"


def _format_timestamp(ts: int | float) -> str:
    """Format a Unix timestamp to human-readable."""
    if not ts:
        return "Unknown time"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%b %d, %Y at %H:%M UTC")


def _time_ago(ts: int | float) -> str:
    """Convert timestamp to relative time string."""
    if not ts:
        return "Unknown"
    now = datetime.now(tz=timezone.utc).timestamp()
    diff = int(now - ts)

    if diff < 60:
        return "just now"
    if diff < 3600:
        mins = diff // 60
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    if diff < 86400:
        hours = diff // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = diff // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


class PlainEnglishFormatter:
    """Formats blockchain data into plain English for end users."""

    def format_defi_position(self, position: dict) -> str:
        """Format a DeFi position into a readable sentence.

        Example output:
            "You have 1,500.00 USDC supplied to the Lending Pool,
             earning approximately 4.2% per year."
        """
        protocol = position.get("protocol", "DeFi protocol")
        position_type = position.get("type", "position")
        amount = position.get("amount", 0)
        token = position.get("token", "tokens")
        apy = position.get("apy")
        value_usd = position.get("value_usd")

        parts = [f"You have {_format_amount(amount)} {token}"]

        type_descriptions = {
            "supply": "supplied to",
            "borrow": "borrowed from",
            "stake": "staked in",
            "liquidity": "providing liquidity in",
            "farm": "farming in",
        }
        action = type_descriptions.get(position_type, "deposited in")
        parts.append(f"{action} the {protocol}")

        if apy is not None:
            parts.append(f"earning approximately {apy:.1f}% per year")

        result = ", ".join(parts) + "."

        if value_usd is not None:
            result += f" Current value: ${_format_amount(value_usd)}."

        return result

    def format_staking_info(self, info: dict) -> str:
        """Format staking information into a readable sentence.

        Example output:
            "You are staking 10.00 ETH in the Default pool. Your current
             annual yield is 5.2%. You have earned 0.52 ETH in rewards so far."
        """
        staked = info.get("staked_amount", 0)
        pool = info.get("pool_name", info.get("pool_id", "Default"))
        apy = info.get("apy")
        rewards = info.get("pending_rewards", 0)
        token = info.get("token", "ETH")

        parts = [f"You are staking {_format_amount(staked)} {token} in the {pool} pool"]

        if apy is not None:
            parts.append(f"Your current annual yield is {apy:.1f}%")

        if rewards > 0:
            parts.append(
                f"You have earned {_format_amount(rewards, 4)} {token} in rewards so far"
            )

        return ". ".join(parts) + "."

    def format_transaction(self, tx: dict) -> str:
        """Format a transaction into a readable sentence.

        Example output:
            "2 hours ago: You sent 5.00 ETH to 0xab...cd12."
        """
        tx_type = tx.get("type", "transaction")
        amount = tx.get("amount", 0)
        token = tx.get("token", "ETH")
        from_addr = _truncate_address(tx.get("from", ""))
        to_addr = _truncate_address(tx.get("to", ""))
        timestamp = tx.get("timestamp", 0)
        status = tx.get("status", "confirmed")

        time_str = _time_ago(timestamp)

        type_descriptions = {
            "send": f"You sent {_format_amount(amount)} {token} to {to_addr}",
            "receive": f"You received {_format_amount(amount)} {token} from {from_addr}",
            "swap": f"You swapped {_format_amount(amount)} {token} for {tx.get('token_out', 'tokens')}",
            "stake": f"You staked {_format_amount(amount)} {token}",
            "unstake": f"You unstaked {_format_amount(amount)} {token}",
            "mint": f"You minted {_format_amount(amount)} {token}",
            "burn": f"You burned {_format_amount(amount)} {token}",
            "approve": f"You approved {to_addr} to spend your {token}",
            "vote": f"You voted on proposal {tx.get('proposal_id', 'unknown')}",
            "claim": f"You claimed {_format_amount(amount)} {token} in rewards",
            "contribute": f"You contributed {_format_amount(amount)} {token} to a campaign",
        }

        description = type_descriptions.get(
            tx_type, f"Transaction: {_format_amount(amount)} {token}"
        )

        status_suffix = ""
        if status == "pending":
            status_suffix = " (pending)"
        elif status == "failed":
            status_suffix = " (failed)"

        return f"{time_str}: {description}{status_suffix}."

    def format_portfolio_summary(self, portfolio: dict) -> str:
        """Format a portfolio overview into readable text."""
        total_value = portfolio.get("total_value_usd", 0)
        token_count = len(portfolio.get("tokens", []))
        nft_count = len(portfolio.get("nfts", []))
        staking_count = len(portfolio.get("staking_positions", []))
        defi_count = len(portfolio.get("defi_positions", []))

        parts = [f"Your portfolio is worth approximately ${_format_amount(total_value)}"]

        holdings = []
        if token_count:
            holdings.append(f"{token_count} token{'s' if token_count != 1 else ''}")
        if nft_count:
            holdings.append(f"{nft_count} NFT{'s' if nft_count != 1 else ''}")
        if staking_count:
            holdings.append(
                f"{staking_count} staking position{'s' if staking_count != 1 else ''}"
            )
        if defi_count:
            holdings.append(
                f"{defi_count} DeFi position{'s' if defi_count != 1 else ''}"
            )

        if holdings:
            parts.append("You hold " + ", ".join(holdings))

        return ". ".join(parts) + "."

    def format_component_status(self, component: str, status: dict) -> str:
        """Format a component status into readable text."""
        component_names = {
            "staking": "Staking",
            "defi": "DeFi",
            "nft_services": "NFT Marketplace",
            "dex": "Token Exchange",
            "governance": "Governance",
            "fundraising": "Community Fundraising",
            "securities_exchange": "Securities Exchange",
            "rwa_tokenization": "Real World Assets",
            "supply_chain": "Supply Chain",
            "insurance": "Insurance",
            "gaming": "Gaming",
            "oracle_gateway": "Data Feeds",
            "cross_border": "International Transfers",
            "stablecoin": "Stablecoin",
            "dashboard": "Dashboard",
        }

        name = component_names.get(component, component.replace("_", " ").title())
        is_healthy = status.get("healthy", status.get("status") == "active")
        health = "running normally" if is_healthy else "experiencing issues"

        return f"{name} is {health}."
