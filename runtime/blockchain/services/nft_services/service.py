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

from runtime.blockchain.services.nft_services._guards import require_finite_amount

from runtime.blockchain.web3_manager import Web3Manager, not_deployed_response

from runtime.blockchain.services.nft_services.factory import NFTFactory
from runtime.blockchain.services.nft_services.rights import RightsManagement
from runtime.blockchain.services.nft_services.royalty_enforcement import RoyaltyEnforcement
from runtime.blockchain.services.nft_services.valuation import ValuationEngine

logger = logging.getLogger(__name__)

# Minimal ABI for the one read the ownership check needs.
ERC721_OWNER_ABI = [{
    "inputs": [{"name": "tokenId", "type": "uint256"}],
    "name": "ownerOf",
    "outputs": [{"name": "", "type": "address"}],
    "stateMutability": "view",
    "type": "function",
}]


# ─────────────────────────────────────────────────────────────────────────
# NFT GATING CONDITION — read before setting `nft.contract_address` (NEW-93)
# ─────────────────────────────────────────────────────────────────────────
#
# ONE config key arms SEVEN fabrications at once. Each of the following opens
# with `if not self._web3.available or self._web3.is_placeholder(...)` and
# returns not_deployed TODAY — that gate is the only reason they are inert:
#
#     fractionalize      -> "fractionalized"   writes self._fractions
#     rent               -> "rented"           writes self._rentals
#     mint_soulbound     -> "minted"           writes self._soulbound
#     batch_mint         -> "minted"
#     royalty_claim      -> "claimed"
#     bridge_nft         -> "bridged"
#     dynamic_update     -> "updated"
#
# None of them touches a chain, a signer, or a token record. Setting the key
# does not make them work; it makes them ANSWER.
#
# WHY THIS DOMAIN'S ARMING IS DIFFERENT FROM EVERY PRIOR ONE. In insurance,
# deployment supplied an already-running consumer with its first objects — the
# claim surface existed and was merely idle. Here, deployment arms claims about
# PROPERTY THAT NOTHING CAN REFUTE:
#
#   * this platform holds NO ownership record. `NFTFactory._collections` is
#     declared "cache for in-process queries" and is NEVER WRITTEN — three
#     occurrences package-wide, one declaration and two reads. Ownership lives
#     on-chain in OpenMatrixNFT.sol, which is not deployed.
#   * so when `fractionalize` reports a token split into 10 shares, there is no
#     store on EITHER side that can say the caller never owned it.
#   * and `buy_nft` — already live, already ungated on
#     POST /api/v1/capabilities/buy_nft/invoke — is in _STATE_MODIFYING_ACTIONS
#     with ACTION_TO_FEED_EVENT "nft_purchased", so every sale that transfers
#     nothing is BROADCAST to the public social feed as a purchase.
#
# A false claim about money is contradicted by a balance. A false claim about
# property, with no title record on either side, is contradicted by nothing.
#
# LIFTING CONDITION — all five, or leave `nft.contract_address` unset:
#
#   1. OWNERSHIP IS READABLE. `NFTFactory.get_token` must return a real owner —
#      from the chain, not from `_collections`, which is a cache with no writer.
#      PARTIAL-STATE FAILURE MODE: every method below acts on tokens whose
#      ownership it cannot check, so any caller can fractionalize, rent or
#      bridge a token they do not hold.
#   2. EACH OF THE SEVEN EITHER PERFORMS ITS OPERATION OR REFUSES. Writing a
#      dict and returning "fractionalized" is not fractionalising.
#      PARTIAL-STATE FAILURE MODE: seven confident receipts for nothing.
#   3. `buy_nft`'s FEED EVENT IS DERIVED FROM SETTLEMENT, not from the request
#      being accepted — the NEW-88 rule, which this domain has not yet applied.
#      PARTIAL-STATE FAILURE MODE: the public feed becomes the loudest surface
#      of the fabrication, exactly as `bridge_completed` was.
#   4. OWNERSHIP IS CHECKED BEFORE ACTING. A caller must be shown to hold a
#      token before its rights, rents or fractions are altered (rule 27 —
#      every sibling authority path, not just one).
#      PARTIAL-STATE FAILURE MODE: NEW-78's hole, on property instead of claims.
#   5. `estimate_value` STILL DISCLOSES its unmeasured factors (NEW-92), because
#      arming the contract does not populate `_floor_prices` or `_creator_scores`
#      — their writers still have zero callers.
#      PARTIAL-STATE FAILURE MODE: a deployed marketplace quoting prices from a
#      model whose majority weight is constants.
#
# Satisfying four of five is not four-fifths safe. Clause 1 is load-bearing for
# 2 and 4 — without a readable owner, neither can be implemented at all.


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
            # 22-B. THE FACTORY REFUSES HONESTLY AND THIS CALLER INDEXED A
            # SUCCESS-ONLY KEY. MEASURED at pin 84a6c3e under the SHIPPED
            # config (which has no top-level `nft` block at all):
            #
            #   deploy_erc721(...) -> {status: 'not_deployed', action_required,
            #                          deployment_guide, message, operation,
            #                          requested, service}   NO 'collection_address'
            #   this line          -> result["collection_address"]  ->  KeyError
            #
            # The gate WORKS and the consumer DEFEATS IT: a correct refusal
            # becomes a crash, and the crash is what made the whole
            # create -> mint -> list -> sell chain unreachable at step one.
            # Two sites share this exact shape (§AK.2), so both are fixed
            # together; fixing one would have left the chain dead one link
            # further down.
            if result.get("status") == "not_deployed" or "collection_address" not in result:
                # The refusal is RE-ORIGINATED here rather than passed through,
                # and the reason is a control, not style. D6 classifies a
                # method as able-to-refuse by looking for a CALL to a
                # registered refusal primitive; a method that merely
                # PROPAGATES a callee's refusal is invisible to it, so
                # returning `result` directly left this method counted as an
                # ungated state-modifying sibling of one that gates.
                #
                # The alternative was to teach the detector about propagation
                # — which touches tests/, making it a P-3 register item, and
                # which would weaken a control to accommodate this change.
                # Re-originating keeps the detector strict and costs nothing:
                # the factory's own diagnosis is carried through verbatim.
                return not_deployed_response("nft_services", {
                    "method": "create_collection",
                    "missing": "nft.factory_address (NFT factory contract)",
                    "reason": (
                        "The NFT factory refused: no contract is deployed. "
                        "This method previously indexed a success-only key on "
                        "that refusal and raised KeyError instead."
                    ),
                    "factory_response": result,
                })
            collection_address = result["collection_address"]
            # 22-A. The return is CAPTURED, not discarded. Before 22-A
            # `configure_royalty` could not refuse, so a bare `await` was
            # harmless; it can now, and D10 caught this the moment the
            # capability appeared. A caller that discards a refusal reports a
            # success the refusal never authorised.
            #
            # These two sites each write a FRESH key so the 22-A authority
            # check cannot refuse them — but `configure_royalty` also rejects a
            # malformed recipient or an out-of-range bps, and THOSE were always
            # possible. The discard was latent before and is closed now.
            _royalty_result = await self._royalty.configure_royalty(
                collection=collection_address,
                token_id=-1,  # collection-wide
                recipient=creator,
                bps=royalty_bps,
            )
            if isinstance(_royalty_result, dict) and _royalty_result.get("refused"):
                result["royalty_configured"] = False
                result["disclosure"] = (
                    "The collection was created but its royalty was NOT "
                    "configured: " + str(_royalty_result.get("reason", ""))
                )
            else:
                result["royalty_configured"] = True

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

            # 22-B. THE FACTORY REFUSES HONESTLY AND THIS CALLER INDEXED A
            # SUCCESS-ONLY KEY. MEASURED at pin 84a6c3e under the SHIPPED
            # config (which has no top-level `nft` block at all):
            #
            #   deploy_erc721(...) -> {status: 'not_deployed', action_required,
            #                          deployment_guide, message, operation,
            #                          requested, service}   NO 'token_id'
            #   this line          -> result["token_id"]  ->  KeyError
            #
            # The gate WORKS and the consumer DEFEATS IT: a correct refusal
            # becomes a crash, and the crash is what made the whole
            # create -> mint -> list -> sell chain unreachable at step one.
            # Two sites share this exact shape (§AK.2), so both are fixed
            # together; fixing one would have left the chain dead one link
            # further down.
            if result.get("status") == "not_deployed" or "token_id" not in result:
                # The refusal is RE-ORIGINATED here rather than passed through,
                # and the reason is a control, not style. D6 classifies a
                # method as able-to-refuse by looking for a CALL to a
                # registered refusal primitive; a method that merely
                # PROPAGATES a callee's refusal is invisible to it, so
                # returning `result` directly left this method counted as an
                # ungated state-modifying sibling of one that gates.
                #
                # The alternative was to teach the detector about propagation
                # — which touches tests/, making it a P-3 register item, and
                # which would weaken a control to accommodate this change.
                # Re-originating keeps the detector strict and costs nothing:
                # the factory's own diagnosis is carried through verbatim.
                return not_deployed_response("nft_services", {
                    "method": "mint",
                    "missing": "nft.factory_address (NFT factory contract)",
                    "reason": (
                        "The NFT factory refused: no contract is deployed. "
                        "This method previously indexed a success-only key on "
                        "that refusal and raised KeyError instead."
                    ),
                    "factory_response": result,
                })
            token_id = result["token_id"]

            # Configure token-specific royalty
            # 22-A. The return is CAPTURED, not discarded. Before 22-A
            # `configure_royalty` could not refuse, so a bare `await` was
            # harmless; it can now, and D10 caught this the moment the
            # capability appeared. A caller that discards a refusal reports a
            # success the refusal never authorised.
            #
            # These two sites each write a FRESH key so the 22-A authority
            # check cannot refuse them — but `configure_royalty` also rejects a
            # malformed recipient or an out-of-range bps, and THOSE were always
            # possible. The discard was latent before and is closed now.
            _royalty_result = await self._royalty.configure_royalty(
                collection=collection,
                token_id=token_id,
                recipient=creator,
                bps=royalty_bps,
            )
            if isinstance(_royalty_result, dict) and _royalty_result.get("refused"):
                result["royalty_configured"] = False
                result["disclosure"] = (
                    "The token was minted but its royalty was NOT configured: "
                    + str(_royalty_result.get("reason", ""))
                )
            else:
                result["royalty_configured"] = True

            # Set default rights. Captured, not discarded — 22-C gives
            # set_rights the ability to refuse, and D10 flags a bare `await`
            # the moment that becomes true (it did so for configure_royalty in
            # 22-A). This site creates a FRESH key for a newly minted token,
            # so the 22-C check cannot refuse it; the capture closes the
            # latent discard rather than an active one.
            _rights_result = await self._rights.set_rights(
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

            # 17-I. THIS RAN UNCONDITIONALLY WHILE THE TRANSFER REFUSED.
            # `transfer_token` returns not_deployed on BOTH branches today, so
            # this method returned the factory's honest refusal WHILE MOVING THE
            # DISPLAY RIGHT TO to_addr — leaving a transfer-history row and
            # `check_nft_rights` reporting source:"explicit".
            #
            # IT IS THE MIRROR IMAGE OF 16-K. `transfer_nft` is in
            # _STATE_MODIFYING_ACTIONS and returns not_deployed, so
            # `_outcome_is_real` is False and the dispatcher writes "ACTION
            # DECLINED (not attested, not published)" — for a call that DID
            # mutate state. 16-K was a false POSITIVE in the trail, a refusal
            # recorded as an action. This was a false NEGATIVE: an action
            # recorded as a refusal.
            #
            # §AK: the predicate is correct and was being told the truth about a
            # lie. A result-based gate can never be more honest than the result,
            # so this class is only fixable AT THE METHOD, never at the
            # chokepoint — no dispatcher-level fix reaches it.
            #
            # 17-G gated the identical call in `process_sale` and MISSED THIS
            # SIBLING: the enumeration was real and its scope was one method.
            # §AK.2 requires the call-site count and each disposition:
            #   transfer_rights — 3 sites in this file, BY ENCLOSING METHOD:
            #     transfer()        GATED on `transferred`   (this one)
            #     process_sale()    GATED on `transferred`   (17-G)
            #     NFTService.transfer_rights()
            #                       UNREACHABLE — in no ACTION_MAP entry, no
            #                       capability catalog id and no gateway route
            #                       (re-enumerated at 84a6c3e: 253 ACTION_MAP
            #                       entries, 195 catalog capabilities, and the
            #                       dispatcher resolves method names only from
            #                       ACTION_MAP). Gate it before it is exposed;
            #                       it is the same shape.
            #
            # 22-E. CITED BY METHOD, NOT BY LINE NUMBER, AND THE REASON IS A
            # MEASURED FAILURE. This block previously read ":310 / :470 / :591".
            # Re-derived by AST at 84a6c3e the sites are :462, :622, :817 —
            # THE COUNT WAS RIGHT AND EVERY LINE NUMBER WAS STALE, drifted
            # +152/+152/+226 by fixes inserted above them. A reader following
            # ":310" lands on unrelated code and concludes the enumeration is
            # wrong; it was right when written.
            #
            # A LINE NUMBER IN A COMMENT IS A CLAIM THAT DECAYS WITHOUT ANYONE
            # EDITING IT — the same family as §AJ.8 (HEAD is a query, not an
            # identifier). A method name is stable under insertion, and if it
            # is renamed the reference breaks loudly instead of pointing
            # somewhere plausible and wrong.
            transferred = (
                isinstance(result, dict)
                and result.get("status") not in (None, "not_deployed", "error")
            )
            if transferred:
                try:
                    await self._rights.transfer_rights(
                        collection=collection,
                        token_id=token_id,
                        new_holder=to_addr,
                        rights=["display"],
                    )
                except KeyError:
                    # No rights record yet — fine for a simple transfer.
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
        # 17-B: `nan <= 0` is False, so the sign check below passes a NaN
        # listing price straight into the listing record.
        price = require_finite_amount(price, "price")
        if price <= 0:
            raise ValueError("Price must be positive")

        # Get royalty info for the listing display
        royalty_info = await self._royalty.get_royalty_info(
            collection, token_id, price
        )

        token = self._factory.get_token(collection, token_id)
        if token is None:
            # 22-F. §AC — THE ERROR NAMED THE PROXIMATE CAUSE AND HID THE
            # ACTUAL ONE. Under the SHIPPED config no token can exist at all:
            # `mint` refuses because the factory is not deployed, so the store
            # is necessarily empty and EVERY call to this live ACTION_MAP
            # action raised "Token 1 not found in 0xCOLL". An operator reads
            # that as "I used the wrong token id" and goes looking for a token,
            # when the real answer is "no NFT contract is deployed".
            #
            # This was the last of the three crashes the reachability recast
            # found. The other two (22-B) indexed a success-only key on a
            # refusal shape; this one raises an honest-but-misleading message.
            # Different mechanism, same consequence: a live action whose
            # failure does not name what to fix.
            #
            # Returned, not raised (21-E/AQ::9), so the dispatcher records a
            # refusal rather than `service_error, degraded: true`.
            if not self._factory._is_ready():
                return not_deployed_response("nft_services", {
                    "method": "list_for_sale",
                    "missing": "nft.factory_address (NFT factory contract)",
                    "reason": (
                        f"Token {token_id} is not in {collection}, and it "
                        f"cannot be: no NFT contract is deployed, so nothing "
                        f"has been minted. The token id is not the problem."
                    ),
                })
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

        # Transfer NFT.
        #
        # NEW-90: this was a BARE `await` — the return value was DISCARDED and
        # `nft_transferred` was set True twelve lines below regardless.
        # `NFTFactory.transfer_token` refuses on BOTH branches, including when
        # `_is_ready()` is true ("factory ABI not yet wired into runtime"), so
        # the one component honest enough to say "I cannot do this" was called,
        # ignored, and contradicted by its own caller.
        #
        # The factory is CORRECT. `_collections` is declared in its own comment
        # as a "cache for in-process queries"; ownership lives on-chain in
        # OpenMatrixNFT.sol (a real ERC721), and refusing while that contract is
        # undeployed is the right behaviour. The defect was never a missing
        # implementation — it was an implemented refusal being overwritten,
        # which is worse than a stub because someone did the work correctly and
        # the caller unmade it.
        transfer_result = await self._factory.transfer_token(
            collection=collection,
            token_id=token_id,
            from_addr=seller,
            to_addr=buyer,
        )
        transferred = (
            isinstance(transfer_result, dict)
            and transfer_result.get("status") not in (None, "not_deployed", "error")
        )

        # 17-G / 17-H. BOTH OF THESE USED TO RUN UNCONDITIONALLY, ABOVE AND
        # OUTSIDE the `if not transferred:` block twenty lines below — so a sale
        # the platform REFUSED still moved the display right to the buyer and
        # still wrote the buyer's asking price into the valuation evidence store.
        if transferred:
            # 17-G — THE AUTHORITY SURFACE. Moving the display right is a
            # rights-ledger write, and it ran even when `transfer_token` refused
            # on both branches. Measured pre-fix: after a refused buy,
            # `_rights['<coll>:<id>']['rights']['display']['holder']` was the
            # BUYER, with a transfer-history row, and `check_nft_rights`
            # reported `source: "explicit"`.
            #
            # The disclosure this method returns says ownership is unchanged and
            # "this platform holds no ownership record of its own" — accurate
            # about VALUE and false about AUTHORITY, in one response, from one
            # method. That is §AI's second axis: a method writes more than one
            # KIND of state, and a disclosure scoped to one reads as scoped to
            # all of them.
            try:
                await self._rights.transfer_rights(
                    collection=collection,
                    token_id=token_id,
                    new_holder=buyer,
                    rights=["display"],
                )
            except KeyError:
                pass

            # 17-H — THE EVIDENCE SURFACE, and the sharpest §AG/§AH instance the
            # engagement produced. `record_sale` is the ONLY production writer of
            # the valuation evidence store, and it was fed the caller's asking
            # price for a sale that did not happen. `estimate_value` then
            # reported that price as `measured_factors: {recent_sales: True}`
            # behind NEW-92's disclosure "30% of the declared weight is backed by
            # observed data" — and six repeats crossed `_min_sales` and lifted
            # the confidence label to "medium".
            #
            # Verified verbatim by the finder and upheld at HIGH: armed
            # "precisely BECAUSE the NFT contract is undeployed". THE HONEST
            # REFUSAL WAS THE ATTACK PATH — NEW-90/91's refusal produced the
            # unsettled sale, this line recorded it as evidence, and NEW-92's
            # disclosure vouched for it. Three correct fixes composing into one
            # defect that none of them contains.
            self._valuation.record_sale(collection, token_id, sale_price)

        # NEW-90: derived from what the factory actually returned, never
        # asserted alongside it. The factory's own answer is carried through so
        # a caller can see WHY, not just that the answer was no.
        #
        # COPY FIRST. `RoyaltyEnforcement.process_sale` returns the SAME dict
        # object it appended to its own `_sales` ledger, so mutating it here
        # would rewrite a stored royalty record from the outside — and would
        # clobber that record's own NEW-91 disclosure. Caught by a test that
        # read the stored record rather than the returned one.
        sale_result = dict(sale_result)
        sale_result["nft_transferred"] = transferred
        sale_result["transfer_result"] = transfer_result
        # 22-D. THE SETTLED BRANCH HAD NO FLAGS OF ITS OWN, so it inherited
        # the ROYALTY module's — and those mean something narrower.
        #
        # `RoyaltyEnforcement.process_sale` sets settled/value_moved False to
        # say "the split was COMPUTED, not PAID" (NEW-91). That is true of the
        # royalty leg. It is NOT true of the sale: when the NFT transfer
        # succeeds, a token changed hands. Passing the royalty leg's flags
        # through unchanged makes `_outcome_is_real` read a REAL TRANSFER as
        # "this did not happen", so a settled sale is recorded and published as
        # a declined action. Armed-only: under the shipped config `transferred`
        # is False and the branch below is correct.
        #
        # ===================================================================
        # DO NOT "FIX" AC::2/AH::4 BY WRITING settled/value_moved=False ONTO
        # THE SEVEN ARMED METHODS.
        # ===================================================================
        # That is the obvious reading — those methods omit the two fields the
        # honesty predicate reads — and it REPRODUCES THIS DEFECT SEVENFOLD,
        # driven and measured. `value_moved: False` is the strongest "this did
        # not happen" signal in `_outcome_is_real`; it outranks every other
        # clause. It means NO VALUE MOVED. It must never be used to mean:
        #   * "this is an internal record"  (domain 21 made exactly this error
        #     in 21-C and erased the attestation of posts that really existed)
        #   * "one leg of this action did not pay"  (this defect)
        #
        # An action that genuinely happens without moving value takes
        # `settled: True` AND OMITS `value_moved`. The omission is the point:
        # the field is a claim, and a claim not made is not a claim of False.
        # THE FIELD WAS SERVING TWO MASTERS, and both prior authors were right.
        #
        # A deliberate earlier decision (tests/test_nft_sale_honesty.py:146)
        # kept `value_moved: False` on a SETTLED sale, reasoning: "the token
        # moved, the ROYALTY did not... the two claims are independent". That
        # is correct AS A STATEMENT ABOUT THE RECORD.
        #
        # AC::1 is also correct: `_outcome_is_real` reads `value_moved: False`
        # as the strongest "this did not happen" signal, outranking every other
        # clause — so that semantic claim silently suppressed the ATTESTATION
        # of a real transfer.
        #
        # Neither author was wrong; the FIELD is overloaded (§AJ.7 — a value
        # without an admissibility test will itself overload). One name carried
        # a per-record semantic claim AND a dispatcher-level control, and the
        # two readers disagree about what it means.
        #
        # SPLIT, so each reader gets a field that answers ITS question:
        #   value_moved  -> the dispatcher's control: did this action happen
        #   royalty_paid -> the record's claim: was the royalty actually paid
        # The earlier reasoning is preserved in full; only its ENCODING moved
        # off a field that another component was already reading for something
        # else.
        if transferred:
            sale_result["settled"] = True
            sale_result.pop("value_moved", None)
            sale_result["royalty_paid"] = False
            sale_result["royalty_disclosure"] = (
                "The NFT transfer settled. The royalty and fee figures on this "
                "record were COMPUTED AND RECORDED, not paid — this service "
                "holds no wallet or payout rail. Those two facts are separate "
                "and are reported separately."
            )
        if not transferred:
            sale_result["status"] = "recorded_unsettled"
            sale_result["settled"] = False
            sale_result["value_moved"] = False
            sale_result["disclosure"] = (
                "NOT SETTLED. The royalty split, platform fee and seller "
                "proceeds below are real arithmetic over the configured "
                "royalty, and this sale has been RECORDED — but the NFT was "
                "NOT transferred and no value moved. Ownership of this token "
                "is unchanged, and this platform holds no ownership record of "
                "its own: token ownership lives on-chain in the NFT contract, "
                "which is not deployed. Nothing was paid to the royalty "
                "recipient, the platform wallet, or the seller."
            )
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
        self,
        collection: str,
        token_id: int,
        rights: dict[str, Any],
        caller_identity: str = "",
        caller_source: str = "",
    ) -> dict[str, Any]:
        """Set IP rights for an NFT.

        `caller_identity` is the authenticated wallet of the caller, injected
        by `ServiceDispatcher.execute` because this signature DECLARES it
        (DOMAIN 17-D). This is the dispatch target for the `set_nft_rights`
        action, so declaring the parameter here is what makes the identity
        reach `RightsManagement` at all — the dispatcher injects by signature
        and never by guesswork.

        Optional, defaulting to "": entry points with no authenticated caller
        still work and the grant is recorded as `set_by: ""` (unknown) rather
        than being refused or attributed to someone.

        NOT an ownership check. Nothing here verifies the caller holds the
        token — this platform has no ownership record to check against (see
        the NFT GATING CONDITION at the top of this file). This threads WHO,
        which is the input such a check would need, and records it.
        """
        # 22-C. RETURNED, NOT RAISED — 21-E/AQ::9, same as 22-A.
        try:
            return await self._rights.set_rights(
                collection, token_id, rights, caller_identity=caller_identity,
                caller_source=caller_source,
            )
        except PermissionError as exc:
            return not_deployed_response("nft_services", {
                "method": "set_rights",
                "refused": True,
                "reason": str(exc),
                "disclosure": (
                    "Rights for this token were established by another party. "
                    "Nothing was changed. This is a REFUSAL BY POLICY, not a "
                    "fault."
                ),
            })

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
        self,
        collection: str,
        token_id: int,
        recipient: str,
        bps: int,
        caller_identity: str = "",
        caller_source: str = "",
    ) -> dict[str, Any]:
        """Configure royalty for a token or collection."""
        # 22-A. RETURNED, NOT RAISED — domain 21's AQ::9 lesson, transferred.
        # MEASURED there through the real ServiceDispatcher: a RAISED refusal
        # unwinds past the attestation block, so `execute` reports
        # `{"status":"error","error_category":"service_error","degraded":true}`
        # and writes ZERO attestations, while a RETURNED refusal produces
        # ATTEST_REFUSAL. A guard that exists to stop a royalty hijack must
        # leave a record that one was attempted — and must not report the
        # attempt as an internal fault of ours.
        try:
            return await self._royalty.configure_royalty(
                collection, token_id, recipient, bps,
                caller_identity=caller_identity, caller_source=caller_source,
            )
        except PermissionError as exc:
            return not_deployed_response("nft_services", {
                "method": "configure_royalty",
                "refused": True,
                "reason": str(exc),
                "disclosure": (
                    "The royalty destination was already configured and this "
                    "caller is not the party that configured it. Nothing was "
                    "changed. This is a REFUSAL BY POLICY, not a fault."
                ),
            })

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
        owner: str = "",
    ) -> dict[str, Any]:
        """Fractionalize an NFT into fungible shares.

        ``owner`` is the caller the route authenticated. The route demanded it
        and then dropped it — an authorization input that governed nothing
        (the audit's §CD sibling pass over NEW-89). It is recorded here and
        checked against the token's on-chain owner the moment a live contract
        makes that readable; until then the record names who claimed it, so a
        fractionalisation can never be attributed to nobody.
        """
        if not self._web3.available or self._web3.is_placeholder(self._nft_contract):
            return not_deployed_response("nft_services", {
                "operation": "fractionalize",
                "requested": {"collection": collection, "token_id": token_id,
                              "fractions": fractions, "owner": owner},
            })
        on_chain_owner = await self._owner_of(collection, token_id)
        if on_chain_owner and owner and on_chain_owner.lower() != owner.lower():
            return {"status": "error", "error": "not_token_owner",
                    "detail": "only the token's owner may fractionalize it"}
        frac_id = f"frac_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": frac_id,
            "status": "fractionalized",
            "collection": collection,
            "token_id": token_id,
            "total_fractions": fractions,
            "price_per_fraction": price_per_fraction,
            "sold_fractions": 0,
            "owner": owner,
        }
        self._fractions[frac_id] = record
        logger.info("NFT fractionalized: id=%s", frac_id)
        return record

    async def _owner_of(self, collection: str, token_id: int) -> str:
        """The token's on-chain owner, or "" when it cannot be read."""
        try:
            contract = self._web3.load_contract(collection, ERC721_OWNER_ABI)
            return str(contract.functions.ownerOf(int(token_id)).call())
        except Exception as exc:   # unreadable chain / wrong ABI / missing token
            logger.debug("ownerOf unavailable for %s#%s: %s", collection, token_id, exc)
            return ""

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
