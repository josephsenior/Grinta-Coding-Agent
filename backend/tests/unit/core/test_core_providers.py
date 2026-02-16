"""Tests for backend.core.providers — _LazyModelList and provider patterns."""

from __future__ import annotations

from unittest.mock import patch


from backend.core.providers import (
    PROVIDER_FALLBACK_PATTERNS,
    PROVIDER_KEYWORD_PATTERNS,
    PROVIDER_PREFIX_PATTERNS,
    VERIFIED_PROVIDERS,
    _LazyModelList,
)


class TestVerifiedProviders:
    def test_is_list(self):
        assert isinstance(VERIFIED_PROVIDERS, list)

    def test_contains_main_providers(self):
        for p in ("anthropic", "openai", "mistral"):
            assert p in VERIFIED_PROVIDERS


class TestProviderPrefixPatterns:
    def test_openai(self):
        assert "openai/" in PROVIDER_PREFIX_PATTERNS["openai"]

    def test_anthropic(self):
        assert "anthropic/" in PROVIDER_PREFIX_PATTERNS["anthropic"]

    def test_google(self):
        assert "google/" in PROVIDER_PREFIX_PATTERNS["google"]


class TestProviderKeywordPatterns:
    def test_google_gemini(self):
        assert "gemini" in PROVIDER_KEYWORD_PATTERNS["google"]

    def test_xai_grok(self):
        assert "grok" in PROVIDER_KEYWORD_PATTERNS["xai"]


class TestProviderFallbackPatterns:
    def test_openai(self):
        assert "gpt" in PROVIDER_FALLBACK_PATTERNS["openai"]

    def test_anthropic(self):
        assert "claude" in PROVIDER_FALLBACK_PATTERNS["anthropic"]


class TestLazyModelList:
    @patch("backend.core.providers._get_verified", return_value=["model-a", "model-b"])
    def test_contains(self, mock_get):
        lml = _LazyModelList("openai")
        assert "model-a" in lml
        assert "model-c" not in lml

    @patch("backend.core.providers._get_verified", return_value=["m1", "m2", "m3"])
    def test_len(self, mock_get):
        lml = _LazyModelList("test")
        assert len(lml) == 3

    @patch("backend.core.providers._get_verified", return_value=["alpha", "beta"])
    def test_iter(self, mock_get):
        lml = _LazyModelList("test")
        assert list(lml) == ["alpha", "beta"]

    @patch("backend.core.providers._get_verified", return_value=["x", "y"])
    def test_getitem(self, mock_get):
        lml = _LazyModelList("test")
        assert lml[0] == "x"
        assert lml[1] == "y"

    @patch("backend.core.providers._get_verified", return_value=["a", "b"])
    def test_repr(self, mock_get):
        lml = _LazyModelList("test")
        assert repr(lml) == repr(["a", "b"])

    @patch("backend.core.providers._get_verified", return_value=["a", "b"])
    def test_eq_list(self, mock_get):
        lml = _LazyModelList("test")
        assert lml == ["a", "b"]

    @patch("backend.core.providers._get_verified", return_value=["a"])
    def test_eq_non_list(self, mock_get):
        lml = _LazyModelList("test")
        assert lml.__eq__("not a list") is NotImplemented

    @patch("backend.core.providers._get_verified", return_value=["x"])
    def test_caches_result(self, mock_get):
        lml = _LazyModelList("test")
        _ = list(lml)
        _ = list(lml)
        # _get_verified called only once (cached)
        assert mock_get.call_count == 1
