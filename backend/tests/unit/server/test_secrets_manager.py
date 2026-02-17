"""Tests for backend.server.utils.secrets_manager module.

Targets the 0% (45 missed lines) coverage gap.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.server.utils.secrets_manager import SecretsManager


# ------------------------------------------------------------------
# SecretsManager init
# ------------------------------------------------------------------
class TestSecretsManagerInit:
    def test_init_with_explicit_key(self):
        sm = SecretsManager(master_key="my-secret-key-123")
        assert sm._cipher is not None

    def test_init_from_env_secret_key(self):
        with patch.dict("os.environ", {"SECRET_KEY": "env-key-456"}, clear=False):
            sm = SecretsManager()
            assert sm._cipher is not None

    def test_init_from_env_jwt_secret(self):
        with patch.dict(
            "os.environ", {"JWT_SECRET": "jwt-key-789"}, clear=False
        ):
            with patch.dict("os.environ", {}, clear=False):
                # Remove SECRET_KEY if present
                import os
                old = os.environ.pop("SECRET_KEY", None)
                try:
                    sm = SecretsManager()
                    assert sm._cipher is not None
                finally:
                    if old is not None:
                        os.environ["SECRET_KEY"] = old

    def test_init_no_key_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="Master key required"):
                SecretsManager()


# ------------------------------------------------------------------
# encrypt / decrypt round-trip
# ------------------------------------------------------------------
class TestEncryptDecrypt:
    def test_round_trip(self):
        sm = SecretsManager(master_key="test-round-trip-key")
        plaintext = "super-secret-password"
        encrypted = sm.encrypt(plaintext)
        assert encrypted != plaintext
        decrypted = sm.decrypt(encrypted)
        assert decrypted == plaintext

    def test_different_plaintexts(self):
        sm = SecretsManager(master_key="different-key")
        e1 = sm.encrypt("alpha")
        e2 = sm.encrypt("beta")
        assert e1 != e2
        assert sm.decrypt(e1) == "alpha"
        assert sm.decrypt(e2) == "beta"

    def test_same_plaintext_different_ciphertext(self):
        """Fernet is nondeterministic — same plaintext gives different ciphertext."""
        sm = SecretsManager(master_key="nondeterministic-key")
        e1 = sm.encrypt("same")
        e2 = sm.encrypt("same")
        # Fernet includes timestamp + IV, so ciphertexts should differ
        assert e1 != e2
        assert sm.decrypt(e1) == "same"
        assert sm.decrypt(e2) == "same"

    def test_empty_string(self):
        sm = SecretsManager(master_key="empty-test-key")
        encrypted = sm.encrypt("")
        decrypted = sm.decrypt(encrypted)
        assert decrypted == ""

    def test_unicode_content(self):
        sm = SecretsManager(master_key="unicode-key")
        plaintext = "Hello, World! 12345"
        encrypted = sm.encrypt(plaintext)
        assert sm.decrypt(encrypted) == plaintext

    def test_long_plaintext(self):
        sm = SecretsManager(master_key="long-content-key")
        plaintext = "a" * 10000
        encrypted = sm.encrypt(plaintext)
        assert sm.decrypt(encrypted) == plaintext


# ------------------------------------------------------------------
# decrypt errors
# ------------------------------------------------------------------
class TestDecryptErrors:
    def test_invalid_ciphertext_raises(self):
        sm = SecretsManager(master_key="error-key")
        with pytest.raises(ValueError, match="Failed to decrypt"):
            sm.decrypt("not-valid-base64-ciphertext!!!")

    def test_wrong_key_raises(self):
        sm1 = SecretsManager(master_key="key-one")
        sm2 = SecretsManager(master_key="key-two")
        encrypted = sm1.encrypt("secret")
        with pytest.raises(ValueError, match="Failed to decrypt"):
            sm2.decrypt(encrypted)


# ------------------------------------------------------------------
# rotate_key
# ------------------------------------------------------------------
class TestRotateKey:
    def test_rotate_key_placeholder(self):
        sm = SecretsManager(master_key="rotate-key")
        result = sm.rotate_key("new-key")
        assert result == {}


# ------------------------------------------------------------------
# Same key produces same cipher
# ------------------------------------------------------------------
class TestCipherDeterminism:
    def test_same_key_can_decrypt(self):
        sm1 = SecretsManager(master_key="shared-key")
        sm2 = SecretsManager(master_key="shared-key")
        encrypted = sm1.encrypt("cross-instance")
        assert sm2.decrypt(encrypted) == "cross-instance"
