"""Phase 3: App Store server-side IAP verification (monetization server).

Verifies App Store Server JWS payloads — the ``signedTransaction`` the app
ships after a purchase, and the ``signedPayload`` App Store Server
Notifications V2 posts to our webhook. Verification is the full chain:

1. The JWS header's ``x5c`` chain must terminate at a PINNED trusted root
   (Apple Root CA - G3, bundled at ``gateway/certs/AppleRootCA-G3.pem``);
   every link's signature, validity window, and basic constraints are checked.
2. The JWS signature itself must verify against the leaf certificate's
   P-256 key, with the algorithm pinned to ES256 (alg-confusion rejected).
3. The decoded payload's ``bundleId`` must equal the configured bundle id.

Trust comes ONLY from the pinned root — the x5c chain is attacker-supplied
bytes until it is proven to terminate there. Tier decisions come ONLY from
our own product map (``classify_product``): a payload can never name its own
tier, and unknown/consumable product ids never map to one.

Fail-closed: no ``iap.bundle_id`` or no trusted roots -> IAPNotConfigured
(the routes answer 503) — never a verified claim, never a granted tier.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# Apple marker OID present on App Store receipt/transaction signing leaves.
APPLE_LEAF_MARKER_OID = "1.2.840.113635.100.6.11.1"

_BUNDLED_ROOT_PATH = os.path.join(os.path.dirname(__file__), "certs",
                                  "AppleRootCA-G3.pem")
_MAX_JWS_BYTES = 64 * 1024
_MAX_CHAIN_LEN = 5

#: product id -> (product_type, tier-or-None). The ONLY source of tier truth.
#: The $0.99 solitaire do-over Consumable is accepted and recorded but maps to
#: no tier — a consumable purchase can never escalate to Pro/Enterprise.
DEFAULT_PRODUCTS: dict[str, tuple[str, str | None]] = {
    "com.opnmatrx.mtrx.pro.monthly": ("subscription", "pro"),
    "com.opnmatrx.mtrx.enterprise.monthly": ("subscription", "enterprise"),
    "com.opnmatrx.mtrx.solitaire.redos5": ("consumable", None),
}


class IAPError(Exception):
    """JWS verification failed (generic — no internal detail leaks)."""


class IAPNotConfigured(Exception):
    """iap.bundle_id / trusted roots unset — routes must fail closed (503)."""


# ── Config ──────────────────────────────────────────────────────────

def iap_config(config: dict) -> dict:
    return ((config or {}).get("iap") or {})


def iap_bundle_id(config: dict) -> str:
    return str(iap_config(config).get("bundle_id", "")).strip()


def iap_environment(config: dict) -> str:
    """Optional 'Production'/'Sandbox' restriction; '' accepts either."""
    return str(iap_config(config).get("environment", "")).strip()


def require_apple_oids(config: dict) -> bool:
    """Leaf-marker OID check. ON by default; test fixture chains (self-signed,
    no Apple OIDs) turn it off explicitly alongside their own trusted root."""
    return bool(iap_config(config).get("require_apple_oids", True))


def product_map(config: dict) -> dict[str, tuple[str, str | None]]:
    """DEFAULT_PRODUCTS plus any ``iap.products`` config additions
    ({product_id: {"type": ..., "tier": ...}})."""
    merged = dict(DEFAULT_PRODUCTS)
    for pid, spec in (iap_config(config).get("products") or {}).items():
        if isinstance(spec, dict):
            tier = spec.get("tier") or None
            merged[str(pid)] = (str(spec.get("type", "unknown")), tier)
    return merged


def classify_product(product_id: str, config: dict) -> tuple[str, str | None]:
    """(product_type, tier|None) for a product id. Unknown ids are recorded as
    ("unknown", None) — NEVER a tier. Tier truth lives here, not in payloads."""
    return product_map(config).get(product_id, ("unknown", None))


def trusted_roots_pem(config: dict) -> list[bytes]:
    """Trusted root certificates: ``iap.trusted_roots_pem`` (list of PEM
    strings — used by tests) or the bundled Apple Root CA - G3."""
    override = iap_config(config).get("trusted_roots_pem")
    if override:
        return [p.encode() if isinstance(p, str) else bytes(p) for p in override]
    try:
        with open(_BUNDLED_ROOT_PATH, "rb") as fh:
            return [fh.read()]
    except OSError:
        return []


def iap_configured(config: dict) -> bool:
    return bool(iap_bundle_id(config)) and bool(trusted_roots_pem(config))


# ── JWS verification ────────────────────────────────────────────────

def _b64url_decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(segment + pad)
    except (binascii.Error, ValueError) as exc:
        raise IAPError("malformed JWS segment") from exc


def _load_chain(header: dict) -> list[Any]:
    from cryptography import x509

    x5c = header.get("x5c")
    if not isinstance(x5c, list) or not (1 <= len(x5c) <= _MAX_CHAIN_LEN):
        raise IAPError("missing or invalid x5c chain")
    certs = []
    for entry in x5c:
        try:
            certs.append(x509.load_der_x509_certificate(
                base64.b64decode(str(entry), validate=True)))
        except Exception as exc:
            raise IAPError("malformed certificate in x5c") from exc
    return certs


def _check_validity(cert: Any, now: float) -> None:
    from datetime import datetime, timezone

    t = datetime.fromtimestamp(now, tz=timezone.utc)
    if t < cert.not_valid_before_utc or t > cert.not_valid_after_utc:
        raise IAPError("certificate outside validity window")


def _is_ca(cert: Any) -> bool:
    from cryptography import x509

    try:
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        return bool(bc.value.ca)
    except x509.ExtensionNotFound:
        return False


def _has_oid(cert: Any, dotted: str) -> bool:
    return any(ext.oid.dotted_string == dotted for ext in cert.extensions)


def _verify_chain(certs: list[Any], roots_pem: list[bytes], *, now: float,
                  check_oids: bool) -> Any:
    """Validate the x5c chain against the pinned roots; return the leaf cert.

    Every adjacent pair must be a real signature link, every cert must be
    inside its validity window, intermediates must be CA certs and the leaf
    must not be, and the chain must END at a pinned root — either the last
    x5c cert IS a trusted root (byte-equal) or it is directly issued by one.
    """
    from cryptography import x509

    roots = []
    for pem in roots_pem:
        try:
            roots.append(x509.load_pem_x509_certificate(pem))
        except Exception as exc:
            raise IAPError("bad trusted root configuration") from exc
    if not roots:
        raise IAPNotConfigured()

    for cert in certs:
        _check_validity(cert, now)

    leaf = certs[0]
    if _is_ca(leaf):
        raise IAPError("leaf certificate must not be a CA")
    for issuer_candidate in certs[1:]:
        if not _is_ca(issuer_candidate):
            raise IAPError("intermediate certificate must be a CA")

    # Signature links within the presented chain.
    for child, issuer in zip(certs, certs[1:]):
        try:
            child.verify_directly_issued_by(issuer)
        except Exception as exc:
            raise IAPError("broken certificate chain") from exc

    # Anchor: the last presented cert is a pinned root, or issued by one.
    last = certs[-1]
    root_ders = {r.public_bytes(_der_encoding()) for r in roots}
    if last.public_bytes(_der_encoding()) not in root_ders:
        anchored = False
        for root in roots:
            try:
                last.verify_directly_issued_by(root)
                _check_validity(root, now)
                anchored = True
                break
            except Exception:
                continue
        if not anchored:
            raise IAPError("chain does not terminate at a trusted root")

    if check_oids and not _has_oid(leaf, APPLE_LEAF_MARKER_OID):
        raise IAPError("leaf lacks the Apple App Store marker extension")
    return leaf


def _der_encoding():
    from cryptography.hazmat.primitives.serialization import Encoding
    return Encoding.DER


def verify_signed_payload(jws: str, *, config: dict,
                          now: float | None = None) -> dict:
    """Verify an App Store Server JWS and return its decoded payload.

    Raises IAPNotConfigured when bundle id / roots are unset (route -> 503)
    and IAPError on ANY verification failure (route -> 401). The payload's
    bundleId is checked by the caller via check_bundle() — ASN nests it under
    data.bundleId while transactions carry it top-level.
    """
    if not iap_bundle_id(config):
        raise IAPNotConfigured()
    roots = trusted_roots_pem(config)
    if not roots:
        raise IAPNotConfigured()

    if not isinstance(jws, str) or not jws or len(jws) > _MAX_JWS_BYTES:
        raise IAPError("invalid JWS")
    parts = jws.split(".")
    if len(parts) != 3:
        raise IAPError("invalid JWS")

    try:
        header = json.loads(_b64url_decode(parts[0]))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise IAPError("malformed JWS header") from exc

    # Algorithm pinned BEFORE any cryptography: only ES256, never a downgrade.
    if header.get("alg") != "ES256":
        raise IAPError("unexpected JWS algorithm")

    now = time.time() if now is None else now
    certs = _load_chain(header)
    leaf = _verify_chain(certs, roots, now=now,
                         check_oids=require_apple_oids(config))

    from cryptography.hazmat.primitives.asymmetric import ec

    public_key = leaf.public_key()
    if not isinstance(public_key, ec.EllipticCurvePublicKey) or \
            not isinstance(public_key.curve, ec.SECP256R1):
        raise IAPError("leaf key is not P-256")

    try:
        import jwt
        payload = jwt.decode(jws, key=public_key, algorithms=["ES256"],
                             options={"verify_aud": False})
    except Exception as exc:
        raise IAPError("JWS signature verification failed") from exc
    if not isinstance(payload, dict):
        raise IAPError("unexpected JWS payload")
    return payload


def check_bundle(payload_bundle_id: Any, config: dict) -> None:
    """The payload's bundleId must equal the configured one, exactly."""
    expected = iap_bundle_id(config)
    if not expected:
        raise IAPNotConfigured()
    if not isinstance(payload_bundle_id, str) or payload_bundle_id != expected:
        raise IAPError("bundle id mismatch")


def check_environment(payload_env: Any, config: dict) -> None:
    """When iap.environment is configured, the payload must match it."""
    expected = iap_environment(config)
    if expected and payload_env != expected:
        raise IAPError("environment mismatch")


# ── Payload helpers ─────────────────────────────────────────────────

def ms_to_epoch(value: Any) -> float:
    """Apple dates are milliseconds since epoch; absent/garbage -> 0.0."""
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return 0.0


def transaction_fields(payload: dict) -> dict[str, Any]:
    """Normalize a JWSTransactionDecodedPayload into the fields we store."""
    return {
        "transaction_id": str(payload.get("transactionId", "")),
        "original_transaction_id": str(payload.get("originalTransactionId", "")),
        "product_id": str(payload.get("productId", "")),
        "bundle_id": payload.get("bundleId"),
        "environment": str(payload.get("environment", "")),
        "purchase_date": ms_to_epoch(payload.get("purchaseDate")),
        "expires_date": ms_to_epoch(payload.get("expiresDate")),
        "quantity": int(payload.get("quantity") or 1),
        "revocation_date": ms_to_epoch(payload.get("revocationDate")),
    }
