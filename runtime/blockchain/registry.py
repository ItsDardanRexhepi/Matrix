"""
Blockchain Capability Registry — registers all blockchain capability classes with the tool dispatcher.

Each capability is a BlockchainInterface subclass that provides:
- name: tool name for the dispatcher
- schema: JSON schema for parameters
- execute: async handler function

All capabilities share the same config and gas sponsorship infrastructure.
"""

import logging
from typing import Any

from runtime.blockchain.smart_contracts import SmartContracts
from runtime.blockchain.defi import DeFi
from runtime.blockchain.nfts import NFTs
from runtime.blockchain.tokenization import Tokenization
from runtime.blockchain.identity import Identity
from runtime.blockchain.daos import DAOs
from runtime.blockchain.stablecoins import Stablecoins
from runtime.blockchain.eas_manager import EASManager
from runtime.blockchain.agent_identity import AgentIdentity
from runtime.blockchain.payments import Payments
from runtime.blockchain.oracles import Oracles
from runtime.blockchain.supply_chain import SupplyChain
from runtime.blockchain.insurance import Insurance
from runtime.blockchain.gaming import Gaming
from runtime.blockchain.ip_royalties import IPRoyalties
from runtime.blockchain.staking import Staking
from runtime.blockchain.crossborder import CrossBorderPayments
from runtime.blockchain.securities import Securities
from runtime.blockchain.governance import Governance
from runtime.blockchain.dashboard import Dashboard

logger = logging.getLogger(__name__)

# All blockchain capability classes
CAPABILITY_CLASSES = [
    SmartContracts,     # 1. Deploy, interact, verify smart contracts
    DeFi,              # 2. Lending, borrowing, yield, liquidity
    NFTs,              # 3. ERC-721/1155 mint, transfer, manage
    Tokenization,      # 4. ERC-20 token creation and management
    Identity,          # 5. On-chain identity verification
    DAOs,              # 6. DAO governance — propose, vote, execute
    Stablecoins,       # 7. USDC/DAI/USDT operations
    EASManager,        # 8. EAS attestation management
    AgentIdentity,     # 9. On-chain agent identity
    Payments,          # 10. ETH and token payments
    Oracles,           # 11. Chainlink price feeds
    SupplyChain,       # 12. Supply chain tracking
    Insurance,         # 13. On-chain insurance policies
    Gaming,            # 14. Gaming assets (ERC-1155)
    IPRoyalties,       # 15. IP registration and royalties
    Staking,           # 16. Token staking and rewards
    CrossBorderPayments,  # 17. International stablecoin transfers
    Securities,        # 18. Tokenized securities (ERC-3643)
    Governance,        # 19. Timelock and access control
    Dashboard,         # 20. Blockchain analytics and monitoring
]


def register_blockchain_tools(dispatcher, config: dict):
    """
    Register all blockchain capabilities with the tool dispatcher.

    Args:
        dispatcher: ToolDispatcher instance
        config: Platform config dict (must include 'blockchain' section)
    """
    registered = 0
    for cls in CAPABILITY_CLASSES:
        try:
            capability = cls(config)
            dispatcher.register(
                capability.name,
                capability.execute,
                capability.schema,
            )
            registered += 1
            logger.debug(f"Registered blockchain capability: {capability.name}")
        except Exception as e:
            logger.error(f"Failed to register {cls.__name__}: {e}")

    logger.info(f"Registered {registered}/{len(CAPABILITY_CLASSES)} blockchain capabilities")
    return registered
