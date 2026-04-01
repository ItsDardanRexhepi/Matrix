"""
IPRegistry — content-addressed IP registration with hash, timestamp, and metadata.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class IPRegistry:
    """Registry for intellectual property assets.

    Each IP is registered with a content hash (SHA-256 of the work),
    a timestamp, and rich metadata. Registration is content-addressed:
    the same content hash cannot be registered twice.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        # ip_id -> IP record
        self._registry: dict[str, dict[str, Any]] = {}
        # content_hash -> ip_id (uniqueness index)
        self._hash_index: dict[str, str] = {}

    async def register(self, ip: dict) -> dict:
        """Register a new IP asset.

        Args:
            ip: Dict with ``owner``, ``ip_type``, ``title``,
                ``description``, ``content_hash``, ``metadata``.

        Returns:
            Registration record with ``ip_id``.
        """
        content_hash = ip.get("content_hash", "")
        if not content_hash:
            # Generate from metadata if not provided
            hashable = f"{ip.get('title', '')}{ip.get('description', '')}{ip.get('owner', '')}"
            content_hash = hashlib.sha256(hashable.encode()).hexdigest()

        # Check uniqueness
        if content_hash in self._hash_index:
            existing_id = self._hash_index[content_hash]
            raise ValueError(
                f"Content hash already registered as IP {existing_id}"
            )

        ip_id = f"ip_{uuid.uuid4().hex[:16]}"
        now = int(time.time())

        record: dict[str, Any] = {
            "ip_id": ip_id,
            "owner": ip["owner"],
            "ip_type": ip.get("ip_type", ""),
            "title": ip.get("title", ""),
            "description": ip.get("description", ""),
            "content_hash": content_hash,
            "metadata": ip.get("metadata", {}),
            "status": "registered",
            "transfer_history": [],
            "registered_at": now,
            "updated_at": now,
        }
        self._registry[ip_id] = record
        self._hash_index[content_hash] = ip_id

        logger.info(
            "IP registered in registry: id=%s hash=%s",
            ip_id, content_hash[:16],
        )
        return record

    async def get(self, ip_id: str) -> dict:
        """Retrieve an IP record by ID."""
        record = self._registry.get(ip_id)
        if not record:
            raise ValueError(f"IP {ip_id} not found")
        return record

    async def update(self, ip_id: str, data: dict) -> dict:
        """Update an existing IP record."""
        if ip_id not in self._registry:
            raise ValueError(f"IP {ip_id} not found")
        self._registry[ip_id] = data
        return data

    async def search(self, query: dict) -> list:
        """Search for IP assets.

        Supported query keys:
            - owner: Filter by owner address.
            - ip_type: Filter by IP type.
            - title: Substring search in title.
            - content_hash: Exact hash match.
            - limit: Max results (default 50).

        Returns:
            List of matching IP records.
        """
        results: list[dict[str, Any]] = []
        limit = int(query.get("limit", 50))

        owner_filter = query.get("owner", "")
        type_filter = query.get("ip_type", "")
        title_filter = query.get("title", "").lower()
        hash_filter = query.get("content_hash", "")

        for record in self._registry.values():
            if owner_filter and record["owner"] != owner_filter:
                continue
            if type_filter and record["ip_type"] != type_filter:
                continue
            if title_filter and title_filter not in record.get("title", "").lower():
                continue
            if hash_filter and record["content_hash"] != hash_filter:
                continue

            results.append(record)
            if len(results) >= limit:
                break

        return results

    async def verify_ownership(self, ip_id: str, claimant: str) -> dict:
        """Verify whether a claimant owns an IP asset.

        Returns:
            Dict with ``verified`` bool, ``owner``, ``ip_id``.
        """
        record = self._registry.get(ip_id)
        if not record:
            return {
                "verified": False,
                "ip_id": ip_id,
                "reason": "IP not found",
            }

        is_owner = record["owner"] == claimant
        return {
            "verified": is_owner,
            "ip_id": ip_id,
            "claimant": claimant,
            "actual_owner": record["owner"],
            "registered_at": record["registered_at"],
            "content_hash": record["content_hash"],
        }
