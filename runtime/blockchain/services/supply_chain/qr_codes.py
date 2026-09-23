"""
QRCodeGenerator -- generates and verifies QR codes for supply chain products.

QR encodes product_id + verification hash. Returns base64-encoded QR image
data. Verification scans validate the embedded hash against the registry.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import logging
import time
from typing import Any

from runtime.auth.constant_time import digests_equal
from runtime.config.validation import is_placeholder

logger = logging.getLogger(__name__)

# QR code version/format identifier
QR_FORMAT_VERSION = "the-matrix-sc-v1"

#: Secrets that are published, and therefore are not secrets. The first was
#: this module's own fallback: an operator who configured nothing got a working
#: verification hash keyed on a string printed in this repository, so anybody
#: holding the source could mint a code for a product that was never
#: registered. A deployment that copied the constant into its config is in the
#: same position, which is why the value is refused wherever it appears rather
#: than merely removed from the default.
_PUBLISHED_SECRETS: frozenset[str] = frozenset({
    "the-matrix-default-qr-secret",
})


def resolve_qr_secret(supply_chain_config: dict[str, Any]) -> str:
    """The configured QR secret, or "" when the operator has not chosen one.

    Empty, whitespace, a placeholder (`CHANGE-ME-...`, `YOUR_...`) and any
    published value all mean the same thing: nothing was chosen. They are
    collapsed here, once, so no caller has to remember the list.
    """
    raw = supply_chain_config.get("qr_secret", "")
    value = str(raw or "").strip()
    if not value or is_placeholder(value) or value in _PUBLISHED_SECRETS:
        return ""
    return value


#: The one refusal both halves return, so "not configured" reads identically
#: whether it stopped a code being issued or a code being trusted.
def _unconfigured(product_id: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": "not_configured",
        "error": ("supply_chain.qr_secret is not configured — this deployment "
                  "cannot issue or verify authenticity codes. Set a long random "
                  "per-deployment value (env: MATRIX_QR_SECRET)."),
    }
    if product_id:
        out["product_id"] = product_id
    return out


class QRCodeGenerator:
    """
    Generates and verifies QR codes for supply chain product tracking.

    Each QR code encodes a JSON payload with product_id, verification hash,
    and optional product data. The verification hash allows offline
    authenticity checks.

    THERE IS NO DEFAULT SECRET. `qr_secret` used to fall back to a constant
    written in this file, so a deployment that configured nothing still issued
    codes — signed with a value published to everyone. Without a configured
    secret both `generate` and `verify_scan` now refuse: no code is issued, and
    no scan is called valid. Authenticity that anybody can forge is worse than
    an honest "not configured", because it is believed.

    Config keys (under config["supply_chain"]):
        qr_secret       -- HMAC secret for verification hashes. REQUIRED; no
                           default. Placeholders count as unset.
        qr_box_size     -- QR code pixel box size (default 10)
        qr_border       -- QR code border size (default 4)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        sc = config.get("supply_chain", {}) or {}

        self.qr_secret: str = resolve_qr_secret(sc)
        self.qr_box_size: int = sc.get("qr_box_size", 10)
        self.qr_border: int = sc.get("qr_border", 4)

        # Cache of generated QR codes: product_id -> qr_data
        self._qr_cache: dict[str, dict[str, Any]] = {}

        if not self.qr_secret:
            logger.warning(
                "QRCodeGenerator: supply_chain.qr_secret is not configured — "
                "authenticity codes will be refused, not issued.")
        logger.info("QRCodeGenerator initialised.")

    @property
    def secret_configured(self) -> bool:
        """Did the operator choose a secret? The one question both halves ask."""
        return bool(self.qr_secret)

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

        if not self.secret_configured:
            return _unconfigured(product_id)

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

        # Nothing issued under a secret this deployment does not have can be
        # judged by it. `verified: False` alone would read as "we checked and
        # it is a forgery"; the status says which of the two this is (§CT).
        if not self.secret_configured:
            return {"verified": False, **_unconfigured()}

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

        # A hash is an ASCII hex string by construction. Anything else is a
        # malformed payload — `invalid`, not `suspicious` (compared and wrong)
        # — and is never handed to a constant-time compare, which raises
        # TypeError on a non-ASCII str: a `verification_hash` of "é" * 32 used
        # to come back as an exception where a wrong hash came back as
        # `verified: False`. No route reaches this yet; the first one must not
        # turn a bad scan into a 500.
        if not isinstance(scanned_hash, str) or not scanned_hash.isascii():
            return {
                "verified": False,
                "status": "invalid",
                "error": "verification_hash must be an ASCII string",
                "product_id": product_id,
            }
        # The id is text too. A JSON list or object here was hashed as its
        # repr and then raised TypeError as a cache key (unhashable); a number
        # was hashed as its digits and called `suspicious`. Not a string is
        # malformed. A string holding a lone surrogate (a JSON "\udcff") is a
        # string — it is hashed over its bytes (surrogatepass, below) and the
        # compare answers, as it does for any id the operator did not issue.
        if not isinstance(product_id, str):
            return {
                "verified": False,
                "status": "invalid",
                "error": "product_id must be a string",
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

        hash_valid = (
            digests_equal(expected_hash, scanned_hash)
            if expected_hash else False
        )

        # Cross-check with cache
        cached = self._qr_cache.get(product_id)
        cache_match = False
        if cached:
            cache_match = digests_equal(cached["verification_hash"], scanned_hash)

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
        """The verification hash: HMAC-SHA256(secret, "product_id|timestamp").

        It was `sha256("product_id|timestamp|secret")` under a docstring that
        called it HMAC — so the claim is now true rather than approximate. Only
        callable with a configured secret; both entry points refuse before they
        reach it.
        """
        # surrogatepass on both: the secret comes from os.environ and the id
        # from a JSON payload, and either may hold a lone surrogate; a bare
        # encode() raised UnicodeEncodeError out of verify_scan on the id.
        return hmac.new(
            self.qr_secret.encode("utf-8", "surrogatepass"),
            f"{product_id}|{timestamp}".encode("utf-8", "surrogatepass"),
            hashlib.sha256,
        ).hexdigest()[:32]

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
