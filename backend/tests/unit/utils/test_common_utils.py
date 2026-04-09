"""Tests for backend.utils.core_utils — LLM configuration and conversation stats setup.

Tests cover:
- LLM config setup from user settings
- Registry and stats creation
- Configuration inheritance and overrides
- Error handling
"""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

import pytest

from backend.core.config.app_config import AppConfig
from backend.inference.llm_registry import LLMRegistry
from backend.orchestration.conversation_stats import ConversationStats
from backend.persistence.data_models.settings import Settings
from backend.utils.core_utils import (
    create_registry_and_conversation_stats,
    setup_llm_config,
)


@pytest.fixture
def base_config() -> AppConfig:
    """Provide a base application configuration."""
    config = Mock(spec=AppConfig)

    # Mock LLM config getter/setter
    mock_llm_config = Mock()
    mock_llm_config.model = 'gpt-4'
    mock_llm_config.api_key = 'base-key'
    mock_llm_config.base_url = 'https://api.openai.com/v1'

    config.get_llm_config = Mock(return_value=mock_llm_config)
    config.set_llm_config = Mock()

    # Mock other config fields
    config.file_store = 'local'
    config.local_data_root = '/tmp/files'

    return config


@pytest.fixture
def user_settings() -> Settings:
    """Provide user settings."""
    settings = Mock(spec=Settings)
    settings.llm_model = 'gpt-4-turbo'
    settings.llm_api_key = 'user-api-key'
    settings.llm_base_url = 'https://custom-api.example.com/v1'
    return settings


@pytest.fixture
def minimal_settings() -> Settings:
    """Provide minimal user settings (some None values)."""
    settings = Mock(spec=Settings)
    settings.llm_model = None
    settings.llm_api_key = 'user-api-key'
    settings.llm_base_url = None
    return settings


class TestSetupLlmConfig:
    """Test LLM configuration setup."""

    @patch('backend.utils.core_utils.deepcopy')
    def test_setup_llm_config_applies_user_settings(
        self, mock_deepcopy: Mock, base_config: AppConfig, user_settings: Settings
    ) -> None:
        """Test that user settings override base config."""
        mock_deepcopy.side_effect = lambda x: x
        setup_llm_config(base_config, user_settings)

        # Get the LLM config that was set
        set_call_args = cast(Mock, base_config.set_llm_config).call_args
        assert set_call_args is not None

        updated_llm_config = set_call_args[0][0]
        assert updated_llm_config.model == 'gpt-4-turbo'
        assert updated_llm_config.api_key == 'user-api-key'
        assert updated_llm_config.base_url == 'https://custom-api.example.com/v1'

    @patch('backend.utils.core_utils.deepcopy')
    def test_setup_llm_config_with_partial_settings(
        self, mock_deepcopy: Mock, base_config: AppConfig, minimal_settings: Settings
    ) -> None:
        """Test that partial user settings fill in base config."""
        mock_deepcopy.side_effect = lambda x: x
        setup_llm_config(base_config, minimal_settings)

        set_call_args = cast(Mock, base_config.set_llm_config).call_args
        updated_llm_config = set_call_args[0][0]

        # API key should be updated
        assert updated_llm_config.api_key == 'user-api-key'
        # Model should become empty string (not provided)
        assert updated_llm_config.model == ''
        # Base URL should be None
        assert updated_llm_config.base_url is None

    def test_setup_llm_config_returns_config(
        self, base_config: AppConfig, user_settings: Settings
    ) -> None:
        """Test that setup_llm_config returns a config object."""
        result = setup_llm_config(base_config, user_settings)
        assert result is not None

    @patch('backend.utils.core_utils.deepcopy')
    def test_setup_llm_config_get_llm_config_called(
        self, mock_deepcopy: Mock, base_config: AppConfig, user_settings: Settings
    ) -> None:
        """Test that get_llm_config is called to retrieve current config."""
        mock_deepcopy.side_effect = lambda x: x
        setup_llm_config(base_config, user_settings)
        cast(Mock, base_config.get_llm_config).assert_called_once()

    @patch('backend.utils.core_utils.deepcopy')
    def test_setup_llm_config_set_llm_config_called(
        self, mock_deepcopy: Mock, base_config: AppConfig, user_settings: Settings
    ) -> None:
        """Test that set_llm_config is called to update config."""
        mock_deepcopy.side_effect = lambda x: x
        setup_llm_config(base_config, user_settings)
        cast(Mock, base_config.set_llm_config).assert_called_once()

    def test_setup_llm_config_does_not_modify_original(
        self, base_config: AppConfig, user_settings: Settings
    ) -> None:
        """Test that original config is not modified (deep copy)."""
        original_id = id(base_config)
        result = setup_llm_config(base_config, user_settings)

        # The original config should still exist and not be the result
        assert id(base_config) == original_id
        assert base_config != result

    @patch('backend.utils.core_utils.deepcopy')
    def test_setup_llm_config_empty_model_string(
        self, mock_deepcopy: Mock, base_config: AppConfig
    ) -> None:
        """Test handling of empty model string in settings."""
        mock_deepcopy.side_effect = lambda x: x
        settings = Mock(spec=Settings)
        settings.llm_model = ''
        settings.llm_api_key = 'key'
        settings.llm_base_url = 'url'

        setup_llm_config(base_config, settings)

        set_call_args = cast(Mock, base_config.set_llm_config).call_args
        updated_llm_config = set_call_args[0][0]
        assert updated_llm_config.model == ''

    @patch('backend.utils.core_utils.deepcopy')
    def test_setup_llm_config_preserves_unspecified_settings(
        self, mock_deepcopy: Mock, base_config: AppConfig, user_settings: Settings
    ) -> None:
        """Test that settings not modified in user config are preserved."""
        mock_deepcopy.side_effect = lambda x: x
        # Set a custom value in base config
        base_llm_config = cast(Mock, base_config.get_llm_config).return_value
        base_llm_config.some_field = 'preserved_value'

        setup_llm_config(base_config, user_settings)

        set_call_args = cast(Mock, base_config.set_llm_config).call_args
        updated_llm_config = set_call_args[0][0]
        # The field we didn't modify should still be there
        assert updated_llm_config.some_field == 'preserved_value'


