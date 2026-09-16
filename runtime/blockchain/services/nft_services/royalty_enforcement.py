"""
RoyaltyEnforcement — ensure royalties are paid on every NFT sale.

ERC-2981 compliant royalty configuration and automatic distribution.
Attests royalty payments via the attestation service (Component 8)
for on-chain proof of payment.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.nft_services._guards import (
    require_finite_amount,
    require_finite_bps,
)

logger = logging.getLogger(__name__)

# Maximum royalty: 25% (2500 bps)
_MAX_ROYALTY_BPS = 2500
# Minimum sale price to enforce royalties (dust prevention)
_MIN_SALE_PRICE = 0.0001


class RoyaltyEnforcement:
    """Enforce ERC-2981 royalty payments on NFT sales.

    Parameters
    ----------
    config : dict
        Platform config.  Reads:
        - ``blockchain.platform_wallet`` — platform fee recipient
        - ``blockchain.platform_fee_bps`` — platform fee (default 250)
        - ``nft.royalty.max_bps`` — maximum royalty (default 2500).
          ``nft.max_royalty_bps`` (the key factory.py documents) is ALSO
          honoured; the nested form wins if both are set. 22-G — they were two
          keys for one concept and only one governed the live path.
    attestation_service : object, optional
        AttestationService instance (Component 8) for recording
        royalty payment attestations.
    """

    def __init__(
        self,
        config: dict,
        attestation_service: Any = None,
    ) -> None:
        self._config = config
        self._attestation = attestation_service

        bc = config.get("blockchain", {})
        self._platform_wallet: str = bc.get("platform_wallet", "")
        self._platform_fee_bps: int = int(bc.get("platform_fee_bps", 250))
        # 22-G. TWO CONFIG KEYS FOR ONE CONCEPT, AND THE DOCUMENTED ONE DID
        # NOT GOVERN THE LIVE PATH.
        #
        #   factory.py:30 documents `nft.max_royalty_bps` and factory.py:44
        #   reads it — governing deploy/mint, which REFUSE under the shipped
        #   config.
        #   THIS class documented `nft.royalty.max_bps` and read only that —
        #   and this class is what `configure_nft_royalty` uses, one of only
        #   SIX of seventeen nft actions that executes at all.
        #
        # MEASURED: with `nft.max_royalty_bps = 100`, a request for 2500 bps
        # was CONFIGURED AT 2500 on the live path. With
        # `nft.royalty.max_bps = 100` it was refused. An operator who read the
        # factory's documentation and set the cap it names capped only the
        # paths that already refuse.
        #
        # §AP's 19-x variant — a document points at a control that does not
        # govern the live path — and R-21.1's shape at key granularity rather
        # than service granularity.
        #
        # BOTH KEYS ARE NOW READ, nested first so an existing deployment's
        # value keeps winning (§AQ class 3: an operator who already set
        # `nft.royalty.max_bps` must not silently get a different cap).
        _nft_cfg = config.get("nft", {}) or {}
        _nested = (_nft_cfg.get("royalty", {}) or {}).get("max_bps")
        _flat = _nft_cfg.get("max_royalty_bps")
        self._max_royalty_bps: int = int(
            _nested if _nested is not None
            else (_flat if _flat is not None else _MAX_ROYALTY_BPS)
        )

        # Royalty configurations: {collection:token_id: config}
        self._royalty_configs: dict[str, dict[str, Any]] = {}
        # Collection-level defaults
        self._collection_defaults: dict[str, dict[str, Any]] = {}
        # Sale records
        self._sales: list[dict[str, Any]] = []

    async def configure_royalty(
        self,
        collection: str,
        token_id: int,
        recipient: str,
        bps: int,
        caller_identity: str = "",
        caller_source: str = "",
    ) -> dict[str, Any]:
        """Configure royalty for a specific token (ERC-2981 compatible).

        Parameters
        ----------
        collection : str
            Collection contract address.
        token_id : int
            Token ID. Use ``-1`` for collection-wide default.
        recipient : str
            Royalty recipient address.
        bps : int
            Royalty in basis points (100 = 1%).

        Returns
        -------
        dict
            Royalty configuration confirmation.
        """
        if not recipient or not recipient.startswith("0x"):
            raise ValueError("Valid recipient address required")
        # 17-B. THE CAP IS THE POINT, AND NaN WALKS BETWEEN ITS TWO BOUNDS.
        # `bps < 0 or bps > cap` is a DISJUNCTION: `nan < 0` is False and
        # `nan > cap` is False, so BOTH disjuncts fail, the disjunction is
        # False, and the raise is skipped — a NaN bps was stored as the
        # collection's royalty rate.
        #
        # This is the shape a careful author writes SPECIFICALLY to be thorough:
        # two bounds, both directions covered, defence in depth. It is the
        # strongest evidence yet for §W's rule that EVERY COMPARISON IS WEAK —
        # adding a second comparison to a guard does not strengthen it against a
        # value for which every comparison is False. It widens the gap.
        bps = require_finite_bps(bps, "bps", self._max_royalty_bps)
        if bps < 0 or bps > self._max_royalty_bps:
            raise ValueError(
                f"Royalty must be between 0 and {self._max_royalty_bps} bps "
                f"({self._max_royalty_bps / 100:.1f}%)"
            )

        # 22-A. WHO SET THIS, AND MAY THIS CALLER CHANGE IT.
        #
        # MEASURED at pin 84a6c3e, through the real ServiceDispatcher, under
        # THE SHIPPED CONFIG (this is one of only 6 of 17 nft actions that
        # executes at all — the rest crash or refuse):
        #
        #   1. creator configures  -> configured  recipient=0x1111 bps=500
        #   2. STRANGER, caller_identity=""  -> configured  recipient=0x2222
        #                                       bps=2500   no refusal
        #   3. get_royalty_info    -> receiver=0x2222
        #   4. buy_nft             -> royalty split computed for 0x2222
        #
        # The stored entry had NO attribution field at all, so after the
        # overwrite nothing in the platform's own store distinguished the
        # creator's configuration from the stranger's except the recipient
        # value — which is the thing under dispute.
        #
        # WHY THIS IS FIXABLE HERE AND THE OWNERSHIP CHECK IS NOT. The package
        # justifies having no authority check with "this platform has no
        # ownership record to check against" (service.py:604). That is TRUE of
        # token ownership, which lives on-chain, and FALSE of this record: the
        # royalty configuration is the PLATFORM'S OWN store, written by this
        # method, and it knows who wrote it first. §AI.1 — an absence
        # established at the ownership scope, stated at the whole-domain scope.
        #
        # THE RULE: AN UNIDENTIFIED CALLER MAY CREATE, NEVER MODIFY.
        #
        # An identified setter owns the entry — only that identity may change
        # it. An entry whose setter is UNKNOWN may not be changed by an
        # unidentified caller either, and the reason is the measurement: under
        # the SHIPPED config there is no authenticated identity at all
        # (register item 0), so a rule that only protected identified setters
        # would protect nothing in the deployment we actually ship.
        #
        # CHECKED, not assumed, that this breaks no legitimate flow (§AQ
        # class 3): the two in-package writers each create a FRESH key —
        # `create_collection` writes the collection default once
        # (service.py:188) and `mint` writes a per-token entry
        # (service.py:242). Neither overwrites an existing entry, so neither
        # is refused. What is refused is precisely the external re-write,
        # which is the attack.
        #
        # The honest residue, stated rather than hidden: with no identity
        # available, re-configuring a royalty legitimately now requires a
        # caller bound to the identity that set it. That is a real cost and it
        # is the correct direction — the alternative is the measured hijack.
        #
        # WHOM THIS STOPS. `caller_identity` is whatever the entry point bound.
        # It is derived only from a session; configure_nft_royalty is also
        # reachable through POST /api/v1/capabilities/{id}/invoke, where a
        # caller with no session (holding the operator key, or on a gateway with
        # auth off) is bound to the X-Wallet-Address header or a body
        # wallet/from/sender/account field or params.from it wrote. That caller
        # can name the original setter and pass. The rule stops a session
        # caller, and a caller that binds no identity; against a written
        # identity it keeps attribution consistent, not the recipient safe.
        _set_by = caller_identity or ""
        _set_by_source = caller_source or (
            "authenticated" if _set_by else "unauthenticated"
        )
        _existing = (
            self._collection_defaults.get(collection)
            if token_id == -1
            else self._royalty_configs.get(f"{collection}:{token_id}")
        )
        if _existing is not None:
            _owner = str(_existing.get("set_by") or "")
            _may_change = bool(_set_by) and _owner.lower() == _set_by.lower()
            if not _may_change:
                raise PermissionError(
                    f"royalty for {collection} #{token_id} was configured by "
                    f"{_owner or '<an unidentified caller>'} and cannot be "
                    f"changed by {_set_by or '<an unidentified caller>'}. The royalty "
                    f"destination decides who is paid on every future sale; "
                    f"the platform wrote this record itself and will not let a "
                    f"second party redirect it."
                )

        now = int(time.time())
        config_entry = {
            "collection": collection,
            "token_id": token_id,
            "recipient": recipient,
            "bps": bps,
            "percentage": f"{bps / 100:.2f}%",
            "configured_at": now,
            # 22-A. Written at both levels for the same reason 17-J gives:
            # WHO, and separately HOW WE KNOW. `set_by: ""` alone cannot
            # distinguish "nobody was authenticated" from "we did not look".
            "set_by": _set_by,
            "set_by_source": _set_by_source,
        }

        if token_id == -1:
            # Collection-wide default
            self._collection_defaults[collection] = config_entry
            logger.info(
                "Collection royalty set: %s -> %s at %d bps",
                collection[:10], recipient, bps,
            )
        else:
            key = f"{collection}:{token_id}"
            self._royalty_configs[key] = config_entry
            logger.info(
                "Token royalty set: %s #%d -> %s at %d bps",
                collection[:10], token_id, recipient, bps,
            )

        return {
            "status": "configured",
            **config_entry,
        }

    async def process_sale(
        self,
        collection: str,
        token_id: int,
        sale_price: float,
        seller: str,
        buyer: str,
    ) -> dict[str, Any]:
        """Process an NFT sale with automatic royalty distribution.

        Calculates and distributes:
        1. Creator royalty (ERC-2981)
        2. Platform fee
        3. Seller proceeds

        Parameters
        ----------
        collection : str
            Collection contract address.
        token_id : int
            Token ID.
        sale_price : float
            Sale price in ETH.
        seller : str
            Seller wallet address.
        buyer : str
            Buyer wallet address.

        Returns
        -------
        dict
            Sale breakdown with royalty, platform fee, and seller proceeds.
        """
        # 17-B. THE FLOOR GUARD BELOW CANNOT SEE NaN: `nan < 0.0001` is False,
        # so it was skipped and the sale was priced at NaN throughout. Reject
        # non-finite BEFORE the comparison that is supposed to reject it.
        sale_price = require_finite_amount(sale_price, "sale_price")
        if sale_price < _MIN_SALE_PRICE:
            raise ValueError(
                f"Sale price {sale_price} is below minimum {_MIN_SALE_PRICE}"
            )

        # Get royalty configuration
        royalty_config = self._get_royalty_config(collection, token_id)
        royalty_bps = royalty_config.get("bps", 0) if royalty_config else 0
        royalty_recipient = royalty_config.get("recipient", "") if royalty_config else ""

        # Calculate amounts
        royalty_amount = (sale_price * royalty_bps) / 10000
        platform_fee = (sale_price * self._platform_fee_bps) / 10000
        seller_proceeds = sale_price - royalty_amount - platform_fee

        sale_id = f"sale_{uuid.uuid4().hex[:16]}"
        now = int(time.time())

        sale_record: dict[str, Any] = {
            "sale_id": sale_id,
            "collection": collection,
            "token_id": token_id,
            "sale_price": sale_price,
            # 17-A. §U, THE FIFTH SELF-ATTESTATION INSTANCE. `sale_price` is
            # supplied by the party who OWES the royalty computed from it, and
            # nothing here consults a chain receipt, escrow, or oracle — grep
            # over this method for web3/chain/receipt/verify/escrow/oracle
            # returns nothing. Measured with a 10% royalty configured: an
            # honest 10.0 pays the creator 1.0; reporting 1.0 pays 0.1. No
            # malformed input required.
            #
            # There is no price oracle for an arbitrary NFT sale, so the sale
            # price CANNOT be independently established here. What can be fixed
            # is the record's silence about that: 16-G's idiom, provenance
            # preserved rather than a verification invented.
            "price_source": "caller_asserted",
            "price_verified": False,
            "price_disclosure": (
                "sale_price was supplied by the caller and has NOT been "
                "verified against an on-chain transfer, an escrow, or a price "
                "oracle. The royalty and platform fee below are computed from "
                "that unverified figure."
            ),
            "seller": seller,
            "buyer": buyer,
            "royalty": {
                "recipient": royalty_recipient,
                "bps": royalty_bps,
                "amount": round(royalty_amount, 8),
            },
            "platform_fee": {
                "recipient": self._platform_wallet,
                "bps": self._platform_fee_bps,
                "amount": round(platform_fee, 8),
            },
            "seller_proceeds": round(seller_proceeds, 8),
            "timestamp": now,
            # NEW-91: this module computes a split and RECORDS it. It holds no
            # wallet, no balance and no payout rail — nothing here pays anyone.
            # The arithmetic above is real; the settlement it describes has not
            # occurred. Disclosed on the record itself so a reader of
            # `self._sales` cannot mistake a line item for a payment.
            "settled": False,
            "value_moved": False,
            "disclosure": (
                "NOT SETTLED. This is a computed royalty/fee split recorded "
                "locally. No transfer was made to the royalty recipient, the "
                "platform wallet, or the seller."
            ),
        }

        self._sales.append(sale_record)

        # Attest royalty payment via Component 8
        attestation_result = None
        if self._attestation is not None and royalty_amount > 0:
            try:
                attestation_result = await self._attestation.attest(
                    schema_uid="primary",
                    data={
                        "action": "royalty_payment",
                        "category": "royalty",
                        "sale_id": sale_id,
                        "collection": collection,
                        "token_id": token_id,
                        "sale_price": str(sale_price),
                        "royalty_amount": str(royalty_amount),
                        "royalty_recipient": royalty_recipient,
                        "seller": seller,
                        "buyer": buyer,
                    },
                    recipient=royalty_recipient,
                )
                sale_record["attestation"] = attestation_result
            except Exception as exc:
                logger.warning(
                    "Royalty attestation failed for sale %s: %s",
                    sale_id, exc,
                )
                sale_record["attestation"] = {
                    "status": "failed",
                    "error": str(exc),
                }

        logger.info(
            "Sale processed: id=%s %s #%d price=%.4f ETH "
            "royalty=%.4f platform=%.4f seller=%.4f",
            sale_id, collection[:10], token_id, sale_price,
            royalty_amount, platform_fee, seller_proceeds,
        )

        return sale_record

    async def get_royalty_info(
        self, collection: str, token_id: int, sale_price: float = 1.0
    ) -> dict[str, Any]:
        """ERC-2981 compatible royalty info query.

        Parameters
        ----------
        collection : str
            Collection address.
        token_id : int
            Token ID.
        sale_price : float
            Sale price to calculate royalty for.

        Returns
        -------
        dict
            Keys: ``receiver``, ``royalty_amount``, ``bps``.
        """
        config = self._get_royalty_config(collection, token_id)

        if config is None:
            return {
                "receiver": "",
                "royalty_amount": 0,
                "bps": 0,
            }

        amount = (sale_price * config["bps"]) / 10000
        return {
            "receiver": config["recipient"],
            "royalty_amount": round(amount, 8),
            "bps": config["bps"],
        }

    async def get_sales_history(
        self,
        collection: str | None = None,
        token_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get sale history with royalty details."""
        results: list[dict[str, Any]] = []
        for sale in reversed(self._sales):
            if collection and sale["collection"] != collection:
                continue
            if token_id is not None and sale["token_id"] != token_id:
                continue
            results.append(sale)
            if len(results) >= limit:
                break
        return results

    async def get_total_royalties_paid(
        self, recipient: str
    ) -> dict[str, Any]:
        """Get total royalties paid to a specific recipient."""
        total = 0.0
        count = 0
        for sale in self._sales:
            if sale["royalty"]["recipient"] == recipient:
                total += sale["royalty"]["amount"]
                count += 1

        # NEW-91: the key was `total_royalties_eth` on a method named
        # get_total_royalties_PAID. Nothing here was paid: this sums line items
        # this module wrote for itself, with no wallet, balance or payout record
        # anywhere to reconcile against. The arithmetic is real; the word was
        # not. The method name is kept so existing callers still resolve, and
        # the response says plainly what the number is.
        return {
            "recipient": recipient,
            "total_royalties_recorded_eth": round(total, 8),
            "num_sales": count,
            "settled": False,
            "value_moved": False,
            "disclosure": (
                "RECORDED, NOT PAID. This is the sum of royalty amounts this "
                "service computed and stored for its own sale records. No "
                "payment was made and there is no external ledger, wallet or "
                "payout to reconcile this figure against."
            ),
        }

    # ── Internal ──────────────────────────────────────────────────────

    def _get_royalty_config(
        self, collection: str, token_id: int
    ) -> dict[str, Any] | None:
        """Get the applicable royalty config for a token.

        Checks token-specific config first, then collection default.
        """
        key = f"{collection}:{token_id}"
        config = self._royalty_configs.get(key)
        if config is not None:
            return config
        return self._collection_defaults.get(collection)
