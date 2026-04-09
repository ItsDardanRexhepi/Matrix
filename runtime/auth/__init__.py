"""Authentication utilities for 0pnMatrx runtime."""

from __future__ import annotations

# SIWE depends on optional packages (eth_account). Import lazily so the
# rest of the package — notably the SQLite-backed session store — is
# usable in environments where eth_account isn't installed (e.g. local
# tests that don't touch the wallet flow).
try:
    from runtime.auth.siwe import (  # noqa: F401
        generate_nonce,
        build_siwe_message,
        verify_signature,
        create_session_token,
    )

    __all__ = [
        "generate_nonce",
        "build_siwe_message",
        "verify_signature",
        "create_session_token",
    ]
except ImportError:
    __all__ = []
