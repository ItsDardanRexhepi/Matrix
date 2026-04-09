"""
NFTFactory — deploy ERC-721 and ERC-1155 collections on Base L2.

Handles contract deployment, metadata configuration, and royalty setup.
Uses the contract conversion service templates for consistent, audited
contract code.
"""

from __future__ import annotations

import logging
from typing import Any

from runtime.blockchain.web3_manager import Web3Manager, not_deployed_response

logger = logging.getLogger(__name__)


class NFTFactory:
    """Deploy NFT collections on-chain.

    Parameters
    ----------
    config : dict
        Platform config.  Reads:
        - ``blockchain.rpc_url`` — RPC endpoint
        - ``blockchain.chain_id`` — target chain
        - ``blockchain.platform_wallet`` — deployer/fee recipient
        - ``nft.default_base_uri`` — default IPFS/Arweave base URI
        - ``nft.max_royalty_bps`` — maximum royalty (default 2500 = 25%)
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        bc = config.get("blockchain", {})
        nft_cfg = config.get("nft", {})

        self._rpc_url: str = bc.get("rpc_url", "")
        self._chain_id: int = int(bc.get("chain_id", 8453))
        self._platform_wallet: str = bc.get("platform_wallet", "")
        self._default_base_uri: str = nft_cfg.get(
            "default_base_uri", "ipfs://"
        )
        self._max_royalty_bps: int = int(nft_cfg.get("max_royalty_bps", 2500))
        self._nft_factory_address: str = (
            nft_cfg.get("factory_address")
            or bc.get("nft_factory_address", "")
            or ""
        )

        self._web3 = Web3Manager.get_shared(config)

        # Track deployed collections (cache for in-process queries)
        self._collections: dict[str, dict[str, Any]] = {}

    def _is_ready(self) -> bool:
        """Return True if the NFT factory contract is configured for real deployment."""
        return (
            self._web3.available
            and not self._web3.is_placeholder(self._nft_factory_address)
        )

    async def deploy_erc721(
        self,
        owner: str,
        name: str,
        symbol: str,
        base_uri: str,
        royalty_bps: int,
    ) -> dict[str, Any]:
        """Deploy an ERC-721 NFT collection.

        Parameters
        ----------
        owner : str
            Owner/deployer wallet address.
        name : str
            Collection name.
        symbol : str
            Token symbol.
        base_uri : str
            Base URI for token metadata.
        royalty_bps : int
            Default royalty in basis points (e.g., 500 = 5%).

        Returns
        -------
        dict
            Deployment result with ``collection_address``, ``tx_hash``.
        """
        if not name or not symbol:
            raise ValueError("Name and symbol are required")
        if royalty_bps < 0 or royalty_bps > self._max_royalty_bps:
            raise ValueError(
                f"Royalty must be between 0 and {self._max_royalty_bps} bps"
            )
        if not owner or not owner.startswith("0x"):
            raise ValueError("Valid owner address required")

        base_uri = base_uri or self._default_base_uri

        if not self._is_ready():
            logger.warning(
                "Service %s called but contract not deployed", self.__class__.__name__
            )
            return not_deployed_response("nft_services", {
                "operation": "deploy_erc721",
                "requested": {
                    "name": name,
                    "symbol": symbol,
                    "owner": owner,
                    "royalty_bps": royalty_bps,
                },
            })

        # Real deployment path is gated on a deployed factory contract.
        # Without a verified factory ABI we surface a not_deployed response
        # rather than fabricating a collection address.
        return not_deployed_response("nft_services", {
            "operation": "deploy_erc721",
            "reason": "factory ABI not yet wired into runtime",
        })

    async def deploy_erc1155(
        self,
        owner: str,
        uri: str,
        royalty_bps: int,
    ) -> dict[str, Any]:
        """Deploy an ERC-1155 multi-token collection.

        Parameters
        ----------
        owner : str
            Owner/deployer wallet address.
        uri : str
            Base URI template (with ``{id}`` placeholder).
        royalty_bps : int
            Default royalty in basis points.

        Returns
        -------
        dict
            Deployment result.
        """
        if not owner or not owner.startswith("0x"):
            raise ValueError("Valid owner address required")
        if royalty_bps < 0 or royalty_bps > self._max_royalty_bps:
            raise ValueError(
                f"Royalty must be between 0 and {self._max_royalty_bps} bps"
            )

        uri = uri or f"{self._default_base_uri}{{id}}"

        if not self._is_ready():
            logger.warning(
                "Service %s called but contract not deployed", self.__class__.__name__
            )
            return not_deployed_response("nft_services", {
                "operation": "deploy_erc1155",
                "requested": {
                    "owner": owner,
                    "uri": uri,
                    "royalty_bps": royalty_bps,
                },
            })

        return not_deployed_response("nft_services", {
            "operation": "deploy_erc1155",
            "reason": "factory ABI not yet wired into runtime",
        })

    async def mint_token(
        self,
        collection: str,
        to: str,
        metadata: dict[str, Any],
        token_id: int | None = None,
    ) -> dict[str, Any]:
        """Mint a new token in a collection.

        Parameters
        ----------
        collection : str
            Collection contract address.
        to : str
            Recipient wallet address.
        metadata : dict
            Token metadata (name, description, image, attributes, etc.).
        token_id : int, optional
            Specific token ID (auto-assigned if omitted).

        Returns
        -------
        dict
            Mint result with ``token_id``, ``tx_hash``.
        """
        if not self._is_ready():
            logger.warning(
                "Service %s called but contract not deployed", self.__class__.__name__
            )
            return not_deployed_response("nft_services", {
                "operation": "mint_token",
                "requested": {
                    "collection": collection,
                    "to": to,
                    "token_id": token_id,
                },
            })

        return not_deployed_response("nft_services", {
            "operation": "mint_token",
            "reason": "factory ABI not yet wired into runtime",
        })

    async def transfer_token(
        self,
        collection: str,
        token_id: int,
        from_addr: str,
        to_addr: str,
    ) -> dict[str, Any]:
        """Transfer a token between addresses."""
        if not self._is_ready():
            logger.warning(
                "Service %s called but contract not deployed", self.__class__.__name__
            )
            return not_deployed_response("nft_services", {
                "operation": "transfer_token",
                "requested": {
                    "collection": collection,
                    "token_id": token_id,
                    "from": from_addr,
                    "to": to_addr,
                },
            })

        return not_deployed_response("nft_services", {
            "operation": "transfer_token",
            "reason": "factory ABI not yet wired into runtime",
        })

    def get_collection(self, collection: str) -> dict[str, Any] | None:
        """Get collection details."""
        return self._collections.get(collection)

    def get_token(self, collection: str, token_id: int) -> dict[str, Any] | None:
        """Get token details."""
        coll = self._collections.get(collection)
        if coll is None:
            return None
        return coll.get("tokens", {}).get(token_id)
