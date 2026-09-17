"""Tests for backend.persistence.data_models.settings — Settings model."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from pydantic import SecretStr

from backend.persistence.data_models.settings import (
    Settings,
)
from backend.persistence.data_models.user_secrets import UserSecrets


class TestSettingsDefaults:
    def test_empty_construction(self):
        s = Settings()
        assert s.language is None
        assert s.agent is None
        assert s.max_iterations is None
        assert s.llm_model is None
        assert s.llm_api_key is None
        assert s.enable_sound_notifications is False
        assert s.enable_proactive_conversation_starters is True
        assert s.enable_solvability_analysis is True
        assert s.mcp_config is None

    def test_custom_fields(self):
        s = Settings(
            language='en',
            agent='Orchestrator',
            max_iterations=50,
            llm_model='gpt-4',
            llm_provider='openai',
            llm_api_key=SecretStr('sk-test'),
        )
        assert s.language == 'en'
        assert s.agent == 'Orchestrator'
        assert s.llm_model == 'openai/gpt-4'
        assert s.llm_provider == 'openai'
        assert s.llm_api_key is not None
        assert s.llm_api_key.get_secret_value() == 'sk-test'

    def test_provider_inferred_from_prefixed_model(self):
        s = Settings(llm_model='groq/meta-llama/llama-4-scout')
        assert s.llm_provider == 'groq'
        assert s.llm_model == 'groq/meta-llama/llama-4-scout'

    def test_provider_normalized_preserves_cross_provider_model(self):
        s = Settings(llm_model='openai/gpt-4o', llm_provider='groq')
        assert s.llm_provider == 'groq'
        assert s.llm_model == 'openai/gpt-4o'

    def test_agent_name_is_stripped_not_rewritten(self):
        s = Settings(agent='  Orchestrator  ')
        assert s.agent == 'Orchestrator'

    def test_agent_aliases_are_not_mapped(self):
        s = Settings(agent='Orchestrator')
        assert s.agent == 'Orchestrator'

    def test_agent_none_or_empty(self):
        assert Settings(agent=None).agent is None
        assert Settings(agent='   ').agent is None

    def test_provider_none(self):
        assert Settings(llm_provider=None).llm_provider is None


class TestApiKeySerialization:
    def test_hidden_by_default(self):
        s = Settings(llm_api_key=SecretStr('sk-secret'))
        data = s.model_dump()
        assert 'sk-secret' not in str(data.get('llm_api_key', ''))

    def test_exposed_with_context(self):
        s = Settings(llm_api_key=SecretStr('sk-secret'))
        data = s.model_dump(context={'expose_secrets': True})
        assert data['llm_api_key'] == 'sk-secret'

    def test_none_api_key(self):
        s = Settings(llm_api_key=None)
        data = s.model_dump()
        assert data['llm_api_key'] is None


class TestValidateApiKey:
    def test_none(self):
        assert Settings._validate_api_key(None) is False

    def test_empty_secret(self):
        assert Settings._validate_api_key(SecretStr('')) is False

    def test_valid_secret(self):
        assert Settings._validate_api_key(SecretStr('sk-valid')) is True

    def test_plain_string(self):
        assert Settings._validate_api_key('sk-test') is True

    def test_empty_string(self):
        assert Settings._validate_api_key('') is True


class TestCheckExplicitLlmConfig:
    def test_no_llms_attr(self):
        config = MagicMock(spec=[])
        assert Settings._check_explicit_llm_config(config) is False

    def test_llms_not_dict(self):
        config = MagicMock()
        config.llms = 'not_a_dict'
        assert Settings._check_explicit_llm_config(config) is False

    def test_no_llm_key(self):
        config = MagicMock()
        config.llms = {}
        assert Settings._check_explicit_llm_config(config) is False

    def test_explicit_no_api_key(self):
        llm = MagicMock()
        llm.api_key = None
        config = MagicMock()
        config.llms = {'llm': llm}
        assert Settings._check_explicit_llm_config(config) is True

    def test_explicit_env_match(self):
        llm = MagicMock()
        llm.api_key = SecretStr('secret-123')
        config = MagicMock()
        config.llms = {'llm': llm}
        with patch.dict('os.environ', {'LLM_API_KEY': 'secret-123'}):
            assert Settings._check_explicit_llm_config(config) is True


class TestConvertProviderTokens:
    def test_non_dict_passthrough(self):
        assert Settings.convert_provider_tokens('string_data') == 'string_data'

    def test_convert_dict_with_tokens_and_custom_secrets(self):
        data = {
            'secrets_store': {
                'provider_tokens': {'openai': {'token': 'abc'}},
                'custom_secrets': {'my_key': 'val'},
            }
        }
        res = Settings.convert_provider_tokens(data)
        assert isinstance(res, dict)
        assert 'secret_store' in res
        store = res['secret_store']
        assert isinstance(store, UserSecrets)


class TestHasExplicitApiKey:
    def test_with_explicit_attr(self):
        config = MagicMock()
        config._has_explicit_api_key = True
        assert Settings._has_explicit_api_key(config) is True

    def test_fallback_api_key_attr(self):
        class DummyConfig:
            api_key = 'sk-dummy'

        assert Settings._has_explicit_api_key(DummyConfig()) is True

    def test_fallback_no_api_key(self):
        class DummyConfig:
            pass

        assert Settings._has_explicit_api_key(DummyConfig()) is False


class TestSettingsCache:
    def setup_method(self):
        Settings._reset_settings_cache()

    def teardown_method(self):
        Settings._reset_settings_cache()

    def test_reset_cache(self):
        import backend.persistence.data_models.settings as mod

        mod._settings_from_config_cache = Settings()
        mod._settings_from_config_cache_time = 999.0
        Settings._reset_settings_cache()
        assert getattr(mod, '_settings_from_config_cache') is None
        assert getattr(mod, '_settings_from_config_cache_time') == 0.0

    def test_cache_and_return_none(self):
        import backend.persistence.data_models.settings as mod

        result = Settings._cache_and_return_none(100.0)
        assert result is None
        assert mod._settings_from_config_cache is None
        assert mod._settings_from_config_cache_time == 100.0

    def test_get_cached_settings_fresh(self):
        s = Settings(language='en')
        now = time.time()
        Settings._cache_settings_result(s, now)
        cached = Settings._get_cached_settings(now + 1)
        assert cached == s

    def test_get_cached_settings_expired(self):
        s = Settings(language='en')
        now = time.time()
        Settings._cache_settings_result(s, now)
        cached = Settings._get_cached_settings(now + 1000)
        assert cached is None


class TestMergeWithConfigSettings:
    def test_merge_no_config_settings(self):
        s = Settings(language='fr')
        with patch.object(Settings, 'from_config', return_value=None):
            res = s.merge_with_config_settings()
            assert res == s

    def test_merge_config_with_mcp(self):
        from backend.core.config.mcp_config import MCPConfig

        s = Settings(language='fr')
        config_s = Settings(mcp_config=MCPConfig(servers=[]))
        with patch.object(Settings, 'from_config', return_value=config_s):
            res = s.merge_with_config_settings()
            assert res.mcp_config == config_s.mcp_config
