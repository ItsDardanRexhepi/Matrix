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
        """Create a new EAS schema. Gas covered by platform."""
        schema_def = params.get("schema", "string action, string agent, uint256 timestamp")
        return json.dumps({
            "status": "schema_ready",
            "schema": schema_def,
            "note": "Schema registration requires SchemaRegistry contract interaction. Gas covered by platform.",
            "network": self.network,
        }, indent=2)

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
        """Revoke an attestation. Gas covered by platform."""
        uid = params.get("attestation_uid", "")
        return json.dumps({
            "status": "revocation_prepared",
            "uid": uid,
            "note": "Revocation requires EAS contract call. Gas covered by platform.",
        })

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
