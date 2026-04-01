"""
IPRoyaltyService — intellectual property and royalty management for 0pnMatrx.

Handles registration, transfer, licensing, and royalty enforcement for
music, art, patents, trademarks, software, and literary works.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.ip_royalties.ip_registry import IPRegistry
from runtime.blockchain.services.ip_royalties.royalty_enforcement import RoyaltyEnforcement
from runtime.blockchain.services.ip_royalties.distribution import RoyaltyDistribution

logger = logging.getLogger(__name__)

IP_TYPES: set[str] = {
    "music", "art", "patent", "trademark", "software", "literary",
}


class IPRoyaltyService:
    """Main IP and royalty management service.

    Config keys (under ``config["ip_royalties"]``):
        max_licenses_per_ip (int): License cap per IP (default 1000).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        ip_cfg: dict[str, Any] = config.get("ip_royalties", {})

        self._max_licenses: int = int(
            ip_cfg.get("max_licenses_per_ip", 1_000)
        )

        self._registry = IPRegistry(config)
        self._enforcement = RoyaltyEnforcement(config)
        self._distribution = RoyaltyDistribution(config)

        # License store
        self._licenses: dict[str, dict[str, Any]] = {}
        # ip_id -> list of license_ids
        self._ip_licenses: dict[str, list[str]] = {}

        logger.info("IPRoyaltyService initialised.")

    @property
    def registry(self) -> IPRegistry:
        return self._registry

    @property
    def enforcement(self) -> RoyaltyEnforcement:
        return self._enforcement

    @property
    def distribution(self) -> RoyaltyDistribution:
        return self._distribution

    # ------------------------------------------------------------------
    # IP lifecycle
    # ------------------------------------------------------------------

    async def register_ip(
        self, owner: str, ip_type: str, metadata: dict,
    ) -> dict:
        """Register a new intellectual property asset.

        Args:
            owner: Address of the IP owner.
            ip_type: One of the supported IP_TYPES.
            metadata: Dict with ``title``, ``description``,
                      ``content_hash``, and type-specific fields.

        Returns:
            IP registration record.
        """
        if ip_type not in IP_TYPES:
            raise ValueError(
                f"Unknown ip_type '{ip_type}'. "
                f"Must be one of: {', '.join(sorted(IP_TYPES))}"
            )

        ip_record = await self._registry.register({
            "owner": owner,
            "ip_type": ip_type,
            "title": metadata.get("title", ""),
            "description": metadata.get("description", ""),
            "content_hash": metadata.get("content_hash", ""),
            "metadata": metadata,
        })

        logger.info(
            "IP registered: id=%s type=%s owner=%s title=%s",
            ip_record["ip_id"], ip_type, owner, metadata.get("title", ""),
        )
        return ip_record

    async def get_ip(self, ip_id: str) -> dict:
        """Retrieve an IP asset by ID."""
        ip_record = await self._registry.get(ip_id)
        licenses = self._ip_licenses.get(ip_id, [])

        return {
            **ip_record,
            "license_count": len(licenses),
            "royalty_config": await self._enforcement.get_config(ip_id),
        }

    async def transfer_ip(
        self, ip_id: str, from_owner: str, to_owner: str,
    ) -> dict:
        """Transfer IP ownership.

        Args:
            ip_id: The IP to transfer.
            from_owner: Current owner address.
            to_owner: New owner address.

        Returns:
            Updated IP record.
        """
        ip_record = await self._registry.get(ip_id)
        if ip_record["owner"] != from_owner:
            raise ValueError(f"IP {ip_id} is not owned by {from_owner}")

        ip_record["owner"] = to_owner
        ip_record["transfer_history"] = ip_record.get("transfer_history", [])
        ip_record["transfer_history"].append({
            "from": from_owner,
            "to": to_owner,
            "timestamp": int(time.time()),
        })
        ip_record["updated_at"] = int(time.time())

        await self._registry.update(ip_id, ip_record)

        logger.info(
            "IP transferred: id=%s from=%s to=%s",
            ip_id, from_owner, to_owner,
        )
        return ip_record

    async def license_ip(
        self, ip_id: str, licensee: str, terms: dict,
    ) -> dict:
        """Grant a license for an IP asset.

        Args:
            ip_id: The IP being licensed.
            licensee: Address of the licensee.
            terms: Dict with ``license_type`` ("exclusive", "non_exclusive"),
                   ``duration_days``, ``territory``, ``royalty_pct``,
                   ``usage_types`` (list).

        Returns:
            License record.
        """
        ip_record = await self._registry.get(ip_id)

        existing = self._ip_licenses.get(ip_id, [])
        if len(existing) >= self._max_licenses:
            raise ValueError(
                f"Maximum licenses ({self._max_licenses}) reached for IP {ip_id}"
            )

        # Check exclusivity conflicts
        license_type = terms.get("license_type", "non_exclusive")
        if license_type == "exclusive":
            active_exclusive = [
                lid for lid in existing
                if self._licenses.get(lid, {}).get("license_type") == "exclusive"
                and self._licenses.get(lid, {}).get("status") == "active"
            ]
            if active_exclusive:
                raise ValueError(
                    f"IP {ip_id} already has an active exclusive license"
                )

        license_id = f"lic_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        duration_days = int(terms.get("duration_days", 365))

        license_record: dict[str, Any] = {
            "license_id": license_id,
            "ip_id": ip_id,
            "ip_owner": ip_record["owner"],
            "licensee": licensee,
            "license_type": license_type,
            "territory": terms.get("territory", "worldwide"),
            "usage_types": terms.get("usage_types", ["all"]),
            "royalty_pct": float(terms.get("royalty_pct", 0)),
            "status": "active",
            "created_at": now,
            "expires_at": now + duration_days * 86400,
        }
        self._licenses[license_id] = license_record
        self._ip_licenses.setdefault(ip_id, []).append(license_id)

        logger.info(
            "License granted: id=%s ip=%s licensee=%s type=%s",
            license_id, ip_id, licensee, license_type,
        )
        return license_record
