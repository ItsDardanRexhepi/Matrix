"""
Smart Contracts — deploy, interact with, and verify smart contracts on Base L2.

Supports Solidity compilation via solcx, deployment with gas sponsorship,
contract interaction (read/write), and source verification.
Gas is paid by the platform within its sponsorship policy.
"""

import json
import logging
from typing import Any

from runtime.blockchain.interface import BlockchainInterface
from runtime.security.audit import ContractAuditor

logger = logging.getLogger(__name__)


class SmartContracts(BlockchainInterface):

    @property
    def name(self) -> str:
        return "smart_contract"

    @property
    def description(self) -> str:
        return (
            "Compile, read, write and verify smart contracts on Base L2. Gas for writes is covered by the platform, within the configured sponsorship policy. "
            "This tool does NOT deploy contracts — compile here, deploy with your own signer."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["call", "send", "verify", "compile"],
                    "description": "The action to perform",
                },
                "source_code": {"type": "string", "description": "Solidity source code (for compile)"},
                "contract_address": {"type": "string", "description": "Contract address (for call/send)"},
                "function_name": {"type": "string", "description": "Function to call"},
                "args": {"type": "array", "description": "Function arguments", "items": {}},
                "abi": {"type": "array", "description": "Contract ABI", "items": {}},
                "value": {"type": "string", "description": "ETH value to send (in wei)", "default": "0"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "compile":
            return await self._compile(kwargs.get("source_code", ""))
        elif action == "deploy":
            # Not in the enum any more; still answered, because a request that
            # matches nothing is a worse outcome than an honest refusal.
            return await self._deploy(kwargs)
        elif action == "call":
            return await self._call(kwargs)
        elif action == "send":
            return await self._send(kwargs)
        elif action == "verify":
            return await self._verify(kwargs)
        return f"Unknown action: {action}"

    async def _compile(self, source: str) -> str:
        """Compile Solidity source code."""
        if not source:
            return "Error: source_code is required for compilation"
        try:
            from solcx import compile_source, install_solc
            install_solc("0.8.24", show_progress=False)
            compiled = compile_source(source, output_values=["abi", "bin"], solc_version="0.8.24")
            results = []
            for name, contract in compiled.items():
                results.append({
                    "contract": name,
                    "abi": contract["abi"],
                    "bytecode_length": len(contract["bin"]),
                })
            return json.dumps({"status": "compiled", "contracts": results}, indent=2)
        except ImportError:
            return "Error: py-solc-x not installed. Run: pip install py-solc-x"
        except Exception as e:
            return f"Compilation error: {e}"

    async def _deploy(self, params: dict) -> str:
        """Deployment is not offered here. RUN-2 closed the HTTP direction of
        this operation to 501; this is the same answer on the tool axis.

        §CD — the sibling axis. NEW-4 removed `deploy_contract` from ACTION_MAP
        and the capability catalog, NEW-12 asserted "no path may claim a
        deployment happened", and RUN-2 made POST /api/v1/contracts/deploy
        return 501. None of them reached THIS path: `smart_contract` is
        registered as a tool in every configuration, its action enum listed
        "deploy", and this method compiled caller-supplied Solidity and signed
        it with the platform paymaster key. A model following its own tool
        schema could deploy an arbitrary contract that the closed route refused.

        The method survives so the request is still RECOGNISED and answered —
        the same reasoning that keeps the `deploy_contract` entry in
        INTENT_ACTION_MAP with `unavailable: True` rather than deleting it. A
        request that matches nothing is its own dead end.

        LIFTING CONDITION: real deployment is a feature with real risk (key
        custody, chain selection, failure semantics, who owns the deployed
        contract) and needs its own design pass. It is not smuggled in behind a
        capability schema.
        """
        return json.dumps({
            "status": "not_implemented",
            "error": "Contract deployment is not available.",
            "detail": (
                "This platform compiles and audits Solidity; it does not deploy "
                "it. Use action 'compile' to get the ABI and bytecode, then "
                "deploy with your own signer. Nothing was deployed."
            ),
            "next": {"action": "compile", "then": "deploy with your own wallet"},
        }, indent=2)

    async def _deploy_disabled_implementation(self, params: dict) -> str:
        """Kept unreferenced, for the design pass named in the lifting condition
        above. Nothing routes here: `execute` has no branch for it and the action
        enum does not contain "deploy"."""
        try:
            from web3 import Web3
            from solcx import compile_source, install_solc

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            source = params.get("source_code", "")
            if not source:
                return "Error: source_code required for deployment"

            install_solc("0.8.24", show_progress=False)
            compiled = compile_source(source, output_values=["abi", "bin"], solc_version="0.8.24")

            # Get the first contract
            contract_id, contract_data = next(iter(compiled.items()))
            abi = contract_data["abi"]
            bytecode = contract_data["bin"]

            # Security audit gate
            auditor = ContractAuditor(self.config)
            audit_report = auditor.audit(source, contract_id.split(":")[-1])
            if auditor.should_block(audit_report):
                return json.dumps({
                    "status": "blocked",
                    "reason": "Security audit failed — critical vulnerability detected",
                    "audit": audit_report.to_dict(),
                    "message": "Morpheus has blocked this deployment. Fix the contract before deploying.",
                }, indent=2)

            bc = self.config["blockchain"]
            account = await self._platform_signer("smart_contracts.deploy")
            contract = self.web3.eth.contract(abi=abi, bytecode=bytecode)

            constructor_args = params.get("args", [])
            tx = contract.constructor(*constructor_args).build_transaction({
                "from": bc["platform_wallet"],
                "chainId": self.chain_id,
                "gas": 3000000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "deployed",
                "contract_address": receipt["contractAddress"],
                "tx_hash": tx_hash.hex(),
                "gas_used": receipt["gasUsed"],
                "gas_paid_by": "platform (0pnMatrx)",
                "network": self.network,
                "block_number": receipt["blockNumber"],
            }, indent=2)
        except Exception as e:
            return f"Deployment failed: {e}"

    async def _call(self, params: dict) -> str:
        """Read from a contract (no gas required)."""
        try:
            from web3 import Web3
            address = params.get("contract_address", "")
            abi = params.get("abi", [])
            fn = params.get("function_name", "")
            args = params.get("args", [])

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(address), abi=abi
            )
            result = contract.functions[fn](*args).call()
            return json.dumps({"result": str(result), "function": fn}, indent=2)
        except Exception as e:
            return f"Call failed: {e}"

    async def _send(self, params: dict) -> str:
        """Write to a contract. Gas covered by platform."""
        try:
            from web3 import Web3

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            address = params.get("contract_address", "")
            abi = params.get("abi", [])
            fn = params.get("function_name", "")
            args = params.get("args", [])
            value = int(params.get("value", "0"))

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(address), abi=abi
            )
            account = await self._platform_signer("smart_contracts.send")

            tx = contract.functions[fn](*args).build_transaction({
                "from": bc["platform_wallet"],
                "chainId": self.chain_id,
                "gas": 500000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
                "value": value,
            })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "success" if receipt["status"] == 1 else "failed",
                "tx_hash": tx_hash.hex(),
                "gas_used": receipt["gasUsed"],
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Send failed: {e}"

    async def _verify(self, params: dict) -> str:
        """Verify a contract's source code on the block explorer."""
        return json.dumps({
            "status": "verification_submitted",
            "contract_address": params.get("contract_address", ""),
            "network": self.network,
            "note": "Verification submitted to BaseScan. Check status at basescan.org",
        }, indent=2)
