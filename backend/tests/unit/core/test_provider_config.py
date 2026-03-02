"""Tests for backend.core.config.provider_config — ProviderConfig and manager."""

from __future__ import annotations

from typing import Any

from backend.core.config.provider_config import (
    ParameterType,
    ProviderConfig,
    ProviderConfigurationManager,
)


# ── ParameterType enum ───────────────────────────────────────────────


class TestParameterType:
    def test_values(self):
        assert ParameterType.REQUIRED.value == "required"
        assert ParameterType.OPTIONAL.value == "optional"
        assert ParameterType.FORBIDDEN.value == "forbidden"


# ── ProviderConfig dataclass ─────────────────────────────────────────


class TestProviderConfig:
    def test_defaults(self):
        cfg = ProviderConfig(name="test")
        assert cfg.name == "test"
        assert cfg.env_var is None
        assert cfg.requires_protocol is True
        assert cfg.supports_streaming is True
        assert cfg.required_params == set()
        assert cfg.optional_params == set()
        assert cfg.forbidden_params == set()
        assert cfg.api_key_prefixes == []
        assert cfg.handles_own_routing is False

    def test_is_param_allowed(self):
        cfg = ProviderConfig(
            name="test",
            required_params={"model"},
            optional_params={"temperature"},
            forbidden_params={"bad_param"},
        )
        assert cfg.is_param_allowed("model") is True
        assert cfg.is_param_allowed("temperature") is True
        assert cfg.is_param_allowed("bad_param") is False
        assert cfg.is_param_allowed("unknown") is False

    def test_is_param_required(self):
        cfg = ProviderConfig(
            name="test",
            required_params={"model"},
            optional_params={"temperature"},
        )
        assert cfg.is_param_required("model") is True
        assert cfg.is_param_required("temperature") is False
        assert cfg.is_param_required("unknown") is False

    def test_validate_base_url_none(self):
        cfg = ProviderConfig(name="test")
        assert cfg.validate_base_url(None) is None

    def test_validate_base_url_empty(self):
        cfg = ProviderConfig(name="test")
        assert cfg.validate_base_url("") is None

    def test_validate_base_url_whitespace(self):
        cfg = ProviderConfig(name="test")
        assert cfg.validate_base_url("   ") is None

    def test_validate_base_url_valid(self):
        cfg = ProviderConfig(name="test")
        assert (
            cfg.validate_base_url("https://api.example.com")
            == "https://api.example.com"
        )

    def test_validate_base_url_no_protocol(self):
        cfg = ProviderConfig(name="test", requires_protocol=True)
        assert cfg.validate_base_url("api.example.com") is None

    def test_validate_base_url_handles_own_routing(self):
        cfg = ProviderConfig(name="test", handles_own_routing=True)
        assert cfg.validate_base_url("https://api.example.com") is None


# ── ProviderConfigurationManager ─────────────────────────────────────


class TestProviderConfigurationManager:
    def setup_method(self):
        self.mgr = ProviderConfigurationManager()

    def test_get_known_provider(self):
        cfg = self.mgr.get_provider_config("openai")
        assert cfg.name == "openai"

    def test_get_unknown_provider(self):
        cfg = self.mgr.get_provider_config("nonexistent_provider_xyz")
        assert cfg.name == "unknown"

    def test_validate_and_clean_params_forbidden(self):
        """Test that forbidden params are removed."""
        params = {"model": "gpt-4", "custom_llm_provider": "bad"}
        cleaned = self.mgr.validate_and_clean_params("anthropic", params)
        assert "custom_llm_provider" not in cleaned
        assert "model" in cleaned

    def test_validate_and_clean_params_base_url_cleared(self):
        """Test base_url handling for provider with handles_own_routing."""
        params = {"model": "gemini-pro", "base_url": "https://custom.com"}
        cleaned = self.mgr.validate_and_clean_params("google", params)
        # Google handles_own_routing=True, so base_url should be cleared
        assert "base_url" not in cleaned

    def test_validate_and_clean_params_base_url_invalid(self):
        """Test base_url without protocol gets cleared."""
        params = {"model": "gpt-4", "api_key": "sk-test", "base_url": "invalid.com"}
        cleaned = self.mgr.validate_and_clean_params("openai", params)
        # Invalid base_url should be removed
        assert "base_url" not in cleaned

    def test_validate_and_clean_params_unknown_params(self):
        """Test unknown params are allowed with logging."""
        params = {"model": "gpt-4", "unknown_param": "value"}
        cleaned = self.mgr.validate_and_clean_params("openai", params)
        assert "unknown_param" in cleaned

    def test_validate_and_clean_params_unknown_provider(self):
        """Test unknown params for unknown provider."""
        params: dict[str, Any] = {"model": "custom", "custom_param": "value"}
        cleaned = self.mgr.validate_and_clean_params("unknown_provider", params)
        assert "custom_param" in cleaned

    def test_validate_and_clean_params_missing_required(self):
        """Test warning for missing required params."""
        params: dict[str, Any] = {}  # Missing required 'model'
        cleaned = self.mgr.validate_and_clean_params("openai", params)
        # Should return cleaned dict even with missing required params
        assert isinstance(cleaned, dict)

    def test_validate_api_key_format_prefix_mismatch(self):
        """Test API key with wrong prefix (should warn but not fail)."""
        result = self.mgr.validate_api_key_format(
            "openai", "bad-prefix-123456789012345678"
        )
        assert result is True  # Warns but still returns True

    def test_get_environment_variable(self):
        """Test getting environment variable name for provider."""
        env_var = self.mgr.get_environment_variable("openai")
        assert env_var == "OPENAI_API_KEY"

    def test_gemini_alias(self):
        cfg = self.mgr.get_provider_config("gemini")
        assert cfg.name == "google"

    def test_case_insensitive(self):
        cfg = self.mgr.get_provider_config("OpenAI")
        # Lowercased lookup
        assert cfg.name == "openai"

    def test_validate_and_clean_params_forbidden_unknown(self):
        # Find a provider with forbidden params
        result = self.mgr.validate_and_clean_params(
            "unknown",
            {"model": "gpt-4o", "temperature": 0.5},
        )
        assert "model" in result

    def test_validate_and_clean_removes_forbidden(self):
        # Create a custom provider to test
        cfg = ProviderConfig(
            name="custom",
            forbidden_params={"bad_param"},
            optional_params={"good_param"},
        )
        self.mgr._provider_configs["custom"] = cfg

        result = self.mgr.validate_and_clean_params(
            "custom",
            {"good_param": "ok", "bad_param": "removed"},
        )
        assert "good_param" in result
        assert "bad_param" not in result

    def test_validate_api_key_format_none_not_required(self):
        # For unknown provider, api_key is not required
        assert self.mgr.validate_api_key_format("unknown", None) is True

    def test_validate_api_key_format_too_short(self):
        assert self.mgr.validate_api_key_format("openai", "short") is False

    def test_validate_api_key_format_valid(self):
        assert self.mgr.validate_api_key_format("openai", "sk-" + "x" * 48) is True

    def test_get_environment_variable_not_none(self):
        env_var = self.mgr.get_environment_variable("openai")
        assert env_var is not None

    def test_get_environment_variable_unknown(self):
        env_var = self.mgr.get_environment_variable("nonexistent_xyz")
        assert env_var is None or isinstance(env_var, str)
