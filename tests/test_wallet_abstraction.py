"""Tests for wallet abstraction — account manager, session wallets, gas sponsorship."""

from __future__ import annotations

import pytest

from runtime.blockchain.web3_manager import Web3Manager
from runtime.blockchain.wallet_abstraction.account_manager import AccountManager


# Force-offline blockchain config — no rpc_url, no paymaster.
OFFLINE_CONFIG: dict = {
    "blockchain": {
        "rpc_url": "",
        "chain_id": 84532,
        "network": "base-sepolia",
    }
}


@pytest.fixture(autouse=True)
def _reset_web3_singleton():
    """Ensure each test starts with a fresh offline Web3Manager."""
    Web3Manager.reset_shared()
    Web3Manager.get_shared(OFFLINE_CONFIG)
    yield
    Web3Manager.reset_shared()


# ═══════════════════════════════════════════════════════════════════════
# Account Manager
# ═══════════════════════════════════════════════════════════════════════


class TestAccountManager:
    """Verify AccountManager session wallets, balances, gas, batching, and display helpers."""

    @pytest.mark.asyncio
    async def test_get_or_create_session_wallet(self):
        mgr = AccountManager(config={})
        wallet = await mgr.get_or_create_session_wallet("test-session-1")
        assert isinstance(wallet, str)
        assert wallet.startswith("0x")
        assert len(wallet) == 42  # 0x + 40 hex chars

    @pytest.mark.asyncio
    async def test_session_wallet_deterministic(self):
        mgr = AccountManager(config={})
        wallet_a = await mgr.get_or_create_session_wallet("determinism-check")
        wallet_b = await mgr.get_or_create_session_wallet("determinism-check")
        assert wallet_a == wallet_b

    @pytest.mark.asyncio
    async def test_different_sessions_different_wallets(self):
        mgr = AccountManager(config={})
        wallet_x = await mgr.get_or_create_session_wallet("session-x")
        wallet_y = await mgr.get_or_create_session_wallet("session-y")
        assert wallet_x != wallet_y

    @pytest.mark.asyncio
    async def test_get_balance_offline(self):
        mgr = AccountManager(OFFLINE_CONFIG)
        balance = await mgr.get_balance("0x" + "a" * 40, "ETH", "base")
        assert isinstance(balance, float)
        assert balance == 0.0

    @pytest.mark.asyncio
    async def test_get_all_balances_structure(self):
        mgr = AccountManager(OFFLINE_CONFIG)
        result = await mgr.get_all_balances("0x" + "a" * 40)
        assert isinstance(result, dict)
        for key in ("wallet", "chains", "total_usd"):
            assert key in result, f"Missing key: {key}"
        assert isinstance(result["chains"], dict)
        assert isinstance(result["total_usd"], (int, float))

    @pytest.mark.asyncio
    async def test_estimate_gas_offline(self):
        mgr = AccountManager(OFFLINE_CONFIG)
        result = await mgr.estimate_gas(
            action="transfer",
            params={"to": "0x" + "b" * 40, "amount": 0.01},
            chain="base",
        )
        assert isinstance(result, dict)
        for key in ("chain", "action", "gas_units", "gas_price_gwei", "cost_eth", "cost_usd"):
            assert key in result, f"Missing key: {key}"
        assert result["gas_units"] > 0

    @pytest.mark.asyncio
    async def test_sponsor_gas_not_configured(self):
        mgr = AccountManager(config={})
        result = await mgr.sponsor_gas(tx={"action": "transfer", "chain": "base"})
        assert isinstance(result, dict)
        assert result["sponsored"] is False

    @pytest.mark.asyncio
    async def test_batch_transactions(self):
        mgr = AccountManager(OFFLINE_CONFIG)
        mock_txs = [
            {"action": "transfer", "chain": "base", "to": "0x" + "1" * 40, "amount": 0.1},
            {"action": "swap", "chain": "base", "token_in": "ETH", "token_out": "USDC"},
            {"action": "approve", "chain": "base", "spender": "0x" + "2" * 40},
        ]
        result = await mgr.batch_transactions(mock_txs, wallet="0x" + "a" * 40)
        assert isinstance(result, dict)
        assert "batch_id" in result
        assert result["transaction_count"] == 3

    def test_display_address_format(self):
        mgr = AccountManager(config={})
        full_address = "0x1234567890abcdef1234567890abcdef12345678"
        display = mgr.get_display_address(full_address)
        assert display == "0x1234...5678"

    def test_display_address_short(self):
        mgr = AccountManager(config={})
        # Short or invalid addresses should be returned as-is.
        short = mgr.get_display_address("0x1234")
        assert short == "0x1234"

        empty = mgr.get_display_address("")
        assert empty == ""

    @pytest.mark.asyncio
    async def test_empty_batch(self):
        mgr = AccountManager(OFFLINE_CONFIG)
        result = await mgr.batch_transactions([], wallet="0x" + "a" * 40)
        assert isinstance(result, dict)
        assert "status" in result
        # Empty batch should return an error status, not crash.
        assert result["status"] == "error"
