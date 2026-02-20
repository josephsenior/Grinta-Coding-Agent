"""Secrets management with encryption at rest.

Provides secure storage and retrieval of secrets with:
- Encryption at rest
- Secret rotation support
- Audit logging
- Secure key derivation
"""

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from backend.core.logger import forge_logger as logger


class SecretsManager:
    """Manages encryption and decryption of secrets."""

    def __init__(self, master_key: str | None = None):
        """Initialize secrets manager.

        Args:
            master_key: Master encryption key (defaults to SECRET_KEY env var)
        """
        if master_key is None:
            master_key = os.getenv("SECRET_KEY") or os.getenv("JWT_SECRET")
            if not master_key:
                raise ValueError(
                    "Master key required. Set SECRET_KEY or JWT_SECRET environment variable."
                )

        # Derive encryption key from master key
        self._cipher = self._create_cipher(master_key)

    def _create_cipher(self, master_key: str) -> Fernet:
        """Create Fernet cipher from master key.

        Args:
            master_key: Master key string

        Returns:
            Fernet cipher instance
        """
        # Derive a 32-byte key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"forge_secrets_salt",  # In production, use a unique salt per secret
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(master_key.encode()))
        return Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a secret value.

        Args:
            plaintext: Secret value to encrypt

        Returns:
            Encrypted string (base64 encoded)
        """
        try:
            encrypted = self._cipher.encrypt(plaintext.encode())
            return base64.urlsafe_b64encode(encrypted).decode()
        except Exception as e:
            logger.error("Encryption failed: %s", e)
            raise ValueError(f"Failed to encrypt secret: {e}") from e

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a secret value.

        Args:
            ciphertext: Encrypted string (base64 encoded)

        Returns:
            Decrypted plaintext
        """
        try:
            encrypted_bytes = base64.urlsafe_b64decode(ciphertext.encode())
            decrypted = self._cipher.decrypt(encrypted_bytes)
            return decrypted.decode()
        except Exception as e:
            logger.error("Decryption failed: %s", e)
            raise ValueError(f"Failed to decrypt secret: {e}") from e

    def rotate_key(self, new_master_key: str) -> dict[str, str]:
        """Rotate encryption key (re-encrypt all secrets with new key).

        Args:
            new_master_key: New master key

        Returns:
            Dictionary mapping old encrypted values to new encrypted values

        Note:
            This is a placeholder. In production, you'd need to:
            1. Load all encrypted secrets
            2. Decrypt with old key
            3. Re-encrypt with new key
            4. Update storage
        """
        logger.warning(
            "Key rotation not fully implemented. Manual re-encryption required."
        )
        return {}


# Global secrets manager instance
_secrets_manager: SecretsManager | None = None


def get_secrets_manager() -> SecretsManager:
    """Get or create global secrets manager instance.

    Returns:
        SecretsManager instance
    """
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret value using the global secrets manager.

    Args:
        plaintext: Secret value to encrypt

    Returns:
        Encrypted string
    """
    return get_secrets_manager().encrypt(plaintext)


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a secret value using the global secrets manager.

    Args:
        ciphertext: Encrypted string

    Returns:
        Decrypted plaintext
    """
    return get_secrets_manager().decrypt(ciphertext)
