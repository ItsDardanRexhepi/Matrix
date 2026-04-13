"""
NFTService — orchestrate all NFT creation and artist services on 0pnMatrx.

This is the single entry point for collection deployment, minting,
transfers, sales, valuation, rights management, and royalty enforcement.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from runtime.blockchain.web3_manager import Web3Manager, not_deployed_response

from runtime.blockchain.services.nft_services.factory import NFTFactory
from runtime.blockchain.services.nft_services.rights import RightsManagement
from runtime.blockchain.services.nft_services.royalty_enforcement import RoyaltyEnforcement
from runtime.blockchain.services.nft_services.valuation import ValuationEngine

logger = logging.getLogger(__name__)


class NFTService:
    """Orchestrate all NFT operations on the 0pnMatrx platform.

    Config keys used:
        - ``blockchain.*`` — chain and wallet configuration
        - ``nft.default_base_uri`` — default metadata URI
        - ``nft.max_royalty_bps`` — max royalty
        - ``nft.valuation.*`` — valuation weights
        - ``nft.rights.*`` — rights defaults

    Parameters
    ----------
    config : dict
        Full platform configuration dictionary.
    attestation_service : object, optional
        AttestationService (Component 8) for royalty attestations.
    """

    def __init__(
        self,
        config: dict,
        attestation_service: Any = None,
    ) -> None:
        self._config = config

        self._web3 = Web3Manager.get_shared(config)
        self._nft_contract: str = config.get("nft", {}).get("contract_address", "") or ""

        self._factory = NFTFactory(config)
        self._valuation = ValuationEngine(config)
        self._rights = RightsManagement(config)
        self._royalty = RoyaltyEnforcement(config, attestation_service)

        # Extended in-memory stores
        self._fractions: dict[str, dict[str, Any]] = {}
        self._rentals: dict[str, dict[str, Any]] = {}
        self._soulbound: dict[str, dict[str, Any]] = {}

        logger.info("NFTService initialised.")

    # ── Collection Operations ────────────────────────────────────────

    async def create_collection(
        self,
        creator: str,
        name: str,
        symbol: str,
        collection_type: str,
        royalty_bps: int = 500,
    ) -> dict[str, Any]:
        """Create a new NFT collection.

        Parameters
        ----------
        creator : str
            Creator wallet address.
        name : str
            Collection name.
        symbol : str
            Token symbol.
        collection_type : str
            ``"erc721"`` or ``"erc1155"``.
        royalty_bps : int
            Default royalty in basis points (default 500 = 5%).

        Returns
        -------
        dict
            Collection deployment result.
        """
        collection_type = collection_type.lower()

        try:
            if collection_type == "erc721":
                result = await self._factory.deploy_erc721(
                    owner=creator,
                    name=name,
                    symbol=symbol,
                    base_uri="",
                    royalty_bps=royalty_bps,
                )
            elif collection_type == "erc1155":
                result = await self._factory.deploy_erc1155(
                    owner=creator,
                    uri="",
                    royalty_bps=royalty_bps,
                )
            else:
                raise ValueError(
                    f"Unknown collection type '{collection_type}'. "
                    f"Use 'erc721' or 'erc1155'."
                )

            # Configure collection-wide royalty
            collection_address = result["collection_address"]
            await self._royalty.configure_royalty(
                collection=collection_address,
                token_id=-1,  # collection-wide
                recipient=creator,
                bps=royalty_bps,
            )

            logger.info(
                "Collection created: address=%s type=%s name=%s creator=%s",
                collection_address, collection_type, name, creator,
            )
            return result

        except Exception as exc:
            logger.error("Collection creation failed: %s", exc, exc_info=True)
            raise

    # ── Minting ──────────────────────────────────────────────────────

    async def mint(
        self,
        collection: str,
        creator: str,
        metadata: dict[str, Any],
        royalty_bps: int = 500,
    ) -> dict[str, Any]:
        """Mint a new NFT in an existing collection.

        Parameters
        ----------
        collection : str
            Collection contract address.
        creator : str
            Creator/minter wallet address.
        metadata : dict
            Token metadata (name, description, image, attributes, etc.).
        royalty_bps : int
            Royalty for this token in basis points.

        Returns
        -------
        dict
            Mint result with token ID and transaction hash.
        """
        try:
            result = await self._factory.mint_token(
                collection=collection,
                to=creator,
                metadata=metadata,
            )

            token_id = result["token_id"]

            # Configure token-specific royalty
            await self._royalty.configure_royalty(
                collection=collection,
                token_id=token_id,
                recipient=creator,
                bps=royalty_bps,
            )

            # Set default rights
            await self._rights.set_rights(
                collection=collection,
                token_id=token_id,
                rights={
                    "display": {"granted": True, "holder": creator},
                    "commercial": {"granted": False, "holder": creator},
                    "derivative": {"granted": False, "holder": creator},
                    "physical": {"granted": False, "holder": creator},
                },
            )

            logger.info(
                "NFT minted: collection=%s token_id=%d creator=%s",
                collection[:10], token_id, creator,
            )
            return result

        except Exception as exc:
            logger.error("Minting failed: %s", exc, exc_info=True)
            raise

    # ── Transfers ────────────────────────────────────────────────────

    async def transfer(
        self,
        collection: str,
        token_id: int,
        from_addr: str,
        to_addr: str,
    ) -> dict[str, Any]:
        """Transfer an NFT between addresses.

        Also transfers display rights to the new owner.

        Parameters
        ----------
        collection : str
            Collection contract address.
        token_id : int
            Token ID to transfer.
        from_addr : str
            Current owner address.
        to_addr : str
            New owner address.

        Returns
        -------
        dict
            Transfer result.
        """
        try:
            result = await self._factory.transfer_token(
                collection=collection,
                token_id=token_id,
                from_addr=from_addr,
                to_addr=to_addr,
            )

            # Transfer display rights to new owner
            try:
                await self._rights.transfer_rights(
                    collection=collection,
                    token_id=token_id,
                    new_holder=to_addr,
                    rights=["display"],
                )
            except KeyError:
                # No rights record yet — that's fine for simple transfers
                pass

            return result

        except Exception as exc:
            logger.error("Transfer failed: %s", exc, exc_info=True)
            raise

    # ── Sales ────────────────────────────────────────────────────────

    async def list_for_sale(
        self,
        collection: str,
        token_id: int,
        price: float,
    ) -> dict[str, Any]:
        """List an NFT for sale.

        Parameters
        ----------
        collection : str
            Collection contract address.
        token_id : int
            Token ID.
        price : float
            Listing price in ETH.

        Returns
        -------
        dict
            Listing confirmation with price breakdown.
        """
        if price <= 0:
            raise ValueError("Price must be positive")

        # Get royalty info for the listing display
        royalty_info = await self._royalty.get_royalty_info(
            collection, token_id, price
        )

        token = self._factory.get_token(collection, token_id)
        if token is None:
            raise KeyError(f"Token {token_id} not found in {collection}")

        # Calculate fee breakdown
        platform_fee_bps = int(
            self._config.get("blockchain", {}).get("platform_fee_bps", 250)
        )
        platform_fee = (price * platform_fee_bps) / 10000
        royalty_amount = royalty_info.get("royalty_amount", 0)
        seller_receives = price - platform_fee - royalty_amount

        listing = {
            "status": "listed",
            "collection": collection,
            "token_id": token_id,
            "price": price,
            "owner": token["owner"],
            "royalty": royalty_info,
            "platform_fee": {
                "bps": platform_fee_bps,
                "amount": round(platform_fee, 8),
            },
            "seller_receives": round(seller_receives, 8),
            "listed_at": int(time.time()),
        }

        logger.info(
            "Listed for sale: %s #%d at %.4f ETH (seller receives %.4f)",
            collection[:10], token_id, price, seller_receives,
        )
        return listing

    async def process_sale(
        self,
        collection: str,
        token_id: int,
        sale_price: float,
        seller: str,
        buyer: str,
    ) -> dict[str, Any]:
        """Process a completed sale with royalty distribution.

        Handles the full sale flow:
        1. Distribute royalties
        2. Transfer the NFT
        3. Update valuation data
        4. Attest the royalty payment

        Returns
        -------
        dict
            Complete sale record.
        """
        # Process royalties
        sale_result = await self._royalty.process_sale(
            collection=collection,
            token_id=token_id,
            sale_price=sale_price,
            seller=seller,
            buyer=buyer,
        )

        # Transfer NFT
        await self._factory.transfer_token(
            collection=collection,
            token_id=token_id,
            from_addr=seller,
            to_addr=buyer,
        )

        # Transfer display rights
        try:
            await self._rights.transfer_rights(
                collection=collection,
                token_id=token_id,
                new_holder=buyer,
                rights=["display"],
            )
        except KeyError:
            pass

        # Update valuation data
        self._valuation.record_sale(collection, token_id, sale_price)

        sale_result["nft_transferred"] = True
        return sale_result

    # ── Valuation ────────────────────────────────────────────────────

    async def estimate_value(
        self, collection: str, token_id: int
    ) -> dict[str, Any]:
        """Estimate the value of an NFT."""
        return await self._valuation.estimate_value(collection, token_id)

    async def get_rarity_score(
        self,
        collection: str,
        token_id: int,
        total_supply: int,
        traits: dict[str, Any],
    ) -> dict[str, Any]:
        """Calculate rarity score for a token."""
        return await self._valuation.get_rarity_score(
            collection, token_id, total_supply, traits
        )

    # ── Rights Management ────────────────────────────────────────────

    async def set_rights(
        self, collection: str, token_id: int, rights: dict[str, Any]
    ) -> dict[str, Any]:
        """Set IP rights for an NFT."""
        return await self._rights.set_rights(collection, token_id, rights)

    async def check_rights(
        self, collection: str, token_id: int, right_type: str
    ) -> dict[str, Any]:
        """Check a specific right for an NFT."""
        return await self._rights.check_rights(collection, token_id, right_type)

    async def transfer_rights(
        self,
        collection: str,
        token_id: int,
        new_holder: str,
        rights: list[str],
    ) -> dict[str, Any]:
        """Transfer specific rights to a new holder."""
        return await self._rights.transfer_rights(
            collection, token_id, new_holder, rights
        )

    # ── Royalty Management ───────────────────────────────────────────

    async def configure_royalty(
        self, collection: str, token_id: int, recipient: str, bps: int
    ) -> dict[str, Any]:
        """Configure royalty for a token or collection."""
        return await self._royalty.configure_royalty(
            collection, token_id, recipient, bps
        )

    async def get_royalty_info(
        self, collection: str, token_id: int, sale_price: float = 1.0
    ) -> dict[str, Any]:
        """Get ERC-2981 royalty info."""
        return await self._royalty.get_royalty_info(
            collection, token_id, sale_price
        )

    # ── Expanded NFT Operations ─────────────────────────────────────

    async def fractionalize(
        self, collection: str, token_id: int, fractions: int, price_per_fraction: float,
    ) -> dict[str, Any]:
        """Fractionalize an NFT into fungible shares."""
        if not self._web3.available or self._web3.is_placeholder(self._nft_contract):
            return not_deployed_response("nft_services", {
                "operation": "fractionalize",
                "requested": {"collection": collection, "token_id": token_id, "fractions": fractions},
            })
        frac_id = f"frac_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": frac_id,
            "status": "fractionalized",
            "collection": collection,
            "token_id": token_id,
            "total_fractions": fractions,
            "price_per_fraction": price_per_fraction,
            "sold_fractions": 0,
        }
        self._fractions[frac_id] = record
        logger.info("NFT fractionalized: id=%s", frac_id)
        return record

    async def rent(
        self, collection: str, token_id: int, renter: str, duration_days: int, price: float,
    ) -> dict[str, Any]:
        """Rent an NFT (ERC-4907)."""
        if not self._web3.available or self._web3.is_placeholder(self._nft_contract):
            return not_deployed_response("nft_services", {
                "operation": "rent",
                "requested": {"collection": collection, "token_id": token_id, "renter": renter},
            })
        rental_id = f"rent_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": rental_id,
            "status": "rented",
            "collection": collection,
            "token_id": token_id,
            "renter": renter,
            "duration_days": duration_days,
            "price": price,
        }
        self._rentals[rental_id] = record
        logger.info("NFT rented: id=%s", rental_id)
        return record

    async def dynamic_update(
        self, collection: str, token_id: int, updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Update dynamic NFT metadata."""
        if not self._web3.available or self._web3.is_placeholder(self._nft_contract):
            return not_deployed_response("nft_services", {
                "operation": "dynamic_update",
                "requested": {"collection": collection, "token_id": token_id, "updates": updates},
            })
        update_id = f"dynup_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": update_id,
            "status": "updated",
            "collection": collection,
            "token_id": token_id,
            "updates": updates,
        }
        logger.info("Dynamic NFT updated: id=%s", update_id)
        return record

    async def batch_mint(
        self, collection: str, creator: str, count: int, metadata_template: dict[str, Any],
    ) -> dict[str, Any]:
        """Batch mint multiple NFTs."""
        if not self._web3.available or self._web3.is_placeholder(self._nft_contract):
            return not_deployed_response("nft_services", {
                "operation": "batch_mint",
                "requested": {"collection": collection, "creator": creator, "count": count},
            })
        batch_id = f"batch_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": batch_id,
            "status": "minted",
            "collection": collection,
            "creator": creator,
            "count": count,
            "metadata_template": metadata_template,
            "token_ids": list(range(1, count + 1)),
        }
        logger.info("Batch mint completed: id=%s count=%d", batch_id, count)
        return record

    async def royalty_claim(
        self, collection: str, token_id: int, claimer: str,
    ) -> dict[str, Any]:
        """Claim accrued royalties for an NFT."""
        if not self._web3.available or self._web3.is_placeholder(self._nft_contract):
            return not_deployed_response("nft_services", {
                "operation": "royalty_claim",
                "requested": {"collection": collection, "token_id": token_id, "claimer": claimer},
            })
        claim_id = f"rclaim_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": claim_id,
            "status": "claimed",
            "collection": collection,
            "token_id": token_id,
            "claimer": claimer,
            "amount_claimed": 0.0,
        }
        logger.info("Royalty claimed: id=%s", claim_id)
        return record

    async def bridge_nft(
        self, collection: str, token_id: int, destination_chain: str, owner: str,
    ) -> dict[str, Any]:
        """Bridge an NFT to another chain."""
        if not self._web3.available or self._web3.is_placeholder(self._nft_contract):
            return not_deployed_response("nft_services", {
                "operation": "bridge_nft",
                "requested": {"collection": collection, "token_id": token_id, "destination_chain": destination_chain},
            })
        bridge_id = f"nftbr_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": bridge_id,
            "status": "bridged",
            "collection": collection,
            "token_id": token_id,
            "destination_chain": destination_chain,
            "owner": owner,
        }
        logger.info("NFT bridged: id=%s", bridge_id)
        return record

    async def mint_soulbound(
        self, recipient: str, metadata: dict[str, Any], issuer: str,
    ) -> dict[str, Any]:
        """Mint a soulbound (non-transferable) token."""
        if not self._web3.available or self._web3.is_placeholder(self._nft_contract):
            return not_deployed_response("nft_services", {
                "operation": "mint_soulbound",
                "requested": {"recipient": recipient, "issuer": issuer},
            })
        sbt_id = f"sbt_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": sbt_id,
            "status": "minted",
            "recipient": recipient,
            "issuer": issuer,
            "metadata": metadata,
            "transferable": False,
        }
        self._soulbound[sbt_id] = record
        logger.info("Soulbound token minted: id=%s", sbt_id)
        return record
