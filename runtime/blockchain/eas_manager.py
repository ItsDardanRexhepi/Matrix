"""
EAS Manager — attestation management for The Matrix.

Creates schemas and answers queries. It does not sign attestations or
revocations on request: every attestation the platform makes is signed with
the platform's key, so one whose action, agent and recipient the request
writes is the platform vouching for whatever it was told, and a revocation of
an attestation the request names voids a record about somebody else. The
platform attests what it does when it does it; revoking is not a request's to
make (register entry::B3-ATTEST-SIBLING, entry::U-ATTEST-AXIS). Gas covered by
the platform.
"""

import json
import logging

from runtime.blockchain.interface import BlockchainInterface
from runtime.protocols.outcome_truth import refusal

logger = logging.getLogger(__name__)


class EASManager(BlockchainInterface):

    @property
    def name(self) -> str:
        return "eas"

    @property
    def description(self) -> str:
        return ("Manage EAS attestations: create a schema, query an attestation. attest, "
                "batch_attest and revoke are refused: the platform key signs no attestation "
                "whose content a request writes, and revokes none a request names. "
                "Gas covered by platform.")

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
        return refusal(
            f"Unknown EAS action: {action}",
            code="unknown_action")

    async def _create_schema(self, params: dict) -> str:
        """Create a new EAS schema on-chain via the SchemaRegistry. Gas covered by platform."""
        try:
            from web3 import Web3

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            schema_registry_addr = bc.get("eas_schema_registry", "")
            if not schema_registry_addr or str(schema_registry_addr).startswith("YOUR_"):
                return json.dumps({
                    "status": "error",
                    "error": "blockchain.eas_schema_registry address is not configured.",
                    "hint": "Set eas_schema_registry in matrix.config.json (e.g., 0x4200000000000000000000000000000000000020 on Base).",
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
            account = await self._platform_signer("eas_manager.create_schema")

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
            receipt = await self._receipt(tx_hash, "eas_manager.create_schema")
            if receipt is None:
                return self._unconfirmed(tx_hash, **{"schema": schema_def, "network": self.network})

            return json.dumps({
                "status": "registered" if receipt["status"] == 1 else "failed",
                "schema": schema_def,
                "tx_hash": tx_hash.hex(),
                "network": self.network,
                "gas_paid_by": "platform (The Matrix)",
            }, indent=2)
        except Exception as e:
            return refusal(
                f"Schema creation failed: {e}",
                code="capability_error")

    async def _attest(self, params: dict) -> str:
        """REFUSED. This signed, with the platform key, an attestation whose
        action and agent were ``data.action`` / ``data.agent`` and whose
        recipient was ``recipient`` — every part of it as the request wrote it:
        a public statement that "agent morpheus approved a withdrawal for
        0x…", composed by whoever asked. The same statement agent_identity's
        attest_action made, one tool over. Nothing here to sign.
        """
        return refusal(
            "The platform key does not sign an attestation whose action, agent and "
            "recipient are whatever the request says; the platform attests an action "
            "when it executes it. Nothing was attested.",
            code="denied")

    async def _query(self, params: dict) -> str:
        """Query an attestation by UID."""
        uid = params.get("attestation_uid", "")
        return json.dumps({
            "uid": uid,
            "network": self.network,
            "query_url": f"https://base-sepolia.easscan.org/attestation/view/{uid}",
        })

    async def _revoke(self, params: dict) -> str:
        """REFUSED. This revoked, with the platform key, whichever attestation
        the request named. EAS lets the attester revoke, and the platform is
        the attester of every record it signs — somebody's identity
        registration, an insurance policy that insurance.get_policy verifies
        by its uid — so a request could void a record about somebody else.
        """
        return refusal(
            "The platform key does not revoke an attestation because a request names "
            "it: the record may be about somebody else. Nothing was revoked.",
            code="denied")

    async def _batch_attest(self, params: dict) -> str:
        """REFUSED, as ``_attest`` is: each entry's action and agent were the
        request's, one platform-signed attestation per entry."""
        return refusal(
            "The platform key does not sign attestations whose action and agent are "
            "whatever the request says, one or many; nothing was attested.",
            code="denied")
