from __future__ import annotations

"""
NeoSafe Revenue Verifier — confirms all platform fees reach NeoSafe wallet.
Address: config-driven (0x46fF491D7054A6F500026B3E81f358190f8d8Ec5 in production).
"""

import asyncio
import json
import logging
import time
from typing import Optional

from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.exceptions import TransactionNotFound
from eth_account import Account
from eth_abi import encode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Minimal ERC-20 ABI for balance/transfer checks
# ---------------------------------------------------------------------------
ERC20_ABI: list[dict] = [
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "transfer",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "decimals",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}],
    },
    {
        "name": "symbol",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "string"}],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_neosafe_address(config: dict) -> str:
    """Resolve the NeoSafe wallet address from config."""
    addr = config.get("neosafe_address")
    if not addr:
        raise ValueError(
            "neosafe_address must be set in config "
            "(production default: 0x46fF491D7054A6F500026B3E81f358190f8d8Ec5)"
        )
    return addr


async def _build_web3(config: dict) -> tuple[AsyncWeb3, Account]:
    w3 = AsyncWeb3(AsyncHTTPProvider(config["rpc_url"]))
    account = Account.from_key(config["private_key"])
    return w3, account


async def _wait_for_receipt(
    w3: AsyncWeb3, tx_hash_hex: str, timeout: int = 180, poll: int = 2
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            receipt = await w3.eth.get_transaction_receipt(tx_hash_hex)
            if receipt is not None:
                return receipt
        except TransactionNotFound:
            pass
        await asyncio.sleep(poll)
    raise TimeoutError(f"Tx {tx_hash_hex} not confirmed within {timeout}s")


# ---------------------------------------------------------------------------
# verify_revenue_route
# ---------------------------------------------------------------------------

async def verify_revenue_route(config: dict) -> dict:
    """
    Check NeoSafe balance and recent incoming transactions.

    Returns
    -------
    {
        "neosafe_address": str,
        "eth_balance_wei": int,
        "eth_balance_ether": str,
        "block_number": int,
        "is_receiving": bool,
        "recent_tx_count": int,
    }
    """
    w3, _ = await _build_web3(config)
    neosafe = _get_neosafe_address(config)

    balance = await w3.eth.get_balance(neosafe)
    block = await w3.eth.get_block("latest")
    tx_count = await w3.eth.get_transaction_count(neosafe)

    result = {
        "neosafe_address": neosafe,
        "eth_balance_wei": balance,
        "eth_balance_ether": str(w3.from_wei(balance, "ether")),
        "block_number": block["number"],
        "is_receiving": balance > 0 or tx_count > 0,
        "recent_tx_count": tx_count,
    }

    logger.info(
        "NeoSafe %s — balance %s ETH, tx_count %d",
        neosafe,
        result["eth_balance_ether"],
        tx_count,
    )
    return result


# ---------------------------------------------------------------------------
# send_platform_fee
# ---------------------------------------------------------------------------

async def send_platform_fee(
    config: dict,
    amount: int,
    token: Optional[str] = None,
    reason: str = "",
) -> dict:
    """
    Send a platform fee to the NeoSafe wallet.

    Parameters
    ----------
    config : deployer config dict
    amount : amount in wei (for ETH) or token base units
    token  : ERC-20 token address — ``None`` means native ETH
    reason : human-readable reason for the transfer

    Returns
    -------
    {
        "tx_hash": str,
        "from": str,
        "to": str,
        "amount": int,
        "token": str | None,
        "reason": str,
        "status": str,  # "confirmed" | "reverted"
    }
    """
    w3, account = await _build_web3(config)
    neosafe = _get_neosafe_address(config)
    chain_id = int(config["chain_id"])

    if token is None:
        # Native ETH transfer
        nonce = await w3.eth.get_transaction_count(account.address)
        tx = {
            "from": account.address,
            "to": neosafe,
            "value": amount,
            "nonce": nonce,
            "chainId": chain_id,
            "gas": 21_000,
            "maxPriorityFeePerGas": w3.to_wei(
                config.get("max_priority_fee_gwei", 0.1), "gwei"
            ),
        }

        # Need maxFeePerGas for EIP-1559
        base_fee = (await w3.eth.get_block("latest")).get("baseFeePerGas", 0)
        tx["maxFeePerGas"] = base_fee + tx["maxPriorityFeePerGas"]

        signed = account.sign_transaction(tx)
        tx_hash = await w3.eth.send_raw_transaction(signed.raw_transaction)
    else:
        # ERC-20 transfer
        erc20 = w3.eth.contract(address=token, abi=ERC20_ABI)
        nonce = await w3.eth.get_transaction_count(account.address)
        tx = await erc20.functions.transfer(neosafe, amount).build_transaction(
            {
                "from": account.address,
                "nonce": nonce,
                "chainId": chain_id,
                "maxPriorityFeePerGas": w3.to_wei(
                    config.get("max_priority_fee_gwei", 0.1), "gwei"
                ),
            }
        )
        estimated = await w3.eth.estimate_gas(tx)
        tx["gas"] = int(estimated * 1.2)

        signed = account.sign_transaction(tx)
        tx_hash = await w3.eth.send_raw_transaction(signed.raw_transaction)

    tx_hash_hex = tx_hash.hex()
    logger.info("Platform fee tx sent: %s (%s)", tx_hash_hex, reason)

    receipt = await _wait_for_receipt(w3, tx_hash_hex)
    status = "confirmed" if receipt["status"] == 1 else "reverted"

    result = {
        "tx_hash": tx_hash_hex,
        "from": account.address,
        "to": neosafe,
        "amount": amount,
        "token": token,
        "reason": reason,
        "status": status,
    }

    if status == "confirmed":
        logger.info("Platform fee of %d sent to NeoSafe — reason: %s", amount, reason)
    else:
        logger.error("Platform fee tx reverted: %s", tx_hash_hex)

    return result


# ---------------------------------------------------------------------------
# get_revenue_summary
# ---------------------------------------------------------------------------

async def get_revenue_summary(config: dict) -> dict:
    """
    Build a summary of revenue received by NeoSafe.

    Returns
    -------
    {
        "neosafe_address": str,
        "eth_balance_wei": int,
        "eth_balance_ether": str,
        "token_balances": list[dict],    # checked tokens from config
        "total_tx_count": int,
        "summary_block": int,
        "timestamp": int,
    }
    """
    w3, _ = await _build_web3(config)
    neosafe = _get_neosafe_address(config)

    balance = await w3.eth.get_balance(neosafe)
    tx_count = await w3.eth.get_transaction_count(neosafe)
    block = await w3.eth.get_block("latest")

    # Check ERC-20 balances for tokens listed in config
    token_balances: list[dict] = []
    for token_addr in config.get("tracked_tokens", []):
        try:
            erc20 = w3.eth.contract(address=token_addr, abi=ERC20_ABI)
            bal = await erc20.functions.balanceOf(neosafe).call()
            symbol = "UNKNOWN"
            decimals = 18
            try:
                symbol = await erc20.functions.symbol().call()
                decimals = await erc20.functions.decimals().call()
            except Exception:
                pass
            token_balances.append(
                {
                    "token": token_addr,
                    "symbol": symbol,
                    "balance_raw": bal,
                    "decimals": decimals,
                }
            )
        except Exception as exc:
            logger.warning("Failed to read token %s: %s", token_addr, exc)

    result = {
        "neosafe_address": neosafe,
        "eth_balance_wei": balance,
        "eth_balance_ether": str(w3.from_wei(balance, "ether")),
        "token_balances": token_balances,
        "total_tx_count": tx_count,
        "summary_block": block["number"],
        "timestamp": int(time.time()),
    }

    logger.info(
        "Revenue summary for %s — %s ETH, %d tokens tracked, %d txs",
        neosafe,
        result["eth_balance_ether"],
        len(token_balances),
        tx_count,
    )
    return result
