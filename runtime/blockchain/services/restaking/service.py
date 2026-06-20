"""
Restaking across EigenLayer, Symbiotic, Karak and liquid-restaking protocols.

This service wires the real restaking / liquid-staking protocols to the
platform. Seven operations are exposed:

- ``restake``               — EigenLayer ``StrategyManager.depositIntoStrategy``
- ``restake_symbiotic``     — Symbiotic collateral ``Vault.deposit``
- ``restake_karak``         — Karak ``Vault.deposit`` (ERC-4626 style)
- ``delegate_to_operator``  — EigenLayer ``DelegationManager.delegateTo``
- ``withdraw_restake``      — EigenLayer ``DelegationManager.queueWithdrawals``
- ``liquid_stake_lido``     — Lido ``stETH.submit`` (native ETH stake)
- ``liquid_stake_rocketpool`` — Rocket Pool ``RocketDepositPool.deposit``

ALL state-modifying methods are on-chain WRITES signed by the **platform
paymaster account** (via ``Web3Manager.send_transaction``) so the platform
pays gas and no user key is ever custodied server-side.

NON-CUSTODIAL NOTE: restaking and liquid staking move *value* (ERC-20
tokens or native ETH). Because the only key the server ever holds is the
platform paymaster key, every deposit/delegate/withdraw here operates on
the **platform account's own holdings** — this is platform-level treasury
restaking, NOT a user's funds. The service NEVER signs with, custodies, or
moves a user wallet's balance. A user-initiated restake must be a prepared,
unsigned operation returned to the user's own wallet — never executed here.

Each method gates on its required config FIRST and returns the canonical
CREDENTIAL-GATED ``not_deployed_response`` when a credential is missing or
the chain is unreachable. The real protocol call is only attempted once the
operator has populated the relevant ``services.restaking`` config keys.

Config keys (read from ``services.restaking``):
    - ``strategy_manager_address``   — EigenLayer StrategyManager
    - ``delegation_manager_address`` — EigenLayer DelegationManager
    - ``strategy_address``           — the EigenLayer Strategy (per-LST)
    - ``symbiotic_vault_address``    — Symbiotic collateral vault
    - ``karak_vault_address``        — Karak vault
    - ``lido_steth_address``         — Lido stETH contract
    - ``rocketpool_deposit_address`` — Rocket Pool RocketDepositPool

Real interfaces (addresses are operator-supplied via config; the canonical
mainnet addresses below are UNVERIFIED defaults documented for reference and
NOT hardcoded — every method gates on the configured address):
    - EigenLayer StrategyManager / DelegationManager — protocol contracts.
    - Symbiotic / Karak vaults — ERC-4626-style deposit.
    - Lido stETH ``submit(address _referral)`` payable.
    - Rocket Pool RocketDepositPool ``deposit()`` payable.
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

_PROTOCOL_EIGENLAYER = "EigenLayer"
_PROTOCOL_SYMBIOTIC = "Symbiotic"
_PROTOCOL_KARAK = "Karak"
_PROTOCOL_LIDO = "Lido (stETH)"
_PROTOCOL_ROCKETPOOL = "Rocket Pool (rETH)"

# ── Minimal ABIs — only the function each method invokes. ─────────────

# EigenLayer StrategyManager.depositIntoStrategy(strategy, token, amount)
# Verified against the EigenLayer core IStrategyManager interface.
_STRATEGY_MANAGER_ABI: list[dict] = [
    {
        "type": "function",
        "name": "depositIntoStrategy",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "strategy", "type": "address"},
            {"name": "token", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "shares", "type": "uint256"}],
    },
]

# EigenLayer Strategy.underlyingToken() — used to resolve the deposit token.
# Verified against IStrategy.
_STRATEGY_ABI: list[dict] = [
    {
        "type": "function",
        "name": "underlyingToken",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
]

# EigenLayer DelegationManager.delegateTo + queueWithdrawals.
# delegateTo(operator, approverSignatureAndExpiry, approverSalt).
# Verified against IDelegationManager (current core ABI).
_DELEGATION_MANAGER_ABI: list[dict] = [
    {
        "type": "function",
        "name": "delegateTo",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "operator", "type": "address"},
            {
                "name": "approverSignatureAndExpiry",
                "type": "tuple",
                "components": [
                    {"name": "signature", "type": "bytes"},
                    {"name": "expiry", "type": "uint256"},
                ],
            },
            {"name": "approverSalt", "type": "bytes32"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "queueWithdrawals",
        "stateMutability": "nonpayable",
        "inputs": [
            {
                "name": "queuedWithdrawalParams",
                "type": "tuple[]",
                "components": [
                    {"name": "strategies", "type": "address[]"},
                    {"name": "depositShares", "type": "uint256[]"},
                    {"name": "__deprecated_withdrawer", "type": "address"},
                ],
            }
        ],
        "outputs": [{"name": "", "type": "bytes32[]"}],
    },
]

# ERC-4626-style vault deposit(uint256 assets, address receiver) — shared by
# Symbiotic and Karak collateral vaults. UNVERIFIED for each specific vault:
# some Symbiotic/Karak vault versions use deposit(onBehalfOf, amount); the
# operator must confirm the deployed vault's signature. Gated on config.
_VAULT_DEPOSIT_ABI: list[dict] = [
    {
        "type": "function",
        "name": "deposit",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "assets", "type": "uint256"},
            {"name": "receiver", "type": "address"},
        ],
        "outputs": [{"name": "shares", "type": "uint256"}],
    },
]

# Lido stETH.submit(address _referral) payable — stakes native ETH, mints stETH.
# Verified against the Lido stETH (Lido) contract ABI.
_LIDO_ABI: list[dict] = [
    {
        "type": "function",
        "name": "submit",
        "stateMutability": "payable",
        "inputs": [{"name": "_referral", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]

# Rocket Pool RocketDepositPool.deposit() payable — mints rETH to sender.
# Verified against the Rocket Pool RocketDepositPool interface.
_ROCKETPOOL_ABI: list[dict] = [
    {
        "type": "function",
        "name": "deposit",
        "stateMutability": "payable",
        "inputs": [],
        "outputs": [],
    },
]

_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
_ZERO_BYTES32 = "0x" + "00" * 32


class RestakingService:
    """Restaking across EigenLayer, Symbiotic, Karak and liquid-restaking protocols."""

    service_name = "restaking"

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
        """Return this service's own config sub-dict (``services.restaking``)."""
        return self._config.get("services", {}).get(self.service_name, {}) or {}

    def _gate(self, method: str, missing: str, protocol: str) -> dict:
        """Build the canonical CREDENTIAL-GATED response naming the exact miss."""
        return not_deployed_response(self.service_name, extra={
            "method": method,
            "missing": missing,
            "protocol": protocol,
        })

    @staticmethod
    def _error(method: str, exc: Exception) -> dict:
        """Honest error envelope — never fabricates a tx hash."""
        return {
            "status": "error",
            "service": RestakingService.service_name,
            "method": method,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }

    def _to_wei(self, amount: Any) -> int:
        """Convert a human ``amount`` (ether/token units, 18 decimals) to wei.

        Restaking deposits are denominated in the LST's base unit; we assume
        18 decimals (the common case for stETH/rETH/most LSTs). For non-18
        decimal collateral the caller may pass ``amount_wei`` directly.
        """
        w3 = self._web3.w3
        return int(w3.to_wei(amount, "ether"))

    def _amount_in_wei(self, params: dict) -> int:
        """Resolve the deposit amount in wei from call params."""
        if params.get("amount_wei") is not None:
            return int(params["amount_wei"])
        return self._to_wei(params.get("amount", 0))

    # ── EigenLayer: StrategyManager.depositIntoStrategy ──────────────

    async def restake(self, **params: Any) -> dict:
        """Restake into an EigenLayer strategy.

        Params: ``amount`` (token units, 18-dec) or ``amount_wei``,
        optional ``token`` (deposit token; resolved from the strategy's
        ``underlyingToken()`` when omitted).

        On-chain WRITE: ``StrategyManager.depositIntoStrategy(strategy,
        token, amount)`` signed by the platform paymaster (platform-level
        restaking of the platform account's own token balance).
        """
        cfg = self._cfg()
        manager_addr = cfg.get("strategy_manager_address", "")
        strategy_addr = cfg.get("strategy_address", "")

        # ── CREDENTIAL-GATED gate FIRST ──────────────────────────────
        if not self._web3.available:
            return self._gate("restake", "blockchain.rpc_url", _PROTOCOL_EIGENLAYER)
        if is_placeholder_value(manager_addr):
            return self._gate(
                "restake",
                "services.restaking.strategy_manager_address",
                _PROTOCOL_EIGENLAYER,
            )
        if is_placeholder_value(strategy_addr):
            return self._gate(
                "restake",
                "services.restaking.strategy_address",
                _PROTOCOL_EIGENLAYER,
            )

        # ── REAL path: depositIntoStrategy via platform paymaster ────
        try:
            w3 = self._web3.w3
            strategy_cs = w3.to_checksum_address(strategy_addr)

            token = params.get("token")
            if is_placeholder_value(token):
                # Resolve the deposit token from the strategy itself.
                strategy = self._web3.load_contract(strategy_cs, _STRATEGY_ABI)
                token = strategy.functions.underlyingToken().call()
            token_cs = w3.to_checksum_address(token)

            amount_wei = self._amount_in_wei(params)
            manager = self._web3.load_contract(manager_addr, _STRATEGY_MANAGER_ABI)

            tx = manager.functions.depositIntoStrategy(
                strategy_cs, token_cs, amount_wei
            ).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
            })
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "restake",
                "protocol": _PROTOCOL_EIGENLAYER,
                "strategy_manager": w3.to_checksum_address(manager_addr),
                "strategy": strategy_cs,
                "token": token_cs,
                "amount_wei": str(amount_wei),
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
                "acts_on": "platform_account",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("restake on-chain call failed: %s", exc)
            return self._error("restake", exc)

    # ── Symbiotic: collateral Vault.deposit ──────────────────────────

    async def restake_symbiotic(self, **params: Any) -> dict:
        """Restake into a Symbiotic collateral vault.

        Params: ``amount`` (18-dec) or ``amount_wei``, optional
        ``receiver`` (defaults to the platform account).

        On-chain WRITE: ``Vault.deposit(assets, receiver)`` signed by the
        platform paymaster. NOTE: the deposit signature is UNVERIFIED for
        the specific Symbiotic vault version — operator must confirm.
        """
        cfg = self._cfg()
        vault_addr = cfg.get("symbiotic_vault_address", "")

        if not self._web3.available:
            return self._gate("restake_symbiotic", "blockchain.rpc_url", _PROTOCOL_SYMBIOTIC)
        if is_placeholder_value(vault_addr):
            return self._gate(
                "restake_symbiotic",
                "services.restaking.symbiotic_vault_address",
                _PROTOCOL_SYMBIOTIC,
            )

        try:
            w3 = self._web3.w3
            vault_cs = w3.to_checksum_address(vault_addr)
            receiver = params.get("receiver") or self._web3.get_account().address
            receiver_cs = w3.to_checksum_address(receiver)
            amount_wei = self._amount_in_wei(params)

            vault = self._web3.load_contract(vault_cs, _VAULT_DEPOSIT_ABI)
            tx = vault.functions.deposit(amount_wei, receiver_cs).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
            })
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "restake_symbiotic",
                "protocol": _PROTOCOL_SYMBIOTIC,
                "vault": vault_cs,
                "receiver": receiver_cs,
                "amount_wei": str(amount_wei),
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
                "acts_on": "platform_account",
                "abi_note": "Vault.deposit(assets,receiver) assumed — verify vault version",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("restake_symbiotic on-chain call failed: %s", exc)
            return self._error("restake_symbiotic", exc)

    # ── Karak: Vault.deposit (ERC-4626 style) ────────────────────────

    async def restake_karak(self, **params: Any) -> dict:
        """Restake into a Karak vault.

        Params: ``amount`` (18-dec) or ``amount_wei``, optional
        ``receiver`` (defaults to the platform account).

        On-chain WRITE: ``Vault.deposit(assets, receiver)`` signed by the
        platform paymaster. ABI is ERC-4626-style and UNVERIFIED for the
        specific Karak vault deployment — operator must confirm.
        """
        cfg = self._cfg()
        vault_addr = cfg.get("karak_vault_address", "")

        if not self._web3.available:
            return self._gate("restake_karak", "blockchain.rpc_url", _PROTOCOL_KARAK)
        if is_placeholder_value(vault_addr):
            return self._gate(
                "restake_karak",
                "services.restaking.karak_vault_address",
                _PROTOCOL_KARAK,
            )

        try:
            w3 = self._web3.w3
            vault_cs = w3.to_checksum_address(vault_addr)
            receiver = params.get("receiver") or self._web3.get_account().address
            receiver_cs = w3.to_checksum_address(receiver)
            amount_wei = self._amount_in_wei(params)

            vault = self._web3.load_contract(vault_cs, _VAULT_DEPOSIT_ABI)
            tx = vault.functions.deposit(amount_wei, receiver_cs).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
            })
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "restake_karak",
                "protocol": _PROTOCOL_KARAK,
                "vault": vault_cs,
                "receiver": receiver_cs,
                "amount_wei": str(amount_wei),
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
                "acts_on": "platform_account",
                "abi_note": "Vault.deposit(assets,receiver) assumed — verify vault version",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("restake_karak on-chain call failed: %s", exc)
            return self._error("restake_karak", exc)

    # ── EigenLayer: DelegationManager.delegateTo ─────────────────────

    async def delegate_to_operator(self, **params: Any) -> dict:
        """Delegate the platform account's restaked shares to an operator.

        Params: ``operator`` (operator address — REQUIRED).

        On-chain WRITE: ``DelegationManager.delegateTo(operator,
        approverSignatureAndExpiry, approverSalt)`` signed by the platform
        paymaster. An empty approver signature (expiry 0, zero salt) is used
        — valid when the operator has no delegation approver set.
        """
        cfg = self._cfg()
        delegation_addr = cfg.get("delegation_manager_address", "")
        operator = params.get("operator")

        if not self._web3.available:
            return self._gate("delegate_to_operator", "blockchain.rpc_url", _PROTOCOL_EIGENLAYER)
        if is_placeholder_value(delegation_addr):
            return self._gate(
                "delegate_to_operator",
                "services.restaking.delegation_manager_address",
                _PROTOCOL_EIGENLAYER,
            )
        if is_placeholder_value(operator):
            return self._gate(
                "delegate_to_operator",
                "operator (call param)",
                _PROTOCOL_EIGENLAYER,
            )

        try:
            w3 = self._web3.w3
            operator_cs = w3.to_checksum_address(operator)
            delegation = self._web3.load_contract(delegation_addr, _DELEGATION_MANAGER_ABI)

            # Empty approver signature: (signature=b"", expiry=0), zero salt.
            empty_sig = (b"", 0)
            salt = bytes.fromhex(_ZERO_BYTES32[2:])

            tx = delegation.functions.delegateTo(
                operator_cs, empty_sig, salt
            ).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
            })
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "delegate_to_operator",
                "protocol": _PROTOCOL_EIGENLAYER,
                "delegation_manager": w3.to_checksum_address(delegation_addr),
                "operator": operator_cs,
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
                "acts_on": "platform_account",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("delegate_to_operator on-chain call failed: %s", exc)
            return self._error("delegate_to_operator", exc)

    # ── EigenLayer: DelegationManager.queueWithdrawals ───────────────

    async def withdraw_restake(self, **params: Any) -> dict:
        """Queue a withdrawal of restaked shares from EigenLayer.

        Params: ``shares`` (deposit-share amount, 18-dec) or ``shares_wei``,
        optional ``strategy`` (defaults to configured ``strategy_address``).

        On-chain WRITE: ``DelegationManager.queueWithdrawals([...])`` signed
        by the platform paymaster. The withdrawer defaults to the platform
        account (staker). Note the EigenLayer escrow delay applies before the
        withdrawal can be completed in a later step.
        """
        cfg = self._cfg()
        delegation_addr = cfg.get("delegation_manager_address", "")
        strategy_addr = params.get("strategy") or cfg.get("strategy_address", "")

        if not self._web3.available:
            return self._gate("withdraw_restake", "blockchain.rpc_url", _PROTOCOL_EIGENLAYER)
        if is_placeholder_value(delegation_addr):
            return self._gate(
                "withdraw_restake",
                "services.restaking.delegation_manager_address",
                _PROTOCOL_EIGENLAYER,
            )
        if is_placeholder_value(strategy_addr):
            return self._gate(
                "withdraw_restake",
                "services.restaking.strategy_address",
                _PROTOCOL_EIGENLAYER,
            )

        try:
            w3 = self._web3.w3
            strategy_cs = w3.to_checksum_address(strategy_addr)
            staker = self._web3.get_account().address

            if params.get("shares_wei") is not None:
                shares_wei = int(params["shares_wei"])
            else:
                shares_wei = self._to_wei(params.get("shares", 0))

            delegation = self._web3.load_contract(delegation_addr, _DELEGATION_MANAGER_ABI)
            # QueuedWithdrawalParams: (strategies[], depositShares[], withdrawer)
            withdrawal_param = ([strategy_cs], [shares_wei], staker)

            tx = delegation.functions.queueWithdrawals(
                [withdrawal_param]
            ).build_transaction({
                "from": staker,
                "chainId": self._web3.chain_id,
            })
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "withdraw_restake",
                "protocol": _PROTOCOL_EIGENLAYER,
                "delegation_manager": w3.to_checksum_address(delegation_addr),
                "strategy": strategy_cs,
                "shares_wei": str(shares_wei),
                "withdrawer": staker,
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
                "acts_on": "platform_account",
                "note": "queued — EigenLayer escrow delay applies before completion",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("withdraw_restake on-chain call failed: %s", exc)
            return self._error("withdraw_restake", exc)

    # ── Lido: stETH.submit (native ETH liquid stake) ─────────────────

    async def liquid_stake_lido(self, **params: Any) -> dict:
        """Liquid-stake native ETH via Lido (mints stETH).

        Params: ``amount`` (ETH) or ``amount_wei``, optional ``referral``.

        On-chain WRITE (payable): ``stETH.submit(_referral)`` with the ETH
        value attached, signed by the platform paymaster. Stakes the platform
        account's own ETH — never a user's.
        """
        cfg = self._cfg()
        steth_addr = cfg.get("lido_steth_address", "")

        if not self._web3.available:
            return self._gate("liquid_stake_lido", "blockchain.rpc_url", _PROTOCOL_LIDO)
        if is_placeholder_value(steth_addr):
            return self._gate(
                "liquid_stake_lido",
                "services.restaking.lido_steth_address",
                _PROTOCOL_LIDO,
            )

        try:
            w3 = self._web3.w3
            steth_cs = w3.to_checksum_address(steth_addr)
            referral = params.get("referral")
            referral_cs = (
                w3.to_checksum_address(referral)
                if not is_placeholder_value(referral)
                else _ZERO_ADDRESS
            )
            amount_wei = self._amount_in_wei(params)

            steth = self._web3.load_contract(steth_cs, _LIDO_ABI)
            tx = steth.functions.submit(referral_cs).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
                "value": amount_wei,
            })
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "liquid_stake_lido",
                "protocol": _PROTOCOL_LIDO,
                "steth": steth_cs,
                "referral": referral_cs,
                "amount_wei": str(amount_wei),
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
                "acts_on": "platform_account",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("liquid_stake_lido on-chain call failed: %s", exc)
            return self._error("liquid_stake_lido", exc)

    # ── Rocket Pool: RocketDepositPool.deposit (mints rETH) ──────────

    async def liquid_stake_rocketpool(self, **params: Any) -> dict:
        """Liquid-stake native ETH via Rocket Pool (mints rETH).

        Params: ``amount`` (ETH) or ``amount_wei``.

        On-chain WRITE (payable): ``RocketDepositPool.deposit()`` with the
        ETH value attached, signed by the platform paymaster. Stakes the
        platform account's own ETH — never a user's.
        """
        cfg = self._cfg()
        deposit_addr = cfg.get("rocketpool_deposit_address", "")

        if not self._web3.available:
            return self._gate(
                "liquid_stake_rocketpool", "blockchain.rpc_url", _PROTOCOL_ROCKETPOOL
            )
        if is_placeholder_value(deposit_addr):
            return self._gate(
                "liquid_stake_rocketpool",
                "services.restaking.rocketpool_deposit_address",
                _PROTOCOL_ROCKETPOOL,
            )

        try:
            w3 = self._web3.w3
            deposit_cs = w3.to_checksum_address(deposit_addr)
            amount_wei = self._amount_in_wei(params)

            pool = self._web3.load_contract(deposit_cs, _ROCKETPOOL_ABI)
            tx = pool.functions.deposit().build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
                "value": amount_wei,
            })
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "liquid_stake_rocketpool",
                "protocol": _PROTOCOL_ROCKETPOOL,
                "deposit_pool": deposit_cs,
                "amount_wei": str(amount_wei),
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
                "acts_on": "platform_account",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("liquid_stake_rocketpool on-chain call failed: %s", exc)
            return self._error("liquid_stake_rocketpool", exc)
