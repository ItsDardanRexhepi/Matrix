"""
NFT-backed loans (BendDAO, NFTfi, Arcade) and NFT breeding mechanics.

This service wires NFT-collateralised lending protocols to the platform.
Three operations are exposed:

- ``borrow_against_nft`` — open an NFT-backed loan against a lending pool
  (BendDAO ``LendPool.borrow`` / NFTfi / Arcade style). On-chain WRITE.
- ``liquidate_nft_loan`` — liquidate / trigger auction on a defaulted
  NFT-backed loan (BendDAO ``LendPool.liquidate``). On-chain WRITE.
- ``breed_nft`` — invoke a breeding/merging game contract that produces a
  child NFT from two parents. On-chain WRITE.

Every on-chain WRITE is signed by the **platform paymaster account** (via
``Web3Manager.send_transaction``) so the platform pays gas and no user key
is ever custodied server-side.

NON-CUSTODIAL NOTE: NFT lending moves real user value (the user's NFT
collateral and the borrowed reserve asset). The server NEVER signs with or
moves a user's wallet funds. The platform paymaster only sponsors gas. When
an operation would move a *user's* collateral or borrowed funds, the
``onBehalfOf`` / borrower address must be the platform-controlled account
or the caller must supply a target the platform legitimately operates;
this service operates at the platform level (``onBehalfOf`` defaults to the
platform account) and never custodies a third-party user's NFT or key. A
production deployment should instead return a prepared/unsigned UserOp for
the user's own wallet to sign — that path is gated behind operator config.

Each method gates on its required config FIRST and returns the canonical
CREDENTIAL-GATED ``not_deployed_response`` when a credential is missing or
the chain is unreachable. The real protocol call is only attempted once the
operator has populated the relevant ``services.nft_lending`` config keys.

Config keys (read from ``services.nft_lending``):
    - ``pool_address``      — lending-pool / LoanCore contract address for
                              the selected protocol (REQUIRED — no default;
                              BendDAO LendPool, NFTfi DirectLoan, or Arcade
                              LoanCore depending on ``protocol``)
    - ``protocol``          — "benddao" | "nftfi" | "arcade" (default
                              "benddao"); selects the ABI / method shape
    - ``reserve_asset``     — ERC-20 reserve borrowed against the NFT
                              (e.g. WETH/USDC); REQUIRED for borrow
    - ``breed_contract``    — game/breeding contract address (REQUIRED for
                              ``breed_nft``; no canonical default)
"""

from __future__ import annotations

import logging
from typing import Any

from runtime.blockchain.web3_manager import (
    Web3Manager,
    is_placeholder_value,
    not_deployed_response,
)

logger = logging.getLogger(__name__)

# ── Minimal, function-specific ABIs ──────────────────────────────────────
# Each ABI contains ONLY the function this service invokes. Signatures are
# taken from each protocol's public interface; where a signature could not
# be pinned to an on-chain-verified source it is marked UNVERIFIED.

# BendDAO LendPool.borrow — verified against BendDAO ILendPool interface.
# borrow(reserveAsset, amount, nftAsset, nftTokenId, onBehalfOf, referralCode)
_BENDDAO_BORROW_ABI: list[dict] = [
    {
        "type": "function",
        "name": "borrow",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "reserveAsset", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "nftAsset", "type": "address"},
            {"name": "nftTokenId", "type": "uint256"},
            {"name": "onBehalfOf", "type": "address"},
            {"name": "referralCode", "type": "uint16"},
        ],
        "outputs": [],
    },
]

# BendDAO LendPool.liquidate — verified against BendDAO ILendPool interface.
# liquidate(nftAsset, nftTokenId, amount)
_BENDDAO_LIQUIDATE_ABI: list[dict] = [
    {
        "type": "function",
        "name": "liquidate",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "nftAsset", "type": "address"},
            {"name": "nftTokenId", "type": "uint256"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [],
    },
]