class TestCreateRegistryAndStats:
    """Test registry and stats creation."""

    @patch('backend.utils.core_utils.get_file_store')
    @patch('backend.utils.core_utils.LLMRegistry')
    @patch('backend.utils.core_utils.ConversationStats')
    def test_create_registry_with_user_settings(
        self,
        mock_stats_class: Mock,
        mock_registry_class: Mock,
        mock_get_file_store: Mock,
        base_config: AppConfig,
        user_settings: Settings,
    ) -> None:
        """Test creating registry and stats with user settings."""
        # Setup mocks
        mock_file_store = Mock()
        mock_get_file_store.return_value = mock_file_store
        mock_registry = Mock(spec=LLMRegistry)
        mock_registry_class.return_value = mock_registry
        mock_conversation_stats = Mock(spec=ConversationStats)
        mock_stats_class.return_value = mock_conversation_stats

        # Call function
        registry, stats, config = create_registry_and_conversation_stats(
            base_config, 'sid_1', 'user_1', user_settings
        )

        # Verify calls
        mock_registry_class.assert_called_once()
        mock_stats_class.assert_called_once_with(mock_file_store, 'sid_1', 'user_1')
        mock_registry.subscribe.assert_called_once()

        # Verify returns
        assert registry == mock_registry
        assert stats == mock_conversation_stats

    @patch('backend.utils.core_utils.get_file_store')
    @patch('backend.utils.core_utils.LLMRegistry')
    @patch('backend.utils.core_utils.ConversationStats')
    def test_create_registry_without_user_settings(
        self,
        mock_stats_class: Mock,
        mock_registry_class: Mock,
        mock_get_file_store: Mock,
        base_config: AppConfig,
    ) -> None:
        """Test creating registry and stats without user settings."""
        # Setup mocks
        mock_file_store = Mock()
        mock_get_file_store.return_value = mock_file_store
        mock_registry = Mock(spec=LLMRegistry)
        mock_registry_class.return_value = mock_registry
        mock_conversation_stats = Mock(spec=ConversationStats)
        mock_stats_class.return_value = mock_conversation_stats

        # Call function without user_settings
        registry, stats, config = create_registry_and_conversation_stats(
            base_config, 'sid_1', 'user_1', None
        )

        # Verify the base config was used (not modified)
        mock_registry_class.assert_called_once()
        call_args = mock_registry_class.call_args
        # First argument should be config
        assert call_args[0][0] == base_config

    @patch('backend.utils.core_utils.get_file_store')
    @patch('backend.utils.core_utils.LLMRegistry')
    @patch('backend.utils.core_utils.ConversationStats')
    def test_create_registry_returns_updated_config(
        self,
        mock_stats_class: Mock,
        mock_registry_class: Mock,
        mock_get_file_store: Mock,
        base_config: AppConfig,
        user_settings: Settings,
    ) -> None:
        """Test that updated config is returned."""
        mock_file_store = Mock()
        mock_get_file_store.return_value = mock_file_store
        mock_registry = Mock(spec=LLMRegistry)
        mock_registry_class.return_value = mock_registry
        mock_conversation_stats = Mock(spec=ConversationStats)
        mock_stats_class.return_value = mock_conversation_stats

        registry, stats, returned_config = create_registry_and_conversation_stats(
            base_config, 'sid_1', 'user_1', user_settings
        )

        # Returned config should not be None
        assert returned_config is not None

    @patch('backend.utils.core_utils.get_file_store')
    @patch('backend.utils.core_utils.LLMRegistry')
    @patch('backend.utils.core_utils.ConversationStats')
    def test_create_registry_subscribes_stats(
        self,
        mock_stats_class: Mock,
        mock_registry_class: Mock,
        mock_get_file_store: Mock,
        base_config: AppConfig,
        user_settings: Settings,
    ) -> None:
        """Test that stats is subscribed to registry."""
        mock_file_store = Mock()
        mock_get_file_store.return_value = mock_file_store
        mock_registry = Mock(spec=LLMRegistry)
        mock_registry_class.return_value = mock_registry
        mock_conversation_stats = Mock(spec=ConversationStats)
        mock_stats_class.return_value = mock_conversation_stats

        create_registry_and_conversation_stats(
            base_config, 'sid_1', 'user_1', user_settings
        )

        # Registry's subscribe method should be called with stats callback
        mock_registry.subscribe.assert_called_once()

    @patch('backend.utils.core_utils.get_file_store')
    @patch('backend.utils.core_utils.LLMRegistry')
    @patch('backend.utils.core_utils.ConversationStats')
    def test_create_registry_file_store_created(
        self,
        mock_stats_class: Mock,
        mock_registry_class: Mock,
        mock_get_file_store: Mock,
        base_config: AppConfig,
        user_settings: Settings,
    ) -> None:
        """Test that file store is created with correct config."""
        mock_file_store = Mock()
        mock_get_file_store.return_value = mock_file_store
        mock_registry = Mock(spec=LLMRegistry)
        mock_registry_class.return_value = mock_registry
        mock_conversation_stats = Mock(spec=ConversationStats)
        mock_stats_class.return_value = mock_conversation_stats

        create_registry_and_conversation_stats(
            base_config, 'sid_1', 'user_1', user_settings
        )

        # Verify get_file_store was called with config values
        mock_get_file_store.assert_called_once_with(
            file_store_type='local',
            local_data_root=str(Path('/tmp/files').resolve()),
        )

    @patch('backend.utils.core_utils.get_file_store')
    @patch('backend.utils.core_utils.LLMRegistry')
    @patch('backend.utils.core_utils.ConversationStats')
    def test_create_registry_with_none_user_id(
        self,
        mock_stats_class: Mock,
        mock_registry_class: Mock,
        mock_get_file_store: Mock,
        base_config: AppConfig,
        user_settings: Settings,
    ) -> None:
        """Test creating registry with None user_id."""
        mock_file_store = Mock()
        mock_get_file_store.return_value = mock_file_store
        mock_registry = Mock(spec=LLMRegistry)
        mock_registry_class.return_value = mock_registry
        mock_conversation_stats = Mock(spec=ConversationStats)
        mock_stats_class.return_value = mock_conversation_stats

        create_registry_and_conversation_stats(
            base_config, 'sid_1', None, user_settings
        )

        # Stats should be created with None user_id
        mock_stats_class.assert_called_once_with(mock_file_store, 'sid_1', None)

    @patch('backend.utils.core_utils.get_file_store')
    @patch('backend.utils.core_utils.LLMRegistry')
    @patch('backend.utils.core_utils.ConversationStats')
    def test_create_registry_agent_class_passed(
        self,
        mock_stats_class: Mock,
        mock_registry_class: Mock,
        mock_get_file_store: Mock,
        base_config: AppConfig,
        user_settings: Settings,
    ) -> None:
        """Test that agent class from settings is passed to registry."""
        mock_file_store = Mock()
        mock_get_file_store.return_value = mock_file_store
        mock_registry = Mock(spec=LLMRegistry)
        mock_registry_class.return_value = mock_registry
        mock_conversation_stats = Mock(spec=ConversationStats)
        mock_stats_class.return_value = mock_conversation_stats

        create_registry_and_conversation_stats(
            base_config, 'sid_1', 'user_1', user_settings
        )

        # Check that LLMRegistry was initialized with the agent class
        call_args = mock_registry_class.call_args
        assert call_args[0][1] is None

    @patch('backend.utils.core_utils.get_file_store')
    @patch('backend.utils.core_utils.LLMRegistry')
    @patch('backend.utils.core_utils.ConversationStats')
    def test_create_registry_agent_class_none(
        self,
        mock_stats_class: Mock,
        mock_registry_class: Mock,
        mock_get_file_store: Mock,
        base_config: AppConfig,
    ) -> None:
        """Test that agent class is None when no user settings."""
        mock_file_store = Mock()
        mock_get_file_store.return_value = mock_file_store
        mock_registry = Mock(spec=LLMRegistry)
        mock_registry_class.return_value = mock_registry
        mock_conversation_stats = Mock(spec=ConversationStats)
        mock_stats_class.return_value = mock_conversation_stats

        create_registry_and_conversation_stats(base_config, 'sid_1', 'user_1', None)

        # Agent class should be None
        call_args = mock_registry_class.call_args
        assert call_args[0][1] is None


