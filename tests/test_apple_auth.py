"""P1-8: Sign in with Apple identity-token verification.

Verifies against a locally-generated RSA keypair with a mocked JWKS fetch
(no network). Covers: valid token accepted, wrong-aud rejected, unconfigured
bundle_id fails closed (503-signal via AppleAuthNotConfigured).
"""

import json
import time

import pytest

jwt = pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from gateway.apple_auth import (
    APPLE_ISSUER, AppleJWKSCache, AppleAuthError, AppleAuthNotConfigured,
    verify_apple_identity_token,
)

BUNDLE = "com.opnmatrx.mtrx"


def _keypair_and_jwks(kid="test-kid"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    pub_jwk["kid"] = kid
    pub_jwk["alg"] = "RS256"
    pub_jwk["use"] = "sig"
    return key, {"keys": [pub_jwk]}


def _make_token(key, *, aud=BUNDLE, iss=APPLE_ISSUER, sub="apple-user-123",
                exp_delta=3600, kid="test-kid"):
    now = int(time.time())
    return jwt.encode(
        {"iss": iss, "aud": aud, "sub": sub, "iat": now, "exp": now + exp_delta},
        key, algorithm="RS256", headers={"kid": kid},
    )


def _cache(jwks):
    async def fetcher():
        return jwks
    return AppleJWKSCache(fetcher=fetcher)


@pytest.mark.asyncio
async def test_valid_token_accepted():
    key, jwks = _keypair_and_jwks()
    token = _make_token(key)
    claims = await verify_apple_identity_token(
        token, config={"auth": {"apple": {"bundle_id": BUNDLE}}}, jwks_cache=_cache(jwks))
    assert claims["sub"] == "apple-user-123"


@pytest.mark.asyncio
async def test_wrong_audience_rejected():
    key, jwks = _keypair_and_jwks()
    token = _make_token(key, aud="com.someone.else")
    with pytest.raises(AppleAuthError):
        await verify_apple_identity_token(
            token, config={"auth": {"apple": {"bundle_id": BUNDLE}}}, jwks_cache=_cache(jwks))


@pytest.mark.asyncio
async def test_unconfigured_bundle_id_fails_closed():
    key, jwks = _keypair_and_jwks()
    token = _make_token(key)
    with pytest.raises(AppleAuthNotConfigured):
        await verify_apple_identity_token(
            token, config={"auth": {"apple": {}}}, jwks_cache=_cache(jwks))


@pytest.mark.asyncio
async def test_expired_token_rejected():
    key, jwks = _keypair_and_jwks()
    token = _make_token(key, exp_delta=-10)
    with pytest.raises(AppleAuthError):
        await verify_apple_identity_token(
            token, config={"auth": {"apple": {"bundle_id": BUNDLE}}}, jwks_cache=_cache(jwks))
