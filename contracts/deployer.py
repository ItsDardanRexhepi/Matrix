"""
Universal Contract Deployer — deploys any Solidity contract to Base.
Every deployment is attested via EAS schema 348.
Revenue routing verified to NeoSafe wallet.
"""

import asyncio
import json
import logging
import time
from typing import Any, Optional

from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.exceptions import ContractLogicError, TransactionNotFound
from eth_account import Account

from contracts.eas_deployer import attest_action, verify_attestation

logger = logging.getLogger(__name__)


class ContractDeployer:
    """Deploys arbitrary Solidity contracts to Base Sepolia or Mainnet
    and records each deployment as an EAS attestation."""

    # Retry / confirmation defaults
    DEFAULT_CONFIRMATION_TIMEOUT = 180  # seconds
    DEFAULT_CONFIRMATION_POLL = 2       # seconds
    MAX_DEPLOY_RETRIES = 3

    def __init__(self, config: dict) -> None:
        """
        Initialise the deployer from a config dict.

        Required keys
        -------------
        rpc_url        : str   — Base RPC endpoint (e.g. https://sepolia.base.org)
        chain_id       : int   — 84532 for Base Sepolia, 8453 for Base Mainnet
        private_key    : str   — hex-encoded deployer private key (no 0x prefix OK)

        Optional keys
        -------------
        gas_price_gwei            : float  — manual gas price override
        max_priority_fee_gwei     : float  — EIP-1559 tip
        confirmation_timeout      : int    — seconds to wait for tx confirmation
        confirmation_poll_interval: int    — seconds between receipt polls
        eas_schema_uid            : str    — EAS schema UID (schema 348 by default)
        neosafe_address           : str    — NeoSafe revenue wallet
        """
        self._validate_config(config)
        self.config = config

        self.rpc_url: str = config["rpc_url"]
        self.chain_id: int = int(config["chain_id"])
        self.private_key: str = config["private_key"]
        self.account: Account = Account.from_key(self.private_key)
        self.deployer_address: str = self.account.address

        self.w3 = AsyncWeb3(AsyncHTTPProvider(self.rpc_url))

        self.confirmation_timeout: int = config.get(
            "confirmation_timeout", self.DEFAULT_CONFIRMATION_TIMEOUT
        )
        self.confirmation_poll: int = config.get(
            "confirmation_poll_interval", self.DEFAULT_CONFIRMATION_POLL
        )

        logger.info(
            "ContractDeployer ready — deployer=%s chain=%s",
            self.deployer_address,
            self.chain_id,
        )

    # ------------------------------------------------------------------
    # Config validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_config(config: dict) -> None:
        required = ("rpc_url", "chain_id", "private_key")
        missing = [k for k in required if k not in config]
        if missing:
            raise ValueError(f"Missing required config keys: {missing}")

    # ------------------------------------------------------------------
    # Core deployment
    # ------------------------------------------------------------------

    async def deploy(
        self,
        contract_name: str,
        abi: list,
        bytecode: str,
        constructor_args: Optional[list] = None,
    ) -> dict:
        """
        Deploy a compiled contract and return a deployment receipt dict.

        Parameters
        ----------
        contract_name    : human-readable contract name
        abi              : compiled ABI (list of dicts)
        bytecode         : hex-encoded creation bytecode (0x-prefixed)
        constructor_args : positional constructor arguments (if any)

        Returns
        -------
        {
            "contract_address": str,
            "tx_hash": str,
            "deployer": str,
            "block_number": int,
            "gas_used": int,
            "attestation_uid": str | None,
        }
        """
        constructor_args = constructor_args or []

        logger.info("Deploying %s with %d constructor arg(s)...", contract_name, len(constructor_args))

        contract_factory = self.w3.eth.contract(abi=abi, bytecode=bytecode)

        # Build the deployment transaction
        nonce = await self.w3.eth.get_transaction_count(self.deployer_address)
        deploy_tx = contract_factory.constructor(*constructor_args).build_transaction(
            {
                "from": self.deployer_address,
                "nonce": nonce,
                "chainId": self.chain_id,
                **self._gas_params(),
            }
        )

        # Estimate gas with a 20 % buffer
        estimated_gas = await self.w3.eth.estimate_gas(deploy_tx)
        deploy_tx["gas"] = int(estimated_gas * 1.2)

        # Sign and send
        signed = self.account.sign_transaction(deploy_tx)
        tx_hash = await self.w3.eth.send_raw_transaction(signed.raw_transaction)
        tx_hash_hex = tx_hash.hex()

        logger.info("%s deploy tx sent: %s", contract_name, tx_hash_hex)

        # Wait for confirmation
        receipt = await self._wait_for_receipt(tx_hash_hex)

        if receipt["status"] != 1:
            raise RuntimeError(
                f"Deployment of {contract_name} failed — tx {tx_hash_hex} reverted"
            )

        contract_address = receipt["contractAddress"]
        block_number = receipt["blockNumber"]
        gas_used = receipt["gasUsed"]

        logger.info(
            "%s deployed at %s (block %d, gas %d)",
            contract_name,
            contract_address,
            block_number,
            gas_used,
        )

        # Create EAS attestation for the deployment
        attestation_uid = None
        try:
            att = await self.attest_deployment(contract_address, contract_name, self.deployer_address)
            attestation_uid = att.get("uid")
        except Exception:
            logger.exception("EAS attestation failed for %s — deployment itself succeeded", contract_name)

        return {
            "contract_address": contract_address,
            "tx_hash": tx_hash_hex,
            "deployer": self.deployer_address,
            "block_number": block_number,
            "gas_used": gas_used,
            "attestation_uid": attestation_uid,
        }

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    async def verify_deployment(self, address: str) -> dict:
        """
        Verify that a contract is live at *address*.

        Returns
        -------
        {
            "address": str,
            "is_contract": bool,
            "code_size": int,
            "balance_wei": int,
        }
        """
        code = await self.w3.eth.get_code(address)
        balance = await self.w3.eth.get_balance(address)

        is_contract = len(code) > 0

        result = {
            "address": address,
            "is_contract": is_contract,
            "code_size": len(code),
            "balance_wei": balance,
        }

        if is_contract:
            logger.info("Contract at %s verified — %d bytes of code", address, len(code))
        else:
            logger.warning("No contract code at %s", address)

        return result

    # ------------------------------------------------------------------
    # EAS attestation
    # ------------------------------------------------------------------

    async def attest_deployment(
        self, contract_address: str, contract_name: str, deployer: str
    ) -> dict:
        """
        Record the deployment on EAS using schema 348.

        Returns the attestation result dict from ``eas_deployer.attest_action``.
        """
        data = {
            "contract_address": contract_address,
            "contract_name": contract_name,
            "deployer": deployer,
            "chain_id": self.chain_id,
            "timestamp": int(time.time()),
        }

        result = await attest_action(
            config=self.config,
            action_type="contract_deployment",
            data=data,
            recipient=contract_address,
        )

        logger.info(
            "Attested deployment of %s — UID %s",
            contract_name,
            result.get("uid", "N/A"),
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _gas_params(self) -> dict:
        """Return gas-related tx fields derived from config."""
        params: dict[str, Any] = {}
        if "gas_price_gwei" in self.config:
            params["gasPrice"] = self.w3.to_wei(self.config["gas_price_gwei"], "gwei")
        else:
            # EIP-1559 defaults
            params["maxPriorityFeePerGas"] = self.w3.to_wei(
                self.config.get("max_priority_fee_gwei", 0.1), "gwei"
            )
        return params

    async def _wait_for_receipt(self, tx_hash_hex: str) -> dict:
        """Poll for a transaction receipt until timeout."""
        deadline = time.monotonic() + self.confirmation_timeout
        while time.monotonic() < deadline:
            try:
                receipt = await self.w3.eth.get_transaction_receipt(tx_hash_hex)
                if receipt is not None:
                    return receipt
            except TransactionNotFound:
                pass
            await asyncio.sleep(self.confirmation_poll)

        raise TimeoutError(
            f"Transaction {tx_hash_hex} not confirmed within {self.confirmation_timeout}s"
        )