# NFTfi DirectLoanFixedOffer.liquidateOverdueLoan(loanId) — verified against
# the NFTfi v2 DirectLoanFixedOffer interface.
_NFTFI_LIQUIDATE_ABI: list[dict] = [
    {
        "type": "function",
        "name": "liquidateOverdueLoan",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "_loanId", "type": "uint32"}],
        "outputs": [],
    },
]

# Arcade RepaymentController.claim(loanId) — closes/forecloses a defaulted
# Arcade loan. UNVERIFIED: Arcade's controller method names have changed
# across protocol versions; the operator must confirm against the deployed
# RepaymentController for their network before relying on this path.
_ARCADE_CLAIM_ABI: list[dict] = [
    {
        "type": "function",
        "name": "claim",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "loanId", "type": "uint256"}],
        "outputs": [],
    },
]

# Generic NFT-breeding/merge game contract. UNVERIFIED: there is no
# canonical breeding standard — ``breed(uint256 parentA, uint256 parentB)``
# is a common shape (e.g. CryptoKitties-style ``breedWith``), but the
# operator MUST confirm the real signature against their deployed breeding
# contract before this path produces a correct child token.
_BREED_ABI: list[dict] = [
    {
        "type": "function",
        "name": "breed",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "parentA", "type": "uint256"},
            {"name": "parentB", "type": "uint256"},
        ],
        "outputs": [{"name": "childId", "type": "uint256"}],
    },
]


