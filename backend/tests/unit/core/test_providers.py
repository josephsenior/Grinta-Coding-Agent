"""Tests for backend.core.providers — _LazyModelList and constants."""

from __future__ import annotations

from unittest.mock import patch


from backend.core.providers import (
    DEFAULT_API_KEY_MIN_LENGTH,
    PROVIDER_CONFIGURATIONS,
    PROVIDER_FALLBACK_PATTERNS,
    PROVIDER_KEYWORD_PATTERNS,
    PROVIDER_PREFIX_PATTERNS,
    UNKNOWN_PROVIDER_CONFIG,
    VERIFIED_PROVIDERS,
    _LazyModelList,
    _get_verified,
)


# ===================================================================
# _get_verified
# ===================================================================

class TestGetVerified:

    def test_get_verified_loads_from_catalog(self):
        """Test that _get_verified calls catalog_loader."""
        with patch("backend.llm.catalog_loader.get_verified_models", return_value=["model-1", "model-2"]) as mock_loader:
            result = _get_verified("test_provider")
            assert result == ["model-1", "model-2"]
            mock_loader.assert_called_once_with("test_provider")


# ===================================================================
# _LazyModelList
# ===================================================================

class TestLazyModelList:

    def test_loads_on_first_access(self):
        with patch("backend.core.providers._get_verified", return_value=["model-a", "model-b"]):
            lazy = _LazyModelList("test_provider")
            assert lazy._cached is None
            assert len(lazy) == 2
            assert lazy._cached is not None

    def test_contains(self):
        with patch("backend.core.providers._get_verified", return_value=["gpt-4", "gpt-3.5"]):
            lazy = _LazyModelList("openai")
            assert "gpt-4" in lazy
            assert "unknown" not in lazy

    def test_iter(self):
        with patch("backend.core.providers._get_verified", return_value=["a", "b", "c"]):
            lazy = _LazyModelList("p")
            assert list(lazy) == ["a", "b", "c"]

    def test_getitem(self):
        with patch("backend.core.providers._get_verified", return_value=["x", "y"]):
            lazy = _LazyModelList("p")
            assert lazy[0] == "x"
            assert lazy[1] == "y"

    def test_eq_with_list(self):
        with patch("backend.core.providers._get_verified", return_value=["a", "b"]):
            lazy = _LazyModelList("p")
            assert lazy == ["a", "b"]

    def test_eq_with_non_list(self):
        with patch("backend.core.providers._get_verified", return_value=["a"]):
            lazy = _LazyModelList("p")
            assert lazy.__eq__("not a list") is NotImplemented

    def test_repr(self):
        with patch("backend.core.providers._get_verified", return_value=["m1"]):
            lazy = _LazyModelList("p")
            r = repr(lazy)
            assert "m1" in r

    def test_caches_after_first_call(self):
        call_count = {"n": 0}
        def mock_get(provider):
            call_count["n"] += 1
            return ["model"]

        with patch("backend.core.providers._get_verified", side_effect=mock_get):
            lazy = _LazyModelList("p")
            _ = len(lazy)
            _ = len(lazy)
            assert call_count["n"] == 1  # Only called once


# ===================================================================
# Constants
# ===================================================================

class TestProviderConstants:

    def test_verified_providers(self):
        assert "openai" in VERIFIED_PROVIDERS
        assert "anthropic" in VERIFIED_PROVIDERS

    def test_provider_configurations_keys(self):
        assert "openai" in PROVIDER_CONFIGURATIONS
        assert "anthropic" in PROVIDER_CONFIGURATIONS
        assert "google" in PROVIDER_CONFIGURATIONS
        assert "xai" in PROVIDER_CONFIGURATIONS

    def test_each_config_has_required_keys(self):
        required_keys = {"name", "env_var", "required_params", "supports_streaming"}
        for provider, config in PROVIDER_CONFIGURATIONS.items():
            for key in required_keys:
                assert key in config, f"Missing '{key}' in {provider}"

    def test_unknown_provider_config(self):
        assert UNKNOWN_PROVIDER_CONFIG["name"] == "unknown"
        assert UNKNOWN_PROVIDER_CONFIG["env_var"] is None

    def test_default_api_key_min_length(self):
        assert DEFAULT_API_KEY_MIN_LENGTH == 10

    def test_prefix_patterns_structure(self):
        for patterns in PROVIDER_PREFIX_PATTERNS.values():
            assert isinstance(patterns, list)
            assert all(isinstance(p, str) for p in patterns)

    def test_keyword_patterns_structure(self):
        for patterns in PROVIDER_KEYWORD_PATTERNS.values():
            assert isinstance(patterns, list)

    def test_fallback_patterns_structure(self):
        for patterns in PROVIDER_FALLBACK_PATTERNS.values():
            assert isinstance(patterns, list)
