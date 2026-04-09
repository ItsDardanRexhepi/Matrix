"""EIP-4361 Sign-In with Ethereum (SIWE) verification utilities.

Provides nonce generation, message building, signature verification,
and session token creation following the SIWE specification.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from eth_account import Account
from eth_account.messages import encode_defunct


def generate_nonce() -> str:
    """Generate a cryptographically secure nonce for SIWE challenges."""
    return secrets.token_urlsafe(16)


def build_siwe_message(
    address: str,
    nonce: str,
    domain: str,
    chain_id: int,
    uri: str,
) -> str:
    """Build an EIP-4361 compliant SIWE message string.

    Args:
        address: Ethereum wallet address (checksummed).
        nonce: Random nonce for replay protection.
        domain: The domain requesting the sign-in.
        chain_id: The EIP-155 chain ID.
        uri: The URI of the resource being accessed.

    Returns:
        A formatted EIP-4361 message ready for signing.
    """
    issued_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    message = (
        f"{domain} wants you to sign in with your Ethereum account:\n"
        f"{address}\n"
        f"\n"
        f"Sign in to 0pnMatrx\n"
        f"\n"
        f"URI: {uri}\n"
        f"Version: 1\n"
        f"Chain ID: {chain_id}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued_at}"
    )
    return message


def verify_signature(address: str, message: str, signature: str) -> bool:
    """Verify that *signature* was produced by *address* signing *message*.

    Uses ``eth_account.Account.recover_message`` with ``encode_defunct``
    to recover the signer address and compares it (case-insensitively)
    against the claimed *address*.

    Returns:
        True if the recovered address matches, False otherwise.
    """
    try:
        signable = encode_defunct(text=message)
        recovered = Account.recover_message(signable, signature=signature)
        return recovered.lower() == address.lower()
    except Exception:
        return False


def create_session_token() -> str:
    """Create a cryptographically secure session token."""
    return secrets.token_urlsafe(32)
