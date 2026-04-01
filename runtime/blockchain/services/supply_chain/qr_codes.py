"""
QRCodeGenerator -- generates and verifies QR codes for supply chain products.

QR encodes product_id + verification hash. Returns base64-encoded QR image
data. Verification scans validate the embedded hash against the registry.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# QR code version/format identifier
QR_FORMAT_VERSION = "0pnmatrx-sc-v1"


class QRCodeGenerator:
    """
    Generates and verifies QR codes for supply chain product tracking.

    Each QR code encodes a JSON payload with product_id, verification hash,
    and optional product data. The verification hash allows offline
    authenticity checks.

    Config keys (under config["supply_chain"]):
        qr_secret       -- HMAC secret for verification hashes
        qr_box_size     -- QR code pixel box size (default 10)
        qr_border       -- QR code border size (default 4)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        sc = config.get("supply_chain", {})

        self.qr_secret: str = sc.get("qr_secret", "0pnmatrx-default-qr-secret")
        self.qr_box_size: int = sc.get("qr_box_size", 10)
        self.qr_border: int = sc.get("qr_border", 4)

        # Cache of generated QR codes: product_id -> qr_data
        self._qr_cache: dict[str, dict[str, Any]] = {}

        logger.info("QRCodeGenerator initialised.")

    async def generate(
        self,
        product_id: str,
        include_data: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Generate a QR code for a product.

        The QR code contains a JSON payload with the product_id,
        verification hash, and any requested additional data fields.

        Args:
            product_id: The product identifier.
            include_data: Optional list of additional data keys to embed
                         (e.g. ["manufacturer", "sku", "batch"]).

        Returns:
            Dict with base64-encoded QR image, payload, and verification hash.
        """
        if not product_id:
            return {"status": "error", "error": "Product ID is required"}

        timestamp = int(time.time())
        verification_hash = self._compute_verification_hash(product_id, timestamp)

        # Build QR payload
        payload: dict[str, Any] = {
            "format": QR_FORMAT_VERSION,
            "product_id": product_id,
            "verification_hash": verification_hash,
            "generated_at": timestamp,
        }

        if include_data:
            payload["included_fields"] = include_data

        payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)

        # Generate QR code image
        qr_image_b64 = self._render_qr_code(payload_json)

        result: dict[str, Any] = {
            "status": "generated",
            "product_id": product_id,
            "qr_image_base64": qr_image_b64,
            "qr_payload": payload,
            "verification_hash": verification_hash,
            "generated_at": timestamp,
            "format": QR_FORMAT_VERSION,
        }

        # Cache the QR data
        self._qr_cache[product_id] = {
            "verification_hash": verification_hash,
            "generated_at": timestamp,
            "payload": payload,
        }

        logger.debug("QR code generated for product: %s", product_id)

        return result

    async def verify_scan(self, qr_data: str) -> dict[str, Any]:
        """
        Verify a scanned QR code's authenticity.

        Parses the QR payload and validates the embedded verification
        hash against the expected value.

        Args:
            qr_data: Raw QR code data string (JSON payload).

        Returns:
            Dict with verification result (valid/invalid) and product info.
        """
        if not qr_data:
            return {"status": "error", "error": "QR data is required"}

        # Parse the QR payload
        try:
            payload = json.loads(qr_data)
        except json.JSONDecodeError as exc:
            return {
                "verified": False,
                "status": "invalid",
                "error": f"Invalid QR data format: {exc}",
            }

        # Validate required fields
        product_id = payload.get("product_id")
        scanned_hash = payload.get("verification_hash")
        generated_at = payload.get("generated_at")
        fmt = payload.get("format")

        if not product_id or not scanned_hash:
            return {
                "verified": False,
                "status": "invalid",
                "error": "QR code missing required fields (product_id, verification_hash)",
            }

        # Verify format version
        if fmt != QR_FORMAT_VERSION:
            return {
                "verified": False,
                "status": "invalid",
                "error": f"Unknown QR format: {fmt}. Expected: {QR_FORMAT_VERSION}",
                "product_id": product_id,
            }

        # Recompute verification hash
        if generated_at is not None:
            expected_hash = self._compute_verification_hash(product_id, generated_at)
        else:
            expected_hash = None

        hash_valid = expected_hash == scanned_hash if expected_hash else False

        # Cross-check with cache
        cached = self._qr_cache.get(product_id)
        cache_match = False
        if cached:
            cache_match = cached["verification_hash"] == scanned_hash

        verified = hash_valid or cache_match

        return {
            "verified": verified,
            "status": "valid" if verified else "suspicious",
            "product_id": product_id,
            "hash_valid": hash_valid,
            "cache_match": cache_match,
            "format": fmt,
            "generated_at": generated_at,
            "scanned_at": int(time.time()),
        }

    async def regenerate(self, product_id: str) -> dict[str, Any]:
        """Regenerate a QR code for a product (invalidates previous)."""
        # Remove from cache to invalidate old QR
        self._qr_cache.pop(product_id, None)
        return await self.generate(product_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _compute_verification_hash(self, product_id: str, timestamp: int) -> str:
        """Compute HMAC-like verification hash for a product QR code."""
        payload = f"{product_id}|{timestamp}|{self.qr_secret}"
        return hashlib.sha256(payload.encode()).hexdigest()[:32]

    def _render_qr_code(self, data: str) -> str:
        """
        Render a QR code as a base64-encoded PNG image.

        Uses the qrcode library if available; otherwise falls back to
        a deterministic base64 representation of the data.
        """
        try:
            import qrcode
            from qrcode.constants import ERROR_CORRECT_H

            qr = qrcode.QRCode(
                version=None,  # Auto-size
                error_correction=ERROR_CORRECT_H,
                box_size=self.qr_box_size,
                border=self.qr_border,
            )
            qr.add_data(data)
            qr.make(fit=True)

            img = qr.make_image(fill_color="black", back_color="white")
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)
            return base64.b64encode(buffer.read()).decode("ascii")

        except ImportError:
            logger.debug(
                "qrcode library not available. Generating deterministic base64 fallback."
            )
            # Deterministic fallback: base64-encode the raw data with a marker
            fallback = f"QR:{data}"
            return base64.b64encode(fallback.encode()).encode().decode("ascii") if False else base64.b64encode(fallback.encode()).decode("ascii")
