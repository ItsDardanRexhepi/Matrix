from __future__ import annotations

"""
Config Encryption — protects sensitive values in openmatrix.config.json.

Uses Fernet symmetric encryption (from cryptography package) when available,
falls back to base64 obfuscation with a warning. Encryption key is derived
from OPENMATRIX_SECRET_KEY environment variable or generated on first use.

Usage:
    from runtime.config.encryption import ConfigEncryption

    enc = ConfigEncryption()
    encrypted = enc.encrypt("my-api-key")
    decrypted = enc.decrypt(encrypted)

Encrypted values are prefixed with "enc:" so the config loader can
detect and decrypt them automatically.
"""

import base64
import hashlib
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:"


class ConfigEncryption:
    """Encrypts and decrypts sensitive config values."""

    def __init__(self, key: str | None = None):
        self._key = key or os.environ.get("OPENMATRIX_SECRET_KEY", "")
        self._fernet = None

        if self._key:
            try:
                from cryptography.fernet import Fernet
                # Derive a 32-byte key from the user-provided key
                derived = hashlib.sha256(self._key.encode()).digest()
                fernet_key = base64.urlsafe_b64encode(derived)
                self._fernet = Fernet(fernet_key)
            except ImportError:
                logger.warning(
                    "cryptography package not installed. "
                    "Using base64 obfuscation (NOT secure). "
                    "Install with: pip install cryptography"
                )

    def encrypt(self, value: str) -> str:
        """Encrypt a value. Returns prefixed string."""
        if not value or value.startswith(ENC_PREFIX):
            return value
        if self._fernet:
            encrypted = self._fernet.encrypt(value.encode()).decode()
            return f"{ENC_PREFIX}{encrypted}"
        # Fallback: base64 obfuscation
        encoded = base64.b64encode(value.encode()).decode()
        return f"{ENC_PREFIX}b64:{encoded}"

    def decrypt(self, value: str) -> str:
        """Decrypt a prefixed value. Returns plain string."""
        if not isinstance(value, str) or not value.startswith(ENC_PREFIX):
            return value
        payload = value[len(ENC_PREFIX):]

        if payload.startswith("b64:"):
            # Base64 fallback
            return base64.b64decode(payload[4:]).decode()

        if self._fernet:
            try:
                return self._fernet.decrypt(payload.encode()).decode()
            except Exception as e:
                logger.error(f"Decryption failed: {e}")
                return value

        logger.warning("Cannot decrypt Fernet value without OPENMATRIX_SECRET_KEY")
        return value

    def is_encrypted(self, value: str) -> bool:
        return isinstance(value, str) and value.startswith(ENC_PREFIX)


# ─── Config loader with auto-decryption ──────────────────────────────────────

SENSITIVE_KEYS = {
    "api_key", "private_key", "secret", "password", "token",
    "paymaster_private_key", "platform_wallet_private_key",
}


def load_config_secure(path: str = "openmatrix.config.json") -> dict:
    """
    Load config and automatically decrypt any encrypted values.
    Sensitive keys are identified by name pattern matching.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    config = json.loads(config_path.read_text())
    enc = ConfigEncryption()

    def _decrypt_recursive(obj):
        if isinstance(obj, dict):
            return {k: _decrypt_recursive(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_decrypt_recursive(v) for v in obj]
        if isinstance(obj, str) and enc.is_encrypted(obj):
            return enc.decrypt(obj)
        return obj

    return _decrypt_recursive(config)


def encrypt_config_secrets(path: str = "openmatrix.config.json"):
    """
    Encrypt sensitive values in a config file in-place.
    Only encrypts values for keys matching SENSITIVE_KEYS patterns.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    config = json.loads(config_path.read_text())
    enc = ConfigEncryption()

    if not enc._key:
        logger.error(
            "Set OPENMATRIX_SECRET_KEY environment variable before encrypting. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
        return

    def _encrypt_recursive(obj, parent_key=""):
        if isinstance(obj, dict):
            return {
                k: _encrypt_recursive(v, k) for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_encrypt_recursive(v, parent_key) for v in obj]
        if isinstance(obj, str) and not enc.is_encrypted(obj):
            if any(sk in parent_key.lower() for sk in SENSITIVE_KEYS):
                if obj and not obj.startswith("YOUR_"):
                    return enc.encrypt(obj)
        return obj

    encrypted_config = _encrypt_recursive(config)
    config_path.write_text(json.dumps(encrypted_config, indent=2) + "\n")
    logger.info(f"Sensitive values encrypted in {path}")
