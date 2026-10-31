"""Cross-chain token bridging via CCIP and Stargate; the message sends (CCIP, Hyperlane, Wormhole, Axelar) are refused."""
from runtime.blockchain.services.ccip.service import CrossChainMessagingService

__all__ = ["CrossChainMessagingService"]
