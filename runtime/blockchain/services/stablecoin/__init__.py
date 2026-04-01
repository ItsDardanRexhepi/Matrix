"""
Stablecoin Infrastructure -- Component 7.

Provides stablecoin transfer, balance tracking, tiered fee calculation,
and rate limiting for the 0pnMatrx platform. Supports USDC, USDT, DAI,
and other ERC-20 stablecoins on Base.
"""

from runtime.blockchain.services.stablecoin.service import StablecoinService

__all__ = ["StablecoinService"]
