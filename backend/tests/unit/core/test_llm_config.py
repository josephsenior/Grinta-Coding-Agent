"""Unit tests for backend.core.config.llm_config — LLMConfig validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core.config.llm_config import LLMConfig, suppress_llm_env_export


# ---------------------------------------------------------------------------
# Basic construction and defaults
# ---------------------------------------------------------------------------


class TestLLMConfigDefaults:
    def test_default_construction(self):
        with suppress_llm_env_export():
            cfg = LLMConfig()
        assert cfg.model  # non-empty default
        assert cfg.num_retries >= 0
        assert 0.0 <= cfg.temperature <= 2.0
        assert 0.0 <= cfg.top_p <= 1.0

    def test_model_is_required_nonempty(self):
        with suppress_llm_env_export():
            with pytest.raises(ValidationError):
                LLMConfig(model="")

    def test_extra_fields_rejected(self):
        with suppress_llm_env_export():
            with pytest.raises(ValidationError):
                LLMConfig(model="gpt-4o", totally_unknown_field="oops")


# ---------------------------------------------------------------------------
# Field validation
# ---------------------------------------------------------------------------


class TestFieldValidation:
    def test_temperature_bounds(self):
        with suppress_llm_env_export():
            with pytest.raises(ValidationError):
                LLMConfig(temperature=-0.1)
            with pytest.raises(ValidationError):
                LLMConfig(temperature=2.1)

    def test_top_p_bounds(self):
        with suppress_llm_env_export():
            with pytest.raises(ValidationError):
                LLMConfig(top_p=-0.1)
            with pytest.raises(ValidationError):
                LLMConfig(top_p=1.1)

    def test_num_retries_cannot_be_negative(self):
        with suppress_llm_env_export():
            with pytest.raises(ValidationError):
                LLMConfig(num_retries=-1)

    def test_valid_temperature(self):
        with suppress_llm_env_export():
            cfg = LLMConfig(temperature=0.5)
        assert cfg.temperature == 0.5


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


class TestURLValidation:
    def test_auto_prepend_http(self):
        with suppress_llm_env_export():
            cfg = LLMConfig(base_url="localhost:8080")
        assert cfg.base_url == "http://localhost:8080"

    def test_https_preserved(self):
        with suppress_llm_env_export():
            cfg = LLMConfig(base_url="https://api.example.com")
        assert cfg.base_url == "https://api.example.com"

    def test_http_preserved(self):
        with suppress_llm_env_export():
            cfg = LLMConfig(base_url="http://localhost:11434/v1")
        assert cfg.base_url == "http://localhost:11434/v1"


# ---------------------------------------------------------------------------
# set_defaults model_validator
# ---------------------------------------------------------------------------


class TestSetDefaults:
    def test_non_gemini_gets_reasoning_effort_high(self):
        with suppress_llm_env_export():
            cfg = LLMConfig(model="gpt-4o")
        assert cfg.reasoning_effort == "high"

    def test_gemini_keeps_none_reasoning_effort(self):
        with suppress_llm_env_export():
            cfg = LLMConfig(model="gemini-2.5-pro")
        assert cfg.reasoning_effort is None

    def test_explicit_reasoning_effort_preserved(self):
        with suppress_llm_env_export():
            cfg = LLMConfig(model="gpt-4o", reasoning_effort="low")
        assert cfg.reasoning_effort == "low"


# ---------------------------------------------------------------------------
# from_toml_section
# ---------------------------------------------------------------------------


class TestFromTomlSection:
    def test_base_section_only(self):
        with suppress_llm_env_export():
            mapping = LLMConfig.from_toml_section({"model": "gpt-4o", "temperature": 0.3})
        assert "llm" in mapping
        assert mapping["llm"].model == "gpt-4o"
        assert mapping["llm"].temperature == 0.3

    def test_custom_section_inherits_base(self):
        with suppress_llm_env_export():
            mapping = LLMConfig.from_toml_section({
                "model": "gpt-4o",
                "num_retries": 5,
                "claude": {"model": "claude-3.5-sonnet"},
            })
        assert "llm" in mapping
        assert "claude" in mapping
        assert mapping["claude"].model == "claude-3.5-sonnet"
        assert mapping["claude"].num_retries == 5  # inherited

    def test_invalid_custom_section_skipped(self):
        with suppress_llm_env_export():
            mapping = LLMConfig.from_toml_section({
                "model": "gpt-4o",
                "bad": {"temperature": 999},  # invalid
            })
        assert "llm" in mapping
        assert "bad" not in mapping

    def test_invalid_base_falls_back_to_defaults(self):
        with suppress_llm_env_export():
            mapping = LLMConfig.from_toml_section({"temperature": 999})
        assert "llm" in mapping
        # Should get a default config since base was invalid


# ---------------------------------------------------------------------------
# suppress_llm_env_export context manager
# ---------------------------------------------------------------------------


class TestSuppressEnvExport:
    def test_suppresses_and_restores(self):
        from backend.core.config.api_key_manager import api_key_manager

        original = api_key_manager.suppress_env_export
        with suppress_llm_env_export():
            assert api_key_manager.suppress_env_export is True
        assert api_key_manager.suppress_env_export == original


# ---------------------------------------------------------------------------
# API key handling and environment variables
# ---------------------------------------------------------------------------


class TestAPIKeyHandling:
    def test_api_key_loaded_from_env(self, monkeypatch):
        """Test API key loading from environment."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test123456789012345678901234567890")
        cfg = LLMConfig(model="gpt-4")
        # Should have loaded API key from environment
        assert cfg.api_key is not None

    def test_explicit_api_key_preserved(self, monkeypatch):
        """Test explicit API key is preserved."""
        from pydantic import SecretStr
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
        cfg = LLMConfig(model="gpt-4", api_key=SecretStr("sk-explicit-key"))
        # Should preserve explicit key
        assert cfg.api_key.get_secret_value() == "sk-explicit-key"

    def test_no_api_key_warning(self, monkeypatch):
        """Test warning when no API key is available."""
        # Clear all common API keys
        for key in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY",
                    "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY"]:
            monkeypatch.delenv(key, raising=False)

        # Clear api_key_manager stored keys
        from backend.core.config.llm_config import api_key_manager
        api_key_manager.provider_api_keys.clear()

        # Should create config but log warning about missing key (lines 349-350)
        cfg = LLMConfig(model="gpt-4")
        assert cfg.model == "gpt-4"
        # API key will be None since no key was found anywhere
        assert cfg.api_key is None

    def test_api_key_plain_string(self, monkeypatch):
        """Test API key as plain string (AttributeError path)."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        # Pass plain string as api_key to trigger AttributeError path
        cfg = LLMConfig(model="gpt-4", api_key="plain-string-key")
        assert cfg.api_key is not None

    def test_api_key_from_environment_fallback(self, monkeypatch):
        """Test fallback to environment when api_key_manager doesn't return key."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test12345678901234567890")
        cfg = LLMConfig(model="claude-3-5-sonnet-20241022")
        # Should pick up from environment
        assert cfg.api_key is not None

    def test_model_post_init_completes(self, monkeypatch):
        """Test model_post_init completes successfully."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        # Create without suppress_llm_env_export to ensure full model_post_init runs
        cfg = LLMConfig(model="gpt-4")
        # If model_post_init completed, config should be fully initialized
        assert cfg.model == "gpt-4"
        assert hasattr(cfg, "_has_explicit_api_key")

# ---------------------------------------------------------------------------
# Base URL cleaning with provider configs
# ---------------------------------------------------------------------------


class TestBaseURLCleaning:
    def test_base_url_cleaned_for_google(self):
        """Test base_url is cleared for providers with handles_own_routing."""
        with suppress_llm_env_export():
            cfg = LLMConfig(model="gemini-pro", base_url="https://custom.com")
        # Google handles own routing, so base_url should be cleared
        assert cfg.base_url is None

    def test_base_url_preserved_for_openai(self):
        """Test base_url is preserved for providers that allow it."""
        with suppress_llm_env_export():
            cfg = LLMConfig(model="gpt-4", base_url="https://api.custom.com")
        assert cfg.base_url == "https://api.custom.com"

    def test_custom_llm_provider_forbidden_logged(self):
        """Test custom_llm_provider forbidden for some providers."""
        with suppress_llm_env_export():
            # Anthropic forbids custom_llm_provider
            cfg = LLMConfig(model="claude-3-5-sonnet-20241022", custom_llm_provider="anthropic")
        # Should still create config (just logs warning)
        assert cfg.model == "claude-3-5-sonnet-20241022"


# ---------------------------------------------------------------------------
# Model-specific defaults
# ---------------------------------------------------------------------------


class TestModelDefaults:
    def test_gemini_25_pro_no_reasoning_effort(self):
        """Test gemini-2.5-pro specifically doesn't get reasoning_effort."""
        with suppress_llm_env_export():
            cfg = LLMConfig(model="gemini-2.5-pro")
        assert cfg.reasoning_effort is None

    def test_non_gemini_25_gets_reasoning_effort(self):
        """Test non-gemini-2.5-pro models get reasoning_effort='high'."""
        with suppress_llm_env_export():
            cfg = LLMConfig(model="gemini-1.5-pro")
        assert cfg.reasoning_effort == "high"

    def test_non_gemini_gets_default_reasoning_effort(self):
        """Test non-Gemini models get reasoning_effort='high' in set_defaults."""
        with suppress_llm_env_export():
            cfg = LLMConfig(model="gpt-4o")  # Non-Gemini, no reasoning_effort specified
        # Should be set to "high" in set_defaults validator (line 207)
        assert cfg.reasoning_effort == "high"



