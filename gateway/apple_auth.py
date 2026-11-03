"""P1-8: Sign in with Apple — server-side identity-token verification.

The iOS app sends Apple's ``identityToken`` (a JWT signed by Apple). We verify
it against Apple's published JWKS: RS256 signature, ``iss`` == Apple, ``aud`` ==
our bundle id, and ``exp``. That half is real and is what this module does.

TOKEN REVOCATION IS NOT IMPLEMENTED — this line used to read "only
performed when those credentials are configured; otherwise local data is still
deleted and revocation is skipped with a WARNING", which described a
two-branch behaviour with one branch. No client-secret JWT is built anywhere
in this tree, nothing posts to ``https://appleid.apple.com/auth/revoke``, and
``handle_account_delete`` deletes the account's local data and answers 200
whether or not ``auth.apple.{team_id,key_id,private_key_p8}`` are filled in.
"Only performed when configured" was vacuously true because it is never
performed. The operator is now told so on BOTH paths, because silence is the
shape a working revocation would also have.

What it would take, so the gap is a task and not a mystery: Apple's
``/auth/revoke`` takes a refresh or access token, and the only way to get one
is to exchange the sign-in ``authorizationCode`` at ``/auth/token``. The iOS
client already sends that code (``MTRXAPIClient.authenticateWithApple``) and
``handle_apple_auth`` discards it. Building this means exchanging the code at
sign-in and STORING the user's Apple refresh token server-side until deletion
— a new stored secret with its own schema and threat model.

Consequence while it is missing: App Store 5.1.1(v) is unmet and a deleted
account's Apple token stays live.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
# There was an APPLE_REVOKE_URL here with zero callers. A module-level endpoint
# constant reads as a capability the module has; this one was the whole of the
# revocation. The URL lives in the module docstring, where it is a note about
# work owed rather than a definition pretending to be reached.
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
    """Whether the operator has FILLED IN the revocation credentials.

    Configured is not performed: nothing in this tree revokes an Apple token
    (see the module docstring). This predicate exists so the deletion path can
    tell the operator which of the two gaps they are looking at — credentials
    absent, or credentials present and the code that would use them missing.
    """
    auth = ((config or {}).get("auth") or {}).get("apple") or {}
    return bool(auth.get("team_id") and auth.get("key_id") and auth.get("private_key_p8"))
