"""
EAS Manager — high-level attestation management for 0pnMatrx.

Wraps the EAS client to provide schema creation, attestation querying,
batch attestations, and revocation. Gas covered by the platform.
"""

import json
import logging

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)


class EASManager(BlockchainInterface):

    @property
    def name(self) -> str:
        return "eas"

    @property
    def description(self) -> str:
        return "Manage EAS attestations: create schemas, attest actions, query attestations, revoke. Gas covered by platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create_schema", "attest", "query", "revoke", "batch_attest"]},
                "schema": {"type": "string", "description": "Schema definition string"},
                "schema_uid": {"type": "string"},
                "recipient": {"type": "string"},
                "data": {"type": "object", "description": "Attestation data"},
                "attestation_uid": {"type": "string"},
                "attestations": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "create_schema":
            return await self._create_schema(kwargs)
        elif action == "attest":
            return await self._attest(kwargs)
        elif action == "query":
            return await self._query(kwargs)
        elif action == "revoke":
            return await self._revoke(kwargs)
        elif action == "batch_attest":
            return await self._batch_attest(kwargs)
        return f"Unknown EAS action: {action}"

    async def _create_schema(self, params: dict) -> str:
        """Create a new EAS schema on-chain via the SchemaRegistry. Gas covered by platform."""
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            schema_registry_addr = bc.get("eas_schema_registry", "")
            if not schema_registry_addr or str(schema_registry_addr).startswith("YOUR_"):
                return json.dumps({
                    "status": "error",
                    "error": "blockchain.eas_schema_registry address is not configured.",
                    "hint": "Set eas_schema_registry in openmatrix.config.json (e.g., 0x4200000000000000000000000000000000000020 on Base).",
                    "network": self.network,
                }, indent=2)

            schema_def = params.get("schema", "string action, string agent, uint256 timestamp")

            schema_registry_abi = [{
                "inputs": [
                    {"name": "schema", "type": "string"},
                    {"name": "resolver", "type": "address"},
                    {"name": "revocable", "type": "bool"},
                ],
                "name": "register",
                "outputs": [{"name": "", "type": "bytes32"}],
                "stateMutability": "nonpayable",
                "type": "function",
            }]

            registry = self.web3.eth.contract(
                address=Web3.to_checksum_address(schema_registry_addr),
                abi=schema_registry_abi,
            )
            account = Account.from_key(bc["paymaster_private_key"])

            tx = registry.functions.register(
                schema_def,
                "0x0000000000000000000000000000000000000000",  # no resolver
                True,  # revocable
            ).build_transaction({
                "from": bc["platform_wallet"],
                "chainId": self.chain_id,
                "gas": 300000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "registered" if receipt["status"] == 1 else "failed",
                "schema": schema_def,
                "tx_hash": tx_hash.hex(),
                "network": self.network,
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Schema creation failed: {e}"

    async def _attest(self, params: dict) -> str:
        """Create an attestation. Gas covered by platform."""
        from runtime.blockchain.eas_client import EASClient
        client = EASClient(self.config)
        data = params.get("data", {})
        result = await client.attest(
            action=data.get("action", "custom"),
            agent=data.get("agent", "neo"),
            details=data,
            recipient=params.get("recipient", "0x0000000000000000000000000000000000000000"),
        )
        return json.dumps(result, indent=2, default=str)

    async def _query(self, params: dict) -> str:
        """Query an attestation by UID."""
        uid = params.get("attestation_uid", "")
        return json.dumps({
            "uid": uid,
            "network": self.network,
            "query_url": f"https://base-sepolia.easscan.org/attestation/view/{uid}",
        })

    async def _revoke(self, params: dict) -> str:
        """Revoke an attestation on-chain via EAS. Gas covered by platform."""
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            uid = params.get("attestation_uid", "")
            if not uid:
                return json.dumps({"status": "error", "error": "attestation_uid is required"})

            eas_contract = bc.get("eas_contract", "")
            eas_schema = bc.get("eas_schema", "")
            if not eas_contract or not eas_schema:
                return json.dumps({
                    "status": "error",
                    "error": "blockchain.eas_contract and blockchain.eas_schema must be configured.",
                }, indent=2)

            eas_revoke_abi = [{
                "inputs": [{
                    "components": [
                        {"name": "schema", "type": "bytes32"},
                        {"components": [
                            {"name": "uid", "type": "bytes32"},
                            {"name": "value", "type": "uint256"},
                        ], "name": "data", "type": "tuple"},
                    ],
                    "name": "request",
                    "type": "tuple",
                }],
                "name": "revoke",
                "outputs": [],
                "stateMutability": "payable",
                "type": "function",
            }]

            eas = self.web3.eth.contract(
                address=Web3.to_checksum_address(eas_contract),
                abi=eas_revoke_abi,
            )
            account = Account.from_key(bc["paymaster_private_key"])

            schema_bytes = bytes.fromhex(eas_schema.replace("0x", ""))
            uid_bytes = bytes.fromhex(uid.replace("0x", ""))

            tx = eas.functions.revoke(
                (schema_bytes, (uid_bytes, 0))
            ).build_transaction({
                "from": bc["platform_wallet"],
                "chainId": self.chain_id,
                "gas": 200000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "revoked" if receipt["status"] == 1 else "failed",
                "uid": uid,
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Revocation failed: {e}"

    async def _batch_attest(self, params: dict) -> str:
        """Create multiple attestations. Gas covered by platform."""
        attestations = params.get("attestations", [])
        results = []
        from runtime.blockchain.eas_client import EASClient
        client = EASClient(self.config)
        for att in attestations:
            result = await client.attest(
                action=att.get("action", "custom"),
                agent=att.get("agent", "neo"),
                details=att,
            )
            results.append(result)
        return json.dumps({"batch_results": results, "count": len(results)}, indent=2, default=str)
