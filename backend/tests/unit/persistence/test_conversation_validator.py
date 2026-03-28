"""Tests for backend.persistence.conversation.conversation_validator."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.persistence.conversation.conversation_validator import (
    ConversationAccessDenied,
    ConversationValidator,
    create_conversation_validator,
)


# ── ConversationAccessDenied ──────────────────────────────────────────


class TestConversationAccessDenied:
    def test_is_exception(self):
        exc = ConversationAccessDenied("nope")
        assert isinstance(exc, Exception)

    def test_message_preserved(self):
        exc = ConversationAccessDenied("access denied for user X")
        assert "access denied for user X" in str(exc)


# ── ConversationValidator.__init__ ────────────────────────────────────


class TestConversationValidatorInit:
    def test_explicit_mode_permissive(self):
        v = ConversationValidator(mode="permissive")
        assert v._mode == "permissive"

    def test_explicit_mode_strict(self):
        v = ConversationValidator(mode="strict")
        assert v._mode == "strict"

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("FORGE_VALIDATION_MODE", "strict")
        v = ConversationValidator()
        assert v._mode == "strict"

    def test_env_var_permissive(self, monkeypatch):
        monkeypatch.setenv("FORGE_VALIDATION_MODE", "permissive")
        v = ConversationValidator()
        assert v._mode == "permissive"

    def test_env_var_invalid_falls_to_config(self, monkeypatch):
        monkeypatch.setenv("FORGE_VALIDATION_MODE", "bogus")
        mock_config = MagicMock()
        mock_config.security.validation_mode = "strict"
        with patch(
            "backend.persistence.conversation.conversation_validator.load_forge_config",
            return_value=mock_config,
        ):
            v = ConversationValidator()
            assert v._mode == "strict"

    def test_fallback_default_permissive(self, monkeypatch):
        monkeypatch.delenv("FORGE_VALIDATION_MODE", raising=False)
        with patch(
            "backend.persistence.conversation.conversation_validator.load_forge_config",
            side_effect=RuntimeError("no config"),
        ):
            v = ConversationValidator()
            assert v._mode == "permissive"


# ── _extract_user_id ──────────────────────────────────────────────────


class TestExtractUserId:
    def test_returns_none_by_default(self):
        v = ConversationValidator(mode="permissive")
        assert v._extract_user_id("Bearer token") is None

    def test_returns_none_for_none_header(self):
        v = ConversationValidator(mode="permissive")
        assert v._extract_user_id(None) is None


# ── validate (permissive) ────────────────────────────────────────────


class TestValidatePermissive:
    @pytest.fixture
    def validator(self):
        return ConversationValidator(mode="permissive")

    async def test_permissive_creates_metadata_when_missing(self, validator):
        mock_meta = MagicMock()
        mock_meta.user_id = None
        validator._ensure_metadata_exists = AsyncMock(return_value=mock_meta)

        result = await validator.validate("conv-1", "", None)
        # Anonymous: same id as REST (`get_current_user_id`, e.g. oss_user)
        assert result == "oss_user"
        validator._ensure_metadata_exists.assert_awaited_once_with("conv-1", "oss_user")

    async def test_permissive_returns_extracted_user_id(self, validator):
        mock_meta = MagicMock()
        validator._ensure_metadata_exists = AsyncMock(return_value=mock_meta)
        validator._extract_user_id = MagicMock(return_value="user-42")

        result = await validator.validate("conv-1", "", "Bearer tok")
        assert result == "user-42"
        validator._ensure_metadata_exists.assert_awaited_once_with("conv-1", "user-42")


# ── validate (strict) ────────────────────────────────────────────────


class TestValidateStrict:
    @pytest.fixture
    def validator(self):
        return ConversationValidator(mode="strict")

    async def test_strict_anonymous_raises(self, validator):
        with pytest.raises(ConversationAccessDenied, match="Anonymous access"):
            await validator.validate("conv-1", "", None)

    async def test_strict_calls_validate_strict(self, validator):
        validator._extract_user_id = MagicMock(return_value="user-1")
        validator._validate_strict = AsyncMock(return_value="user-1")

        result = await validator.validate("conv-1", "", "Bearer tok")
        assert result == "user-1"


# ── _validate_strict ──────────────────────────────────────────────────


class TestValidateStrictInternal:
    async def test_none_user_id_raises(self):
        v = ConversationValidator(mode="strict")
        with pytest.raises(ConversationAccessDenied, match="Anonymous"):
            await v._validate_strict("conv-1", None)

    async def test_creates_metadata_on_first_access(self):
        v = ConversationValidator(mode="strict")
        mock_store = AsyncMock()
        mock_store.get_metadata = AsyncMock(side_effect=FileNotFoundError)
        created_meta = MagicMock()
        created_meta.user_id = "user-5"
        cast(Any, v)._create_metadata = AsyncMock(return_value=created_meta)

        mock_config = MagicMock()
        mock_server_config = MagicMock()

        with (
            patch(
                "backend.persistence.conversation.conversation_validator.load_forge_config",
                return_value=mock_config,
            ),
            patch(
                "backend.persistence.conversation.conversation_validator.ServerConfig",
                return_value=mock_server_config,
            ),
            patch(
                "backend.persistence.conversation.conversation_validator.get_impl",
            ) as mock_get_impl,
        ):
            mock_cls = AsyncMock()
            mock_cls.get_instance = AsyncMock(return_value=mock_store)
            mock_get_impl.return_value = mock_cls

            result = await v._validate_strict("conv-1", "user-5")
            assert result == "user-5"

    async def test_owner_mismatch_raises(self):
        v = ConversationValidator(mode="strict")
        mock_store = AsyncMock()
        existing_meta = MagicMock()
        existing_meta.user_id = "other-user"
        mock_store.get_metadata = AsyncMock(return_value=existing_meta)

        mock_config = MagicMock()
        mock_server_config = MagicMock()

        with (
            patch(
                "backend.persistence.conversation.conversation_validator.load_forge_config",
                return_value=mock_config,
            ),
            patch(
                "backend.persistence.conversation.conversation_validator.ServerConfig",
                return_value=mock_server_config,
            ),
            patch(
                "backend.persistence.conversation.conversation_validator.get_impl",
            ) as mock_get_impl,
        ):
            mock_cls = AsyncMock()
            mock_cls.get_instance = AsyncMock(return_value=mock_store)
            mock_get_impl.return_value = mock_cls

            with pytest.raises(ConversationAccessDenied, match="does not own"):
                await v._validate_strict("conv-1", "user-5")


# ── _create_metadata ──────────────────────────────────────────────────


class TestCreateMetadata:
    async def test_creates_and_returns_metadata(self):
        mock_store = AsyncMock()
        expected_meta = MagicMock()
        mock_store.save_metadata = AsyncMock()
        mock_store.get_metadata = AsyncMock(return_value=expected_meta)

        result = await ConversationValidator._create_metadata(
            mock_store, "conv-42", "user-1"
        )
        assert result == expected_meta
        mock_store.save_metadata.assert_awaited_once()
        saved = mock_store.save_metadata.call_args[0][0]
        assert saved.conversation_id == "conv-42"
        assert saved.user_id == "user-1"


# ── create_conversation_validator factory ─────────────────────────────


class TestCreateConversationValidatorFactory:
    def test_returns_validator_instance(self):
        with patch(
            "backend.persistence.conversation.conversation_validator.get_impl",
            return_value=ConversationValidator,
        ):
            v = create_conversation_validator()
            assert isinstance(v, ConversationValidator)

    def test_uses_env_var_class(self, monkeypatch):
        monkeypatch.setenv(
            "FORGE_CONVERSATION_VALIDATOR_CLS",
            "backend.persistence.conversation.conversation_validator.ConversationValidator",
        )
        with patch(
            "backend.persistence.conversation.conversation_validator.get_impl",
            return_value=ConversationValidator,
        ) as mock_impl:
            create_conversation_validator()
            mock_impl.assert_called_once()
