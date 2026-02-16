"""Tests for backend.core.config.api_key_manager — provider detection + key validation."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from backend.core.config.api_key_manager import APIKeyManager


# ===================================================================
# _extract_provider
# ===================================================================

class TestExtractProvider:

    def setup_method(self):
        self.mgr = APIKeyManager()

    def test_empty_model_returns_unknown(self):
        assert self.mgr._extract_provider("") == "unknown"

    def test_openai_prefix(self):
        assert self.mgr._extract_provider("openai/gpt-4o") == "openai"

    def test_gpt_prefix(self):
        assert self.mgr._extract_provider("gpt-4") == "openai"

    def test_anthropic_prefix(self):
        assert self.mgr._extract_provider("anthropic/claude-3.5-sonnet") == "anthropic"

    def test_claude_prefix(self):
        assert self.mgr._extract_provider("claude-sonnet-4-20250514") == "anthropic"

    def test_google_prefix(self):
        assert self.mgr._extract_provider("google/gemini-pro") == "google"

    def test_gemini_prefix(self):
        assert self.mgr._extract_provider("gemini/1.5-pro") == "google"

    def test_xai_prefix(self):
        assert self.mgr._extract_provider("xai/grok-2") == "xai"

    def test_grok_prefix(self):
        assert self.mgr._extract_provider("grok-4-fast") == "xai"

    def test_keyword_match_gemini(self):
        assert self.mgr._extract_provider("some-gemini-model") == "google"

    def test_keyword_match_grok(self):
        assert self.mgr._extract_provider("some-grok-model") == "xai"

    def test_fallback_claude(self):
        assert self.mgr._extract_provider("my-claude-variant") == "anthropic"

    def test_fallback_gpt(self):
        assert self.mgr._extract_provider("my-gpt-variant") == "openai"

    def test_truly_unknown(self):
        assert self.mgr._extract_provider("mistral-large-2") == "unknown"


# ===================================================================
# _is_correct_provider_key
# ===================================================================

class TestIsCorrectProviderKey:

    def setup_method(self):
        self.mgr = APIKeyManager()

    def test_openai_key_correct(self):
        key = SecretStr("sk-abc123456789")
        assert self.mgr._is_correct_provider_key(key, "openai") is True

    def test_openai_key_wrong(self):
        key = SecretStr("AIzaSyBxxxxxx")
        assert self.mgr._is_correct_provider_key(key, "openai") is False

    def test_anthropic_key_correct(self):
        key = SecretStr("sk-ant-api03-xxxx")
        assert self.mgr._is_correct_provider_key(key, "anthropic") is True

    def test_anthropic_key_wrong(self):
        key = SecretStr("sk-openai-xxxx")
        assert self.mgr._is_correct_provider_key(key, "anthropic") is False

    def test_google_key_correct(self):
        key = SecretStr("AIzaSyBxxxxxxxxxxxxxxx")
        assert self.mgr._is_correct_provider_key(key, "google") is True

    def test_xai_key_correct(self):
        key = SecretStr("xai-abc123456")
        assert self.mgr._is_correct_provider_key(key, "xai") is True

    def test_unknown_provider_always_correct(self):
        key = SecretStr("anything")
        assert self.mgr._is_correct_provider_key(key, "custom_provider") is True


# ===================================================================
# _check_prefix_match
# ===================================================================

class TestCheckPrefixMatch:

    def setup_method(self):
        self.mgr = APIKeyManager()

    def test_openai_slash(self):
        assert self.mgr._check_prefix_match("openai/gpt-4", "openai/gpt-4") == "openai"

    def test_no_match(self):
        assert self.mgr._check_prefix_match("mistral-large", "mistral-large") is None


# ===================================================================
# _check_keyword_match
# ===================================================================

class TestCheckKeywordMatch:

    def setup_method(self):
        self.mgr = APIKeyManager()

    def test_gemini_keyword(self):
        assert self.mgr._check_keyword_match("some-gemini-model") == "google"

    def test_grok_keyword(self):
        assert self.mgr._check_keyword_match("some-grok-model") == "xai"

    def test_no_keyword_match(self):
        assert self.mgr._check_keyword_match("mistral-large-2") is None


# ===================================================================
# get_api_key_for_model
# ===================================================================

class TestGetApiKeyForModel:

    def test_returns_correct_provided_key(self):
        mgr = APIKeyManager()
        key = SecretStr("sk-correct123456789")
        result = mgr.get_api_key_for_model("gpt-4", provided_key=key)
        assert result is not None
        assert result.get_secret_value() == "sk-correct123456789"

    def test_falls_back_to_substantial_key(self):
        mgr = APIKeyManager()
        # Key that doesn't match provider pattern but is "substantial" (>10 chars)
        key = SecretStr("AIzaSyBxxxxxxxxxxxxxxx")  # Google key for OpenAI model
        result = mgr.get_api_key_for_model("gpt-4", provided_key=key)
        assert result is not None  # Falls back

    def test_env_var_fallback(self):
        mgr = APIKeyManager()
        with patch.object(mgr, "_get_provider_key_from_env", return_value="env-key-123"):
            result = mgr.get_api_key_for_model("gpt-4")
            assert result is not None
            assert result.get_secret_value() == "env-key-123"

    def test_stored_key_fallback(self):
        mgr = APIKeyManager()
        mgr.provider_api_keys["openai"] = SecretStr("stored-key")
        with patch.object(mgr, "_get_provider_key_from_env", return_value=None):
            result = mgr.get_api_key_for_model("gpt-4")
            assert result is not None
            assert result.get_secret_value() == "stored-key"

    def test_no_key_found(self):
        mgr = APIKeyManager()
        with patch.object(mgr, "_get_provider_key_from_env", return_value=None):
            result = mgr.get_api_key_for_model("gpt-4")
            assert result is None


# ===================================================================
# set_api_key
# ===================================================================

class TestSetApiKey:

    def test_set_api_key(self):
        mgr = APIKeyManager()
        key = SecretStr("sk-test")
        mgr.set_api_key("gpt-4", key)
        assert "openai" in mgr.provider_api_keys
        assert mgr.provider_api_keys["openai"].get_secret_value() == "sk-test"


# ===================================================================
# set_environment_variables
# ===================================================================

class TestSetEnvironmentVariables:

    def test_suppress_env_export(self):
        mgr = APIKeyManager(suppress_env_export=True)
        # Should return early without setting anything
        with patch.dict(os.environ, {}, clear=False):
            mgr.set_environment_variables("gpt-4", SecretStr("sk-test"))
            # LLM_API_KEY should NOT have been set
            assert os.environ.get("LLM_API_KEY_TEST_MARKER") is None

    def test_sets_env_vars(self):
        mgr = APIKeyManager()
        key = SecretStr("sk-test-env-var")
        with patch("backend.core.config.api_key_manager.provider_config_manager") as pcm:
            pcm.get_provider_config.return_value = MagicMock(
                required_params=["api_key"],
                env_var="OPENAI_API_KEY",
            )
            pcm.get_environment_variable.return_value = "OPENAI_API_KEY"
            pcm.validate_api_key_format.return_value = None
            with patch.dict(os.environ, {}, clear=False):
                mgr.set_environment_variables("gpt-4", key)
                assert os.environ.get("OPENAI_API_KEY") == "sk-test-env-var"
                assert os.environ.get("LLM_API_KEY") == "sk-test-env-var"


# ===================================================================
# validate_and_clean_completion_params
# ===================================================================

class TestValidateAndClean:

    def test_delegates_to_provider_config_manager(self):
        mgr = APIKeyManager()
        params = {"temperature": 0.7, "bad_param": True}
        with patch("backend.core.config.api_key_manager.provider_config_manager") as pcm:
            pcm.validate_and_clean_params.return_value = {"temperature": 0.7}
            result = mgr.validate_and_clean_completion_params("gpt-4", params)
            assert result == {"temperature": 0.7}
            pcm.validate_and_clean_params.assert_called_once_with("openai", params)
