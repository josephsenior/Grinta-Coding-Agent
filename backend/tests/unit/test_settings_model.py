"""Tests for backend.storage.data_models.settings — Settings model."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr, ValidationError

from backend.storage.data_models.settings import (
    Settings,
    _settings_from_config_cache,
)


class TestSettingsDefaults:
    def test_empty_construction(self):
        s = Settings()
        assert s.language is None
        assert s.agent is None
        assert s.max_iterations is None
        assert s.llm_model is None
        assert s.llm_api_key is None
        assert s.enable_default_condenser is True
        assert s.enable_sound_notifications is False
        assert s.enable_proactive_conversation_starters is True
        assert s.enable_solvability_analysis is True
        assert s.mcp_config is None
        assert s.condenser_max_size is None

    def test_custom_fields(self):
        s = Settings(
            language="en",
            agent="CodeAct",
            max_iterations=50,
            llm_model="gpt-4",
            llm_api_key=SecretStr("sk-test"),
        )
        assert s.language == "en"
        assert s.agent == "CodeAct"
        assert s.llm_model == "gpt-4"
        assert s.llm_api_key.get_secret_value() == "sk-test"


class TestCondenserMaxSize:
    def test_none_allowed(self):
        s = Settings(condenser_max_size=None)
        assert s.condenser_max_size is None

    def test_valid_value(self):
        s = Settings(condenser_max_size=20)
        assert s.condenser_max_size == 20

    def test_large_value(self):
        s = Settings(condenser_max_size=1000)
        assert s.condenser_max_size == 1000

    def test_below_20_rejected(self):
        with pytest.raises(ValidationError, match="at least 20"):
            Settings(condenser_max_size=19)

    def test_zero_rejected(self):
        with pytest.raises(ValidationError, match="at least 20"):
            Settings(condenser_max_size=0)


class TestKnowledgeBaseProperty:
    def test_default_kb_settings(self):
        s = Settings()
        kb = s.knowledge_base
        assert kb.enabled is True
        assert kb.search_top_k == 5
        assert kb.relevance_threshold == 0.7
        assert kb.auto_search is True
        assert kb.search_strategy == "hybrid"
        assert kb.active_collection_ids == []

    def test_custom_kb_settings(self):
        s = Settings(
            kb_enabled=False,
            kb_active_collection_ids=["c1"],
            kb_search_top_k=10,
            kb_relevance_threshold=0.5,
            kb_auto_search=False,
            kb_search_strategy="semantic",
        )
        kb = s.knowledge_base
        assert kb.enabled is False
        assert kb.search_top_k == 10
        assert kb.active_collection_ids == ["c1"]


class TestApiKeySerialization:
    def test_hidden_by_default(self):
        s = Settings(llm_api_key=SecretStr("sk-secret"))
        data = s.model_dump()
        assert "sk-secret" not in str(data.get("llm_api_key", ""))

    def test_exposed_with_context(self):
        s = Settings(llm_api_key=SecretStr("sk-secret"))
        data = s.model_dump(context={"expose_secrets": True})
        assert data["llm_api_key"] == "sk-secret"

    def test_none_api_key(self):
        s = Settings(llm_api_key=None)
        data = s.model_dump()
        assert data["llm_api_key"] is None


class TestValidateApiKey:
    def test_none(self):
        assert Settings._validate_api_key(None) is False

    def test_empty_secret(self):
        assert Settings._validate_api_key(SecretStr("")) is False

    def test_valid_secret(self):
        assert Settings._validate_api_key(SecretStr("sk-valid")) is True

    def test_plain_string(self):
        assert Settings._validate_api_key("sk-test") is True

    def test_empty_string(self):
        # Plain empty string passes the try/except path and returns True
        # because it's not a SecretStr and bool("") catches are bypassed
        assert Settings._validate_api_key("") is True


class TestCheckExplicitLlmConfig:
    def test_no_llms_attr(self):
        config = MagicMock(spec=[])
        assert Settings._check_explicit_llm_config(config) is False

    def test_llms_not_dict(self):
        config = MagicMock()
        config.llms = "not_a_dict"
        assert Settings._check_explicit_llm_config(config) is False

    def test_no_llm_key(self):
        config = MagicMock()
        config.llms = {}
        assert Settings._check_explicit_llm_config(config) is False

    def test_explicit_no_api_key(self):
        llm = MagicMock()
        llm.api_key = None
        config = MagicMock()
        config.llms = {"llm": llm}
        assert Settings._check_explicit_llm_config(config) is True


class TestSettingsCache:
    def setup_method(self):
        Settings._reset_settings_cache()

    def teardown_method(self):
        Settings._reset_settings_cache()

    def test_reset_cache(self):
        import backend.storage.data_models.settings as mod

        mod._settings_from_config_cache = Settings()
        mod._settings_from_config_cache_time = 999.0
        Settings._reset_settings_cache()
        assert mod._settings_from_config_cache is None
        assert mod._settings_from_config_cache_time == 0.0

    def test_cache_and_return_none(self):
        import backend.storage.data_models.settings as mod

        result = Settings._cache_and_return_none(100.0)
        assert result is None
        assert mod._settings_from_config_cache is None
        assert mod._settings_from_config_cache_time == 100.0
