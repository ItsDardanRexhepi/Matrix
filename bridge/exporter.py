"""
Component Exporter — receives and unpacks component bundles from Matrix.

The Matrix private runtime packages components via its own exporter
(strips private refs, security layers, and internal routing), then
sends the sanitized bundle here for deployment into the public runtime.

This module:
    - Validates the incoming bundle structure
    - Extracts component metadata and source files
    - Strips any residual private references that may have slipped through
    - Prepares a clean component package for the sanitizer stage
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExportBundle:
    """Validated component bundle ready for sanitization."""
    component_name: str
    version: str
    source_files: dict[str, str]       # filename -> content
    metadata: dict[str, Any]
    content_hash: str
    exported_at: float = field(default_factory=time.time)

    @property
    def file_count(self) -> int:
        return len(self.source_files)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_name": self.component_name,
            "version": self.version,
            "file_count": self.file_count,
            "content_hash": self.content_hash,
            "exported_at": self.exported_at,
            "metadata": self.metadata,
        }


# Patterns that should NEVER appear in exported components
_PRIVATE_PATTERNS = [
    re.compile(r"PRIVATE_KEY\s*=", re.IGNORECASE),
    re.compile(r"SEED_PHRASE\s*=", re.IGNORECASE),
    re.compile(r"WALLET_SECRET\s*=", re.IGNORECASE),
    re.compile(r"DARDAN_CONFIG", re.IGNORECASE),
    re.compile(r"INTERNAL_USE_ONLY", re.IGNORECASE),
    re.compile(r"DO_NOT_EXPORT", re.IGNORECASE),
    re.compile(r"CLOSED_SOURCE_ONLY", re.IGNORECASE),
    re.compile(r"MatrixSecurityLayer", re.IGNORECASE),
    re.compile(r"NeoSafe\.internal", re.IGNORECASE),
    re.compile(r"matrix\.private\.", re.IGNORECASE),
]


class ComponentExporter:
    """Receives, validates, and unpacks component bundles from Matrix.

    Usage::

        exporter = ComponentExporter(staging_dir="data/bridge/staging")
        bundle = await exporter.receive_bundle(raw_bundle_dict)
        # bundle is now an ExportBundle ready for sanitization
    """

    def __init__(self, staging_dir: str = "data/bridge/staging"):
        self.staging_dir = Path(staging_dir)
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    async def receive_bundle(self, raw: dict[str, Any]) -> ExportBundle:
        """Validate and unpack a raw component bundle.

        Args:
            raw: Dictionary with keys: component_name, version, files, metadata

        Returns:
            ExportBundle ready for the sanitizer.

        Raises:
            ValueError: If the bundle is malformed or contains private data.
        """
        self._validate_structure(raw)

        component_name = raw["component_name"]
        version = raw.get("version", "1.0.0")
        files = raw["files"]  # dict of filename -> content
        metadata = raw.get("metadata", {})

        # Pre-strip any residual private references
        cleaned_files = {}
        for filename, content in files.items():
            cleaned = self._strip_private_refs(content, filename)
            cleaned_files[filename] = cleaned

        # Compute deterministic content hash
        content_hash = self._compute_hash(cleaned_files)

        bundle = ExportBundle(
            component_name=component_name,
            version=version,
            source_files=cleaned_files,
            metadata=metadata,
            content_hash=content_hash,
        )

        # Stage the bundle to disk
        await self._stage_bundle(bundle)

        logger.info(
            "Received bundle: %s v%s (%d files, hash=%s)",
            component_name, version, bundle.file_count, content_hash[:12],
        )
        return bundle

    def _validate_structure(self, raw: dict[str, Any]) -> None:
        """Ensure the bundle has required fields."""
        required = ["component_name", "files"]
        for key in required:
            if key not in raw:
                raise ValueError(f"Bundle missing required field: '{key}'")

        if not isinstance(raw["files"], dict) or not raw["files"]:
            raise ValueError("Bundle 'files' must be a non-empty dict of filename -> content")

        name = raw["component_name"]
        if not re.match(r"^[a-z][a-z0-9_]{1,63}$", name):
            raise ValueError(
                f"Invalid component name '{name}': must be lowercase alphanumeric "
                f"with underscores, 2-64 chars, starting with a letter."
            )

    def _strip_private_refs(self, content: str, filename: str) -> str:
        """Remove any private references that slipped through the Matrix exporter."""
        for pattern in _PRIVATE_PATTERNS:
            if pattern.search(content):
                logger.warning(
                    "Stripped private reference matching '%s' from %s",
                    pattern.pattern, filename,
                )
                content = pattern.sub("# [STRIPPED BY BRIDGE]", content)
        return content

    def _compute_hash(self, files: dict[str, str]) -> str:
        """Compute a deterministic SHA-256 hash of all files."""
        hasher = hashlib.sha256()
        for filename in sorted(files.keys()):
            hasher.update(filename.encode())
            hasher.update(files[filename].encode())
        return hasher.hexdigest()

    async def _stage_bundle(self, bundle: ExportBundle) -> Path:
        """Write the bundle to the staging directory."""
        bundle_dir = self.staging_dir / bundle.component_name / bundle.version
        bundle_dir.mkdir(parents=True, exist_ok=True)

        # Write source files
        src_dir = bundle_dir / "src"
        src_dir.mkdir(exist_ok=True)
        for filename, content in bundle.source_files.items():
            (src_dir / filename).write_text(content)

        # Write metadata
        meta_path = bundle_dir / "bundle.json"
        meta_path.write_text(json.dumps(bundle.to_dict(), indent=2))

        return bundle_dir

    async def list_staged(self) -> list[dict[str, Any]]:
        """List all staged bundles."""
        results = []
        if not self.staging_dir.exists():
            return results

        for comp_dir in sorted(self.staging_dir.iterdir()):
            if not comp_dir.is_dir():
                continue
            for ver_dir in sorted(comp_dir.iterdir()):
                meta_path = ver_dir / "bundle.json"
                if meta_path.exists():
                    results.append(json.loads(meta_path.read_text()))

        return results

    async def clear_staged(self, component_name: str, version: str) -> bool:
        """Remove a staged bundle after successful deployment."""
        bundle_dir = self.staging_dir / component_name / version
        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)
            logger.info("Cleared staged bundle: %s v%s", component_name, version)
            return True
        return False
