"""
Manifest Manager — tracks every component through the bridge lifecycle.

Each component's journey is recorded:
    export -> sanitization -> approval -> deployment -> attestation -> ios_packaging

The manifest enforces invariants:
    - No deployment without explicit Dardan approval
    - No duplicate active entries for the same component
    - Full audit trail of every export and decision

Manifest is persisted as JSON at data/bridge/manifest.json.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ManifestEntry:
    """A single component's lifecycle record."""
    component_name: str
    version: str
    export_date: float = field(default_factory=time.time)
    content_hash: str = ""
    sanitizer_result: str = "pending"       # pending | clean | violations_found
    dardan_approval: str = "pending"        # pending | approved | rejected
    deployment_status: str = "pending"      # pending | deployed | failed | attested
    deployment_id: str = ""
    attestation_uid: str = ""
    ios_packaged: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_name": self.component_name,
            "version": self.version,
            "export_date": self.export_date,
            "content_hash": self.content_hash,
            "sanitizer_result": self.sanitizer_result,
            "dardan_approval": self.dardan_approval,
            "deployment_status": self.deployment_status,
            "deployment_id": self.deployment_id,
            "attestation_uid": self.attestation_uid,
            "ios_packaged": self.ios_packaged,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManifestEntry:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ManifestManager:
    """Tracks every component export through the full bridge lifecycle.

    Usage::

        manifest = ManifestManager()
        entry = manifest.create_entry("defi", "1.0.0", content_hash="abc...")

        manifest.update_sanitizer(entry.component_name, "clean")
        manifest.update_approval(entry.component_name, "approved")
        manifest.update_deployment(entry.component_name, "deployed", deployment_id="xyz")

        manifest.save()
    """

    def __init__(self, manifest_path: str = "data/bridge/manifest.json"):
        self.manifest_path = Path(manifest_path)
        self.entries: list[ManifestEntry] = []
        self._load()

    def _load(self) -> None:
        """Load manifest from disk."""
        if self.manifest_path.exists():
            try:
                data = json.loads(self.manifest_path.read_text())
                self.entries = [ManifestEntry.from_dict(e) for e in data]
                logger.info("Loaded manifest with %d entries", len(self.entries))
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Failed to load manifest, starting fresh: %s", exc)
                self.entries = []
        else:
            self.entries = []

    def save(self) -> None:
        """Persist manifest to disk."""
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        data = [e.to_dict() for e in self.entries]
        self.manifest_path.write_text(json.dumps(data, indent=2))
        logger.debug("Manifest saved with %d entries", len(self.entries))

    def create_entry(
        self,
        component_name: str,
        version: str,
        content_hash: str = "",
    ) -> ManifestEntry:
        """Create a new manifest entry for a component export.

        Raises:
            ValueError: If there's already an active (non-deployed) entry
            for this component.
        """
        # Prevent duplicate active entries
        existing = self.get_active_entry(component_name)
        if existing:
            raise ValueError(
                f"Active entry already exists for {component_name} "
                f"(status: {existing.deployment_status}). "
                f"Complete or remove it before creating a new one."
            )

        entry = ManifestEntry(
            component_name=component_name,
            version=version,
            content_hash=content_hash,
        )
        self.entries.append(entry)
        self.save()

        logger.info("Created manifest entry: %s v%s", component_name, version)
        return entry

    def get_active_entry(self, component_name: str) -> ManifestEntry | None:
        """Get the most recent non-deployed entry for a component."""
        for entry in reversed(self.entries):
            if (
                entry.component_name == component_name
                and entry.deployment_status in ("pending", "failed")
            ):
                return entry
        return None

    def get_entry(self, component_name: str) -> ManifestEntry | None:
        """Get the most recent entry for a component (any status)."""
        for entry in reversed(self.entries):
            if entry.component_name == component_name:
                return entry
        return None

    def update_sanitizer(self, component_name: str, result: str) -> ManifestEntry | None:
        """Update the sanitizer result for a component.

        Args:
            component_name: Component to update.
            result: "clean" or "violations_found"
        """
        entry = self.get_active_entry(component_name)
        if not entry:
            logger.warning("No active entry for %s", component_name)
            return None

        entry.sanitizer_result = result
        self.save()
        return entry

    def update_approval(self, component_name: str, status: str) -> ManifestEntry | None:
        """Update Dardan's approval status.

        Args:
            component_name: Component to update.
            status: "approved" or "rejected"
        """
        entry = self.get_active_entry(component_name)
        if not entry:
            logger.warning("No active entry for %s", component_name)
            return None

        entry.dardan_approval = status
        self.save()
        return entry

    def update_deployment(
        self,
        component_name: str,
        status: str,
        deployment_id: str = "",
        attestation_uid: str = "",
    ) -> ManifestEntry | None:
        """Update deployment status.

        Args:
            component_name: Component to update.
            status: "deployed", "failed", or "attested"
            deployment_id: The deployment ID if deployed.
            attestation_uid: EAS attestation UID if attested.
        """
        entry = self.get_active_entry(component_name) or self.get_entry(component_name)
        if not entry:
            logger.warning("No entry for %s", component_name)
            return None

        # Guard: cannot deploy without approval
        if status == "deployed" and entry.dardan_approval != "approved":
            logger.error(
                "Cannot mark %s as deployed: approval status is %s",
                component_name, entry.dardan_approval,
            )
            return None

        entry.deployment_status = status
        if deployment_id:
            entry.deployment_id = deployment_id
        if attestation_uid:
            entry.attestation_uid = attestation_uid
        self.save()
        return entry

    def update_ios_packaged(self, component_name: str) -> ManifestEntry | None:
        """Mark a component as packaged for iOS."""
        entry = self.get_entry(component_name)
        if not entry:
            return None
        entry.ios_packaged = True
        self.save()
        return entry

    def get_all(self) -> list[dict[str, Any]]:
        """Return all manifest entries as dicts."""
        return [e.to_dict() for e in self.entries]

    def get_summary(self) -> dict[str, Any]:
        """Return a summary of the manifest state."""
        total = len(self.entries)
        deployed = sum(1 for e in self.entries if e.deployment_status in ("deployed", "attested"))
        pending = sum(1 for e in self.entries if e.deployment_status == "pending")
        failed = sum(1 for e in self.entries if e.deployment_status == "failed")
        ios_packaged = sum(1 for e in self.entries if e.ios_packaged)

        return {
            "total_entries": total,
            "deployed": deployed,
            "pending": pending,
            "failed": failed,
            "ios_packaged": ios_packaged,
        }
