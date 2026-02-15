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
