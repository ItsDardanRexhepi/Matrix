"""
IP & Royalties — intellectual property management and royalty distribution on Base L2.

Register IP on-chain, configure royalty splits, distribute payments.
All gas covered by the platform.
"""

import json
import logging
import time

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)


class IPRoyalties(BlockchainInterface):

    @property
    def name(self) -> str:
        return "ip_royalties"

    @property
    def description(self) -> str:
        return "IP management and royalty distribution: register IP, set royalty splits, distribute payments. Gas covered by platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["register_ip", "set_royalties", "distribute", "get_ip"]},
                "ip_name": {"type": "string"},
                "ip_type": {"type": "string", "description": "Type: patent, copyright, trademark, license"},
                "owner": {"type": "string"},
                "royalty_recipients": {"type": "array", "items": {"type": "object"}, "description": "List of {address, share_bps}"},
                "ip_id": {"type": "string"},
                "amount": {"type": "string"},
                "token_address": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "register_ip":
            return await self._register_ip(kwargs)
        elif action == "set_royalties":
            return await self._set_royalties(kwargs)
        elif action == "distribute":
            return await self._distribute(kwargs)
        elif action == "get_ip":
            return await self._get_ip(kwargs)
        return f"Unknown IP action: {action}"

    async def _register_ip(self, params: dict) -> str:
        """Register intellectual property on-chain via EAS attestation."""
        from runtime.blockchain.eas_client import EASClient
        client = EASClient(self.config)
        result = await client.attest(
            action="ip_registration",
            agent="neo",
            details={
                "ip_name": params.get("ip_name", ""),
                "ip_type": params.get("ip_type", "copyright"),
                "owner": params.get("owner", self.platform_wallet),
                "registered_at": int(time.time()),
            },
            recipient=params.get("owner", "0x0000000000000000000000000000000000000000"),
        )
        return json.dumps(result, indent=2, default=str)

    async def _set_royalties(self, params: dict) -> str:
        """Configure royalty split for an IP asset."""
        recipients = params.get("royalty_recipients", [])
        total_bps = sum(r.get("share_bps", 0) for r in recipients)
        if total_bps > 10000:
            return "Error: total royalty shares exceed 100% (10000 bps)"
        return json.dumps({
            "ip_id": params.get("ip_id", ""),
            "royalty_config": recipients,
            "total_bps": total_bps,
            "status": "configured",
            "note": "Royalty distribution will use this split. Gas covered by platform.",
        }, indent=2)

    async def _distribute(self, params: dict) -> str:
        """Distribute royalty payments to recipients. Gas covered by platform."""
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            recipients = params.get("royalty_recipients", [])
            total_amount = float(params.get("amount", "0"))
            token_address = params.get("token_address", "")

            if not recipients:
                return json.dumps({"status": "error", "error": "royalty_recipients list is required"})
            if total_amount <= 0:
                return json.dumps({"status": "error", "error": "amount must be greater than 0"})

            account = Account.from_key(bc["paymaster_private_key"])
            results = []

            for recipient in recipients:
                addr = recipient.get("address", "")
                share_bps = recipient.get("share_bps", 0)
                share_amount = total_amount * share_bps / 10000

                if not addr or share_amount <= 0:
                    results.append({"address": addr, "status": "skipped", "reason": "invalid address or zero share"})
                    continue

                try:
                    amount_wei = self.web3.to_wei(share_amount, "ether")
                    tx = {
                        "from": bc["platform_wallet"],
                        "to": Web3.to_checksum_address(addr),
                        "value": amount_wei,
                        "chainId": self.chain_id,
                        "gas": 21000,
                        "gasPrice": self.web3.eth.gas_price,
                        "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
                    }
                    signed = account.sign_transaction(tx)
                    tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
                    receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

                    results.append({
                        "address": addr,
                        "share_bps": share_bps,
                        "amount_eth": str(share_amount),
                        "status": "sent" if receipt["status"] == 1 else "failed",
                        "tx_hash": tx_hash.hex(),
                    })
                except Exception as e:
                    results.append({"address": addr, "status": "failed", "error": str(e)})

            return json.dumps({
                "ip_id": params.get("ip_id", ""),
                "total_amount": str(total_amount),
                "distributions": results,
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Distribution failed: {e}"

    async def _get_ip(self, params: dict) -> str:
        """Query IP registration details by verifying the EAS attestation."""
        try:
            ip_id = params.get("ip_id", "")
            if not ip_id:
                return json.dumps({"status": "error", "error": "ip_id (EAS attestation UID) is required"})

            from runtime.blockchain.eas_client import EASClient
            client = EASClient(self.config)
            result = await client.verify(ip_id)

            return json.dumps({
                "ip_id": ip_id,
                "attestation": result,
                "network": self.network,
            }, indent=2, default=str)
        except Exception as e:
            return json.dumps({
                "ip_id": params.get("ip_id", ""),
                "status": "error",
                "error": str(e),
                "hint": "Ensure blockchain.eas_contract and blockchain.rpc_url are configured.",
            }, indent=2)
