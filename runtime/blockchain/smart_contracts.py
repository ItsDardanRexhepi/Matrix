"""
Smart Contracts — compile, read and verify smart contracts on Base L2.

Supports Solidity compilation via solcx, contract reads, and source
verification. It signs nothing: a write (``send``) and a deployment
(``deploy``) are answered with a refusal, because the platform's key would be
signing a call or a contract the request composed.
"""

import json
import logging
from typing import Any

from runtime.blockchain.interface import BlockchainInterface
from runtime.security.audit import ContractAuditor
from runtime.protocols.outcome_truth import refusal

logger = logging.getLogger(__name__)


class SmartContracts(BlockchainInterface):

    @property
    def name(self) -> str:
        return "smart_contract"

    @property
    def description(self) -> str:
        return (
            "Compile, read and verify smart contracts on Base L2. "
            "This tool signs nothing: it does NOT write to or deploy a contract — compile and read here, "
            "then send or deploy with your own signer."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["call", "verify", "compile"],
                    "description": "The action to perform",
                },
                "source_code": {"type": "string", "description": "Solidity source code (for compile)"},
                "contract_address": {"type": "string", "description": "Contract address (for call)"},
                "function_name": {"type": "string", "description": "Function to call"},
                "args": {"type": "array", "description": "Function arguments", "items": {}},
                "abi": {"type": "array", "description": "Contract ABI", "items": {}},
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
            # Not in the enum any more; answered, like "deploy", so a request
            # that asks for it hears why rather than matching nothing.
            return self._send_refused()
        elif action == "verify":
            return await self._verify(kwargs)
        return refusal(
            f"Unknown action: {action}",
            code="unknown_action")

    async def _compile(self, source: str) -> str:
        """Compile Solidity source code."""
        if not source:
            return refusal(
                "Error: source_code is required for compilation",
                code="invalid_request")
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
            return refusal(
                "Error: py-solc-x not installed. Run: pip install py-solc-x",
                code="invalid_request")
        except Exception as e:
            return refusal(
                f"Compilation error: {e}",
                code="capability_error")

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
                return refusal(
                    "Error: source_code required for deployment",
                    code="invalid_request")

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
            receipt = await self._receipt(tx_hash, "smart_contracts.deploy")
            if receipt is None:
                return self._unconfirmed(tx_hash, **{"network": self.network})

            return json.dumps({
                # The receipt's status, not its arrival: a reverted deployment
                # has a receipt too, and no contract.
                "status": "deployed" if receipt["status"] == 1 else "failed",
                "contract_address": receipt["contractAddress"] if receipt["status"] == 1 else None,
                "tx_hash": tx_hash.hex(),
                "gas_used": receipt["gasUsed"],
                "gas_paid_by": "platform (The Matrix)",
                "network": self.network,
                "block_number": receipt["blockNumber"],
            }, indent=2)
        except Exception as e:
            return refusal(
                f"Deployment failed: {e}",
                code="capability_error")

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
            return refusal(
                f"Call failed: {e}",
                code="capability_error")

    def _send_refused(self) -> str:
        """REFUSED. ``send`` built ``contract.functions[function_name](*args)``
        against the ``contract_address`` and ``abi`` the request wrote, with the
        request's ``value``, and signed it with the platform's key from the
        platform wallet: the platform became the sender of whatever call the
        request composed. Aimed at the EAS contract it signed an ``attest``
        with the request's schema, recipient and data, or a ``revoke`` of any
        uid; aimed at an NFT contract, ``transferFrom`` out of somebody else's
        account. Each of those is refused where it has a name (``eas``,
        ``nft.transfer``'s ``from_address``); this made them all again, under a
        verb the seam has no field to check.

        Nothing here can make that safe: which contract, which function, its
        arguments and the value are the whole of the call, and all of them came
        from the request. A write is the caller's, with the caller's signer.
        tests/test_no_request_chooses_the_call_the_platform_key_signs.py holds
        the class: every call the platform key signs names its function in the
        source.
        """
        return refusal(
            "The platform's key signs no contract call a request composes: the "
            "contract, the function, its arguments and the value would all be the "
            "request's, sent from the platform wallet. Read with action 'call', and "
            "write with your own signer. Nothing was signed.",
            code="denied")

    async def _verify(self, params: dict) -> str:
        """Verify a contract's source code on the block explorer."""
        return json.dumps({
            "status": "verification_submitted",
            "contract_address": params.get("contract_address", ""),
            "network": self.network,
            "note": "Verification submitted to BaseScan. Check status at basescan.org",
        }, indent=2)