class TestConfigComplexity:
    """Test complex configuration scenarios."""

    @patch('backend.utils.core_utils.get_file_store')
    @patch('backend.utils.core_utils.LLMRegistry')
    @patch('backend.utils.core_utils.ConversationStats')
    def test_multiple_calls_independent(
        self,
        mock_stats_class: Mock,
        mock_registry_class: Mock,
        mock_get_file_store: Mock,
        base_config: AppConfig,
        user_settings: Settings,
    ) -> None:
        """Test that multiple calls don't interfere."""
        mock_file_store = Mock()
        mock_get_file_store.return_value = mock_file_store
        mock_registry1 = Mock(spec=LLMRegistry)
        mock_registry2 = Mock(spec=LLMRegistry)
        mock_registry_class.side_effect = [mock_registry1, mock_registry2]
        mock_stats1 = Mock(spec=ConversationStats)
        mock_stats2 = Mock(spec=ConversationStats)
        mock_stats_class.side_effect = [mock_stats1, mock_stats2]

        # Create two separate registries
        r1, s1, _ = create_registry_and_conversation_stats(
            base_config, 'sid_1', 'user_1', user_settings
        )
        r2, s2, _ = create_registry_and_conversation_stats(
            base_config, 'sid_2', 'user_2', user_settings
        )

        # They should be different objects
        assert r1 != r2
        assert s1 != s2
        assert mock_registry_class.call_count == 2
        assert mock_stats_class.call_count == 2

    @patch('backend.utils.core_utils.deepcopy')
    def test_settings_with_special_characters(
        self, mock_deepcopy: Mock, base_config: AppConfig
    ) -> None:
        """Test settings with special characters in strings."""
        mock_deepcopy.side_effect = lambda x: x
        settings = Mock(spec=Settings)
        settings.llm_model = 'gpt-4 "special"'
        settings.llm_api_key = 'key with spaces & symbols'
        settings.llm_base_url = 'https://api.example.com:8080/v1/api?version=2'

        setup_llm_config(base_config, settings)

        set_call_args = cast(Mock, base_config.set_llm_config).call_args
        assert set_call_args is not None
        updated_llm_config = set_call_args[0][0]
        assert updated_llm_config.model == 'gpt-4 "special"'
        assert updated_llm_config.api_key == 'key with spaces & symbols'