# ---------------------------------------------------------------------------
# Validator edge cases
# ---------------------------------------------------------------------------


class TestValidatorEdgeCases:
    def test_validate_required_strings_with_log_completions_folder(self):
        """Test validate_required_strings on log_completions_folder."""
        with suppress_llm_env_export():
            with pytest.raises(ValidationError):
                LLMConfig(log_completions_folder="")

    def test_validate_required_strings_valid_log_folder(self):
        """Test validate_required_strings accepts valid log_completions_folder."""
        with suppress_llm_env_export():
            cfg = LLMConfig(log_completions_folder="/tmp/logs")
        assert cfg.log_completions_folder == "/tmp/logs"

    def test_validate_urls_with_none(self):
        """Test validate_urls returns None for None input."""
        with suppress_llm_env_export():
            cfg = LLMConfig(base_url=None)
        assert cfg.base_url is None

    def test_validate_urls_strips_whitespace(self):
        """Test validate_urls strips whitespace."""
        with suppress_llm_env_export():
            cfg = LLMConfig(base_url="  https://api.com  ")
        assert cfg.base_url == "https://api.com"

    def test_validate_urls_empty_after_strip(self):
        """Test validate_urls with whitespace-only string."""
        with suppress_llm_env_export():
            with pytest.raises(ValidationError):
                LLMConfig(base_url="   ")

    def test_validate_urls_invalid_protocol(self):
        """Test validate_urls rejects invalid protocols."""
        with suppress_llm_env_export():
            with pytest.raises(ValidationError, match="must start with http"):
                LLMConfig(base_url="ftp://invalid.com")
