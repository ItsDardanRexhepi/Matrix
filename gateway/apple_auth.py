"""P1-8: Sign in with Apple — server-side identity-token verification and
(credential-gated) token revocation for account deletion.

The iOS app sends Apple's ``identityToken`` (a JWT signed by Apple). We verify
it against Apple's published JWKS: RS256 signature, ``iss`` == Apple, ``aud`` ==
our bundle id, and ``exp``. Revocation on account deletion needs a client-secret
JWT signed with the team's ``.p8`` — only performed when those credentials are
configured; otherwise local data is still deleted and revocation is skipped with
a WARNING.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_REVOKE_URL = "https://appleid.apple.com/auth/revoke"
_JWKS_TTL_SECONDS = 3600


class AppleAuthError(Exception):
    """Identity-token verification failed (generic — no internal detail leaks)."""


class AppleAuthNotConfigured(Exception):
    """auth.apple.bundle_id is unset — the route must fail closed (503)."""


class AppleJWKSCache:
    """Fetches and TTL-caches Apple's JWKS. ``fetcher`` is injectable for tests."""

    def __init__(self, fetcher=None, ttl: float = _JWKS_TTL_SECONDS) -> None:
        self._fetcher = fetcher or _default_fetch_jwks
        self._ttl = ttl
        self._keys: dict[str, Any] = {}
        self._fetched_at: float = 0.0

    async def get_key(self, kid: str, *, now: float):
        if not self._keys or (now - self._fetched_at) > self._ttl:
            raw = await self._fetcher()
            self._keys = {k["kid"]: k for k in raw.get("keys", [])}
            self._fetched_at = now
        return self._keys.get(kid)


async def _default_fetch_jwks() -> dict:
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.get(APPLE_JWKS_URL, timeout=aiohttp.ClientTimeout(total=10)) as r:
            return await r.json()


def apple_bundle_id(config: dict) -> str:
    auth = ((config or {}).get("auth") or {}).get("apple") or {}
    return str(auth.get("bundle_id", "")).strip()


async def verify_apple_identity_token(
    identity_token: str,
    *,
    config: dict,
    jwks_cache: AppleJWKSCache,
    now: float | None = None,
) -> dict:
    """Verify Apple's identity token; return its claims or raise.

    Fail-closed: if bundle_id is unconfigured we NEVER verify against a wildcard
    audience — the caller returns 503.
    """
    bundle_id = apple_bundle_id(config)
    if not bundle_id:
        raise AppleAuthNotConfigured()

    try:
        import jwt
        from jwt.algorithms import RSAAlgorithm
    except Exception as exc:  # PyJWT / cryptography missing
        raise AppleAuthError("jwt library unavailable") from exc

    now = time.time() if now is None else now
    try:
        header = jwt.get_unverified_header(identity_token)
    except Exception as exc:
        raise AppleAuthError("malformed token") from exc

    kid = header.get("kid")
    jwk = await jwks_cache.get_key(kid, now=now)
    if jwk is None:
        raise AppleAuthError("unknown signing key")

    try:
        public_key = RSAAlgorithm.from_jwk(jwk)
        claims = jwt.decode(
            identity_token,
            public_key,
            algorithms=["RS256"],
            audience=bundle_id,
            issuer=APPLE_ISSUER,
            options={"require": ["exp", "iss", "aud"]},
        )
    except Exception as exc:
        raise AppleAuthError("token verification failed") from exc
    return claims


def apple_revocation_configured(config: dict) -> bool:
    auth = ((config or {}).get("auth") or {}).get("apple") or {}
    return bool(auth.get("team_id") and auth.get("key_id") and auth.get("private_key_p8"))
