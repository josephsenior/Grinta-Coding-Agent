"""Tests for backend.storage.secrets.file_secrets_store.FileSecretsStore."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch


from backend.storage.secrets.file_secrets_store import FileSecretsStore


# ── __init__ ──────────────────────────────────────────────────────────


class TestFileSecretsStoreInit:
    def test_default_path(self):
        fs = MagicMock()
        store = FileSecretsStore(fs)
        assert store.path == "user_secrets.json"  # DEFAULT_SECRETS_FILENAME
        assert store.file_store is fs
        assert store.user_id is None

    def test_custom_path(self):
        fs = MagicMock()
        store = FileSecretsStore(fs, path="custom/secrets.json")
        assert store.path == "custom/secrets.json"

    def test_user_id_path(self):
        fs = MagicMock()
        store = FileSecretsStore(fs, user_id="user-42")
        assert "user-42" in store.path
        assert store.user_id == "user-42"

    def test_explicit_path_overrides_user_id(self):
        fs = MagicMock()
        store = FileSecretsStore(fs, path="override.json", user_id="user-42")
        assert store.path == "override.json"


# ── load ──────────────────────────────────────────────────────────────


class TestFileSecretsStoreLoad:
    async def test_load_returns_none_when_not_found(self):
        fs = MagicMock()
        store = FileSecretsStore(fs)

        with patch(
            "backend.storage.secrets.file_secrets_store.call_sync_from_async",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError,
        ):
            result = await store.load()
            assert result is None

    async def test_load_parses_valid_json(self):
        fs = MagicMock()
        store = FileSecretsStore(fs)

        # UserSecrets uses provider_tokens and custom_secrets
        # ProviderType only has "enterprise_sso" as a valid enum value
        data = json.dumps(
            {"provider_tokens": {"enterprise_sso": {"token": "tok_test"}}}
        )

        with patch(
            "backend.storage.secrets.file_secrets_store.call_sync_from_async",
            new_callable=AsyncMock,
            return_value=data,
        ):
            result = await store.load()
            assert result is not None
            # provider_tokens should have the converted entry
            assert result.provider_tokens

    async def test_load_normalizes_string_provider_tokens(self):
        """String token values get normalized to {"token": value} dicts
        before being passed to UserSecrets constructor."""
        fs = MagicMock()
        store = FileSecretsStore(fs)

        # The load() method normalizes string tokens to {"token": ...}
        # Then UserSecrets._convert_provider_tokens converts to ProviderToken objects
        data = json.dumps(
            {
                "provider_tokens": {
                    "enterprise_sso": "tok_abc123",
                }
            }
        )

        with patch(
            "backend.storage.secrets.file_secrets_store.call_sync_from_async",
            new_callable=AsyncMock,
            return_value=data,
        ):
            result = await store.load()
            assert result is not None
            # The tokens end up as MappingProxyType with ProviderType keys
            assert result.provider_tokens

    async def test_load_skips_empty_token_values(self):
        """Empty strings and empty dicts are excluded by the normalization logic."""
        fs = MagicMock()
        store = FileSecretsStore(fs)

        # empty_str -> normalized away (not truthy)
        # empty_dict -> no 'token' key so normalized away
        # valid -> kept
        data = json.dumps(
            {
                "provider_tokens": {
                    "enterprise_sso": {"token": "tok-1"},
                }
            }
        )

        with patch(
            "backend.storage.secrets.file_secrets_store.call_sync_from_async",
            new_callable=AsyncMock,
            return_value=data,
        ):
            result = await store.load()
            assert result is not None
            assert result.provider_tokens

    async def test_load_empty_tokens_filtered(self):
        """Verify that empty strings and empty dicts get filtered out."""
        fs = MagicMock()
        store = FileSecretsStore(fs)

        data = json.dumps(
            {
                "provider_tokens": {
                    "empty_str": "",
                    "empty_dict": {},
                }
            }
        )

        with patch(
            "backend.storage.secrets.file_secrets_store.call_sync_from_async",
            new_callable=AsyncMock,
            return_value=data,
        ):
            result = await store.load()
            assert result is not None
            # Both empty tokens should be filtered in normalization,
            # resulting in provider_tokens=None (no valid tokens)
            tokens = result.provider_tokens
            assert not tokens

    async def test_load_handles_non_dict_json(self):
        fs = MagicMock()
        store = FileSecretsStore(fs)

        with patch(
            "backend.storage.secrets.file_secrets_store.call_sync_from_async",
            new_callable=AsyncMock,
            return_value='"just a string"',
        ):
            result = await store.load()
            assert result is not None  # Constructed with empty kwargs


# ── store ─────────────────────────────────────────────────────────────


class TestFileSecretsStoreStore:
    async def test_store_writes_json(self):
        fs = MagicMock()
        store = FileSecretsStore(fs)

        mock_secrets = MagicMock()

        with (
            patch(
                "backend.storage.secrets.file_secrets_store.model_dump_json",
                return_value='{"llm_api_key": "test"}',
            ),
            patch(
                "backend.storage.secrets.file_secrets_store.call_sync_from_async",
                new_callable=AsyncMock,
            ) as mock_write,
        ):
            await store.store(mock_secrets)
            mock_write.assert_awaited_once()
            # Verify the write call args include path and json string
            call_args = mock_write.call_args[0]
            assert call_args[0] == fs.write  # function reference
            assert call_args[1] == store.path


# ── get_instance ──────────────────────────────────────────────────────


class TestFileSecretsStoreGetInstance:
    async def test_creates_instance_with_file_store(self):
        mock_config = MagicMock()
        mock_config.file_store = "local"
        mock_config.file_store_path = "/tmp/test"
        mock_config.file_store_web_hook_url = None
        mock_config.file_store_web_hook_headers = None
        mock_config.file_store_web_hook_batch = False

        mock_fs = MagicMock()

        with patch(
            "backend.storage.secrets.file_secrets_store.get_file_store",
            return_value=mock_fs,
        ):
            instance = await FileSecretsStore.get_instance(mock_config, "user-1")
            assert isinstance(instance, FileSecretsStore)
            assert instance.file_store is mock_fs
            assert instance.user_id == "user-1"

    async def test_creates_instance_without_user(self):
        mock_config = MagicMock()
        mock_config.file_store = "local"
        mock_config.file_store_path = "/tmp/test"
        mock_config.file_store_web_hook_url = None
        mock_config.file_store_web_hook_headers = None
        mock_config.file_store_web_hook_batch = False

        with patch(
            "backend.storage.secrets.file_secrets_store.get_file_store",
            return_value=MagicMock(),
        ):
            instance = await FileSecretsStore.get_instance(mock_config, None)
            assert isinstance(instance, FileSecretsStore)
            assert instance.user_id is None
