"""
Smart Contract Conversion Service — Component 1.

Converts Solidity, Vyper, or pseudocode contracts into optimized Solidity
targeting Base L2. Handles complexity classification, tiered pricing,
platform fee injection, and artist/creative contract detection.
"""

from runtime.blockchain.services.contract_conversion.service import ContractConversionService

__all__ = ["ContractConversionService"]
