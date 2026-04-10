"""
Sanitization Validator — scans exported components for forbidden patterns.

Re-validates that no private data, security layer references, Matrix-specific
routing, or closed-source content leaked through the export pipeline. This is
the second line of defense after the Matrix-side exporter.

If ANY violation is found, the component is BLOCKED from deployment and an
alert is sent via Telegram.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from bridge.exporter import ExportBundle

logger = logging.getLogger(__name__)


@dataclass
class SanitizationResult:
    """Result of scanning a component bundle."""
    component_name: str
    is_clean: bool
    violations: list[dict[str, str]] = field(default_factory=list)
    files_scanned: int = 0
    patterns_checked: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_name": self.component_name,
            "is_clean": self.is_clean,
            "violation_count": len(self.violations),
            "violations": self.violations,
            "files_scanned": self.files_scanned,
            "patterns_checked": self.patterns_checked,
        }


# ---------------------------------------------------------------------------
# Forbidden pattern categories
# ---------------------------------------------------------------------------

_PRIVATE_DATA_PATTERNS = [
    (re.compile(r"private[_\s]*key\s*[:=]", re.IGNORECASE), "Private key assignment"),
    (re.compile(r"seed[_\s]*phrase\s*[:=]", re.IGNORECASE), "Seed phrase assignment"),
    (re.compile(r"mnemonic\s*[:=]\s*[\"']", re.IGNORECASE), "Mnemonic literal"),
    (re.compile(r"wallet[_\s]*secret\s*[:=]", re.IGNORECASE), "Wallet secret"),
    (re.compile(r"DARDAN_CONFIG", re.IGNORECASE), "Dardan-specific config"),
    (re.compile(r"dardan[_\.]", re.IGNORECASE), "Dardan reference"),
    (re.compile(r"0x[a-fA-F0-9]{64}"), "Raw 256-bit hex literal (possible key)"),
    (re.compile(r"api[_\s]*secret\s*[:=]\s*[\"']", re.IGNORECASE), "API secret literal"),
    (re.compile(r"INTERNAL_SECRET", re.IGNORECASE), "Internal secret marker"),
    (re.compile(r"password\s*[:=]\s*[\"'][^\"']+[\"']", re.IGNORECASE), "Hardcoded password"),
]

_SECURITY_LAYER_PATTERNS = [
    (re.compile(r"MatrixSecurityLayer", re.IGNORECASE), "Matrix security layer reference"),
    (re.compile(r"NeoSafe\.internal", re.IGNORECASE), "NeoSafe internal reference"),
    (re.compile(r"CLOSED_SOURCE_ONLY", re.IGNORECASE), "Closed-source marker"),
    (re.compile(r"security_layer\.(encrypt|decrypt|sign)", re.IGNORECASE), "Security layer method"),
    (re.compile(r"from\s+matrix\.security", re.IGNORECASE), "Matrix security import"),
    (re.compile(r"import\s+.*matrix\.security", re.IGNORECASE), "Matrix security import"),
]

_MATRIX_ROUTING_PATTERNS = [
    (re.compile(r"matrix\.private\.", re.IGNORECASE), "Matrix private routing"),
    (re.compile(r"matrix\.internal\.", re.IGNORECASE), "Matrix internal routing"),
    (re.compile(r"INTERNAL_ROUTE", re.IGNORECASE), "Internal route marker"),
    (re.compile(r"governance\.internal", re.IGNORECASE), "Internal governance endpoint"),
    (re.compile(r"from\s+matrix\.routing", re.IGNORECASE), "Matrix routing import"),
    (re.compile(r"matrix_router\.", re.IGNORECASE), "Matrix router reference"),
]

_CLOSED_SOURCE_PATTERNS = [
    (re.compile(r"DO_NOT_EXPORT", re.IGNORECASE), "Do-not-export marker"),
    (re.compile(r"INTERNAL_USE_ONLY", re.IGNORECASE), "Internal-use marker"),
    (re.compile(r"PROPRIETARY", re.IGNORECASE), "Proprietary marker"),
    (re.compile(r"# ?COPYRIGHT.*MATRIX", re.IGNORECASE), "Matrix copyright header"),
    (re.compile(r"CONFIDENTIAL", re.IGNORECASE), "Confidential marker"),
]

ALL_PATTERN_CATEGORIES = {
    "private_data": _PRIVATE_DATA_PATTERNS,
    "security_layer": _SECURITY_LAYER_PATTERNS,
    "matrix_routing": _MATRIX_ROUTING_PATTERNS,
    "closed_source": _CLOSED_SOURCE_PATTERNS,
}


class SanitizationValidator:
    """Scans component bundles for forbidden patterns across 4 categories.

    Usage::

        validator = SanitizationValidator()
        result = await validator.validate(bundle)
        if not result.is_clean:
            # Block deployment, send alert
            ...
    """

    def __init__(self, extra_patterns: dict[str, list] | None = None):
        """Initialize with optional extra pattern categories."""
        self.categories = dict(ALL_PATTERN_CATEGORIES)
        if extra_patterns:
            self.categories.update(extra_patterns)

        self._total_patterns = sum(len(pats) for pats in self.categories.values())

    async def validate(self, bundle: ExportBundle) -> SanitizationResult:
        """Scan all files in a bundle for forbidden patterns.

        Args:
            bundle: The ExportBundle to validate.

        Returns:
            SanitizationResult with is_clean=True if no violations found.
        """
        violations: list[dict[str, str]] = []

        for filename, content in bundle.source_files.items():
            file_violations = self._scan_content(content, filename)
            violations.extend(file_violations)

        result = SanitizationResult(
            component_name=bundle.component_name,
            is_clean=len(violations) == 0,
            violations=violations,
            files_scanned=bundle.file_count,
            patterns_checked=self._total_patterns,
        )

        if result.is_clean:
            logger.info(
                "Sanitization PASSED for %s (%d files, %d patterns checked)",
                bundle.component_name, result.files_scanned, result.patterns_checked,
            )
        else:
            logger.warning(
                "Sanitization FAILED for %s: %d violations found",
                bundle.component_name, len(violations),
            )

        return result

    def _scan_content(self, content: str, filename: str) -> list[dict[str, str]]:
        """Scan a single file's content against all pattern categories."""
        violations = []
        lines = content.split("\n")

        for category, patterns in self.categories.items():
            for pattern, description in patterns:
                for line_num, line in enumerate(lines, 1):
                    if pattern.search(line):
                        violations.append({
                            "file": filename,
                            "line": line_num,
                            "category": category,
                            "pattern": description,
                            "match": line.strip()[:120],
                        })

        return violations

    async def quick_check(self, content: str) -> bool:
        """Quick boolean check — True if content is clean."""
        for patterns in self.categories.values():
            for pattern, _ in patterns:
                if pattern.search(content):
                    return False
        return True

    def get_pattern_summary(self) -> dict[str, int]:
        """Return count of patterns per category."""
        return {cat: len(pats) for cat, pats in self.categories.items()}