class NFTLendingService:
    """NFT-backed loans (BendDAO, NFTfi, Arcade) and NFT breeding mechanics."""

    service_name = "nft_lending"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    def _cfg(self) -> dict:
        """Return this service's own config sub-dict (``services.nft_lending``)."""
        return self._config.get("services", {}).get(self.service_name, {})

    def _protocol(self) -> str:
        """Selected lending protocol — 'benddao' | 'nftfi' | 'arcade'."""
        proto = self._cfg().get("protocol", "") or "benddao"
        return str(proto).strip().lower()

    async def borrow_against_nft(self, **params: Any) -> dict:
        """Open an NFT-backed loan against the configured lending pool.

        Params: ``nft_asset`` (NFT collection address), ``nft_token_id``,
        ``amount`` (reserve amount in wei), optional ``on_behalf_of`` (loan
        beneficiary; defaults to the platform paymaster account),
        optional ``referral_code`` (default 0).

        On-chain WRITE: BendDAO ``LendPool.borrow(reserveAsset, amount,
        nftAsset, nftTokenId, onBehalfOf, referralCode)``, signed by the
        platform paymaster (gas-sponsored).
        """
        nft_asset = params.get("nft_asset") or params.get("collection")
        nft_token_id = params.get("nft_token_id")
        if nft_token_id is None:
            nft_token_id = params.get("token_id")
        amount = params.get("amount")
        on_behalf_of = params.get("on_behalf_of")
        referral_code = int(params.get("referral_code") or 0)

        cfg = self._cfg()
        pool_address = cfg.get("pool_address", "")
        reserve_asset = cfg.get("reserve_asset", "")
        protocol = self._protocol()

        # ── CREDENTIAL-GATED gate FIRST ──────────────────────────────
        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "borrow_against_nft",
                "missing": "blockchain.rpc_url",
                "protocol": "NFT lending (BendDAO/NFTfi/Arcade)",
            })
        if is_placeholder_value(pool_address):
            return not_deployed_response(self.service_name, extra={
                "method": "borrow_against_nft",
                "missing": "services.nft_lending.pool_address",
                "protocol": f"NFT lending ({protocol})",
            })
        if is_placeholder_value(reserve_asset):
            return not_deployed_response(self.service_name, extra={
                "method": "borrow_against_nft",
                "missing": "services.nft_lending.reserve_asset",
                "protocol": f"NFT lending ({protocol})",
            })
        if is_placeholder_value(nft_asset) or nft_token_id is None or amount is None:
            return not_deployed_response(self.service_name, extra={
                "method": "borrow_against_nft",
                "missing": "nft_asset / nft_token_id / amount (call params)",
                "protocol": f"NFT lending ({protocol})",
            })
        # Only the BendDAO borrow shape is wired with a verified signature.
        if protocol not in ("benddao", ""):
            return not_deployed_response(self.service_name, extra={
                "method": "borrow_against_nft",
                "missing": f"services.nft_lending.protocol='{protocol}' borrow adapter "
                           "(only 'benddao' borrow signature is wired/verified)",
                "protocol": f"NFT lending ({protocol})",
            })

        # ── REAL path: LendPool.borrow(...) via platform paymaster ───
        try:
            w3 = self._web3.w3
            pool = self._web3.load_contract(pool_address, _BENDDAO_BORROW_ABI)

            reserve_cs = w3.to_checksum_address(reserve_asset)
            nft_cs = w3.to_checksum_address(nft_asset)
            # NON-CUSTODIAL: the loan beneficiary defaults to the platform
            # paymaster account — the server never opens a loan custodying a
            # third-party user's NFT/key. An operator wiring a user-signed
            # flow must pass that wallet via on_behalf_of AND have it sign.
            beneficiary = on_behalf_of or self._web3.get_account().address
            beneficiary_cs = w3.to_checksum_address(beneficiary)

            tx = pool.functions.borrow(
                reserve_cs,
                int(amount),
                nft_cs,
                int(nft_token_id),
                beneficiary_cs,
                referral_code,
            ).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
            })

            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "borrow_against_nft",
                "protocol": "benddao",
                "pool": w3.to_checksum_address(pool_address),
                "reserve_asset": reserve_cs,
                "nft_asset": nft_cs,
                "nft_token_id": int(nft_token_id),
                "amount": int(amount),
                "on_behalf_of": beneficiary_cs,
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("borrow_against_nft on-chain call failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "borrow_against_nft",
                "error": str(exc),
                "error_type": type(exc).__name__,
            }

    async def liquidate_nft_loan(self, **params: Any) -> dict:
        """Liquidate / trigger auction on a defaulted NFT-backed loan.

        Params depend on the protocol:
          - benddao: ``nft_asset``, ``nft_token_id``, optional ``amount``
            (bid amount in wei, default 0 for auction trigger)
          - nftfi:   ``loan_id`` (uint32)
          - arcade:  ``loan_id`` (uint256)

        On-chain WRITE signed by the platform paymaster (gas-sponsored).
        """
        protocol = self._protocol()
        cfg = self._cfg()
        pool_address = cfg.get("pool_address", "")

        nft_asset = params.get("nft_asset") or params.get("collection")
        nft_token_id = params.get("nft_token_id")
        if nft_token_id is None:
            nft_token_id = params.get("token_id")
        amount = params.get("amount")
        loan_id = params.get("loan_id")

        # ── CREDENTIAL-GATED gate FIRST ──────────────────────────────
        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "liquidate_nft_loan",
                "missing": "blockchain.rpc_url",
                "protocol": "NFT lending (BendDAO/NFTfi/Arcade)",
            })
        if is_placeholder_value(pool_address):
            return not_deployed_response(self.service_name, extra={
                "method": "liquidate_nft_loan",
                "missing": "services.nft_lending.pool_address",
                "protocol": f"NFT lending ({protocol})",
            })

        # ── REAL path — protocol-specific liquidation ────────────────
        try:
            w3 = self._web3.w3

            if protocol in ("benddao", ""):
                if is_placeholder_value(nft_asset) or nft_token_id is None:
                    return not_deployed_response(self.service_name, extra={
                        "method": "liquidate_nft_loan",
                        "missing": "nft_asset / nft_token_id (call params)",
                        "protocol": "NFT lending (benddao)",
                    })
                pool = self._web3.load_contract(pool_address, _BENDDAO_LIQUIDATE_ABI)
                nft_cs = w3.to_checksum_address(nft_asset)
                tx = pool.functions.liquidate(
                    nft_cs, int(nft_token_id), int(amount or 0),
                ).build_transaction({
                    "from": self._web3.get_account().address,
                    "chainId": self._web3.chain_id,
                })
                identifier = {"nft_asset": nft_cs, "nft_token_id": int(nft_token_id)}

            elif protocol == "nftfi":
                if loan_id is None:
                    return not_deployed_response(self.service_name, extra={
                        "method": "liquidate_nft_loan",
                        "missing": "loan_id (call param)",
                        "protocol": "NFT lending (nftfi)",
                    })
                pool = self._web3.load_contract(pool_address, _NFTFI_LIQUIDATE_ABI)
                tx = pool.functions.liquidateOverdueLoan(
                    int(loan_id),
                ).build_transaction({
                    "from": self._web3.get_account().address,
                    "chainId": self._web3.chain_id,
                })
                identifier = {"loan_id": int(loan_id)}

            elif protocol == "arcade":
                # UNVERIFIED Arcade controller method — see _ARCADE_CLAIM_ABI.
                if loan_id is None:
                    return not_deployed_response(self.service_name, extra={
                        "method": "liquidate_nft_loan",
                        "missing": "loan_id (call param)",
                        "protocol": "NFT lending (arcade)",
                    })
                pool = self._web3.load_contract(pool_address, _ARCADE_CLAIM_ABI)
                tx = pool.functions.claim(
                    int(loan_id),
                ).build_transaction({
                    "from": self._web3.get_account().address,
                    "chainId": self._web3.chain_id,
                })
                identifier = {"loan_id": int(loan_id)}

            else:
                return not_deployed_response(self.service_name, extra={
                    "method": "liquidate_nft_loan",
                    "missing": f"services.nft_lending.protocol='{protocol}' "
                               "liquidation adapter (use benddao|nftfi|arcade)",
                    "protocol": f"NFT lending ({protocol})",
                })

            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "liquidate_nft_loan",
                "protocol": protocol or "benddao",
                "pool": w3.to_checksum_address(pool_address),
                **identifier,
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("liquidate_nft_loan on-chain call failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "liquidate_nft_loan",
                "error": str(exc),
                "error_type": type(exc).__name__,
            }

    async def breed_nft(self, **params: Any) -> dict:
        """Breed two parent NFTs into a child via a breeding game contract.

        Params: ``parent_a`` (token id), ``parent_b`` (token id), optional
        ``breed_contract`` override.

        On-chain WRITE: ``breed(parentA, parentB)`` on the configured
        breeding contract, signed by the platform paymaster (gas-sponsored).
        UNVERIFIED signature — see ``_BREED_ABI``.
        """
        parent_a = params.get("parent_a")
        if parent_a is None:
            parent_a = params.get("parentA")
        parent_b = params.get("parent_b")
        if parent_b is None:
            parent_b = params.get("parentB")

        cfg = self._cfg()
        breed_contract = params.get("breed_contract") or cfg.get("breed_contract", "")

        # ── CREDENTIAL-GATED gate FIRST ──────────────────────────────
        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "breed_nft",
                "missing": "blockchain.rpc_url",
                "protocol": "NFT breeding (game contract)",
            })
        if is_placeholder_value(breed_contract):
            return not_deployed_response(self.service_name, extra={
                "method": "breed_nft",
                "missing": "services.nft_lending.breed_contract",
                "protocol": "NFT breeding (game contract)",
            })
        if parent_a is None or parent_b is None:
            return not_deployed_response(self.service_name, extra={
                "method": "breed_nft",
                "missing": "parent_a / parent_b (call params)",
                "protocol": "NFT breeding (game contract)",
            })

        # ── REAL path: breed(parentA, parentB) via platform paymaster ─
        try:
            w3 = self._web3.w3
            contract = self._web3.load_contract(breed_contract, _BREED_ABI)

            tx = contract.functions.breed(
                int(parent_a), int(parent_b),
            ).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
            })

            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "breed_nft",
                "protocol": "nft_breeding",
                "breed_contract": w3.to_checksum_address(breed_contract),
                "parent_a": int(parent_a),
                "parent_b": int(parent_b),
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
                "note": "breed() signature UNVERIFIED — confirm against the "
                        "deployed breeding contract before relying on childId.",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("breed_nft on-chain call failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "breed_nft",
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
