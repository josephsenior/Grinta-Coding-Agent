"""Unit tests for backend.inference.model_features."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.inference.model_features import (
    FUNCTION_CALLING_PATTERNS,
    PROMPT_CACHE_PATTERNS,
    REASONING_EFFORT_PATTERNS,
    RESPONSE_SCHEMA_PATTERNS,
    SUPPORTS_STOP_WORDS_FALSE_PATTERNS,
    ModelFeatures,
    get_features,
    model_matches,
    normalize_model_name,
)


# ---------------------------------------------------------------------------
# normalize_model_name
# ---------------------------------------------------------------------------


class TestNormalizeModelName:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("GPT-4o", "gpt-4o"),
            ("  gpt-4  ", "gpt-4"),
            ("openai/gpt-4o-mini", "gpt-4o-mini"),
            ("anthropic/claude-3.5-sonnet", "claude-3.5-sonnet"),
            ("google/gemini-2.0-flash", "gemini-2.0-flash"),
            # Multiple slashes — keep after last /
            ("org/team/model-v2", "model-v2"),
            # Ollama-style :tag stripped
            ("ollama/llama3.2:latest", "llama3.2"),
            ("ollama/codestral:7b-q4", "codestral"),
            # Without provider prefix, colons are NOT stripped
            ("llama3.2", "llama3.2"),
            # -gguf suffix removed
            ("llama3-gguf", "llama3"),
            ("some-model-gguf", "some-model"),
            # Edge: empty / whitespace
            ("", ""),
            ("   ", ""),
            (None, ""),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_model_name(raw) == expected


# ---------------------------------------------------------------------------
# model_matches
# ---------------------------------------------------------------------------


class TestModelMatches:
    def test_simple_glob_match(self):
        assert model_matches("gpt-4o", ["gpt-4o*"]) is True

    def test_simple_glob_no_match(self):
        assert model_matches("gpt-4o", ["claude*"]) is False

    def test_provider_qualified_pattern_matches_full(self):
        """Patterns containing '/' match against the full lowercased string."""
        assert model_matches("google/gemini-1.5-pro", ["google/gemini-1.5-*"]) is True

    def test_provider_qualified_does_not_match_bare_name(self):
        # The pattern includes '/' so it must match the full string
        assert model_matches("gemini-1.5-pro", ["google/gemini-1.5-*"]) is False

    def test_bare_pattern_matches_normalized_name(self):
        """Patterns without '/' match against normalized basename."""
        assert model_matches("openai/gpt-4o-mini", ["gpt-4o*"]) is True

    def test_multiple_patterns_first_match_wins(self):
        assert model_matches("claude-3.5-sonnet-20241022", ["gpt*", "claude*"]) is True

    def test_no_patterns_returns_false(self):
        assert model_matches("gpt-4o", []) is False

    def test_empty_model_returns_false(self):
        assert model_matches("", ["gpt*"]) is False

    def test_case_insensitive(self):
        assert model_matches("GPT-4O-Mini", ["gpt-4o*"]) is True

    def test_ollama_tag_stripped_before_matching(self):
        # ollama/llama3.2:latest → normalize → llama3.2
        assert model_matches("ollama/llama3.2:latest", ["llama3*"]) is True


# ---------------------------------------------------------------------------
# ModelFeatures dataclass
# ---------------------------------------------------------------------------


class TestModelFeatures:
    def test_default_values(self):
        f = ModelFeatures()
        assert f.max_input_tokens is None
        assert f.max_output_tokens is None
        assert f.supports_function_calling is False
        assert f.supports_stop_words is True  # default True

    def test_frozen(self):
        f = ModelFeatures(max_input_tokens=1000)
        with pytest.raises(AttributeError):
            f.max_input_tokens = 2000  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Pattern list sanity
# ---------------------------------------------------------------------------


class TestPatternSanity:
    """Verify that known models match the right pattern lists."""

    @pytest.mark.parametrize(
        "model",
        [
            "claude-3-5-sonnet-20241022",
            "gpt-4o-2024-11-20",
            "google/gemini-2.0-flash",
            "grok-3",
        ],
    )
    def test_function_calling_models(self, model):
        assert model_matches(model, FUNCTION_CALLING_PATTERNS)

    @pytest.mark.parametrize(
        "model",
        ["o3-mini", "o1-preview", "gemini-2.5-pro", "deepseek-chat"],
    )
    def test_reasoning_effort_models(self, model):
        assert model_matches(model, REASONING_EFFORT_PATTERNS)

    @pytest.mark.parametrize(
        "model",
        [
            "claude-3.5-sonnet-20241022",
            "claude-3-haiku-20240307",
            "google/gemini-2.0-flash",
            "gemini-2.5-pro",
        ],
    )
    def test_prompt_cache_models(self, model):
        assert model_matches(model, PROMPT_CACHE_PATTERNS)

    @pytest.mark.parametrize(
        "model",
        ["o1-preview", "deepseek-reasoner"],
    )
    def test_stop_words_disabled_models(self, model):
        assert model_matches(model, SUPPORTS_STOP_WORDS_FALSE_PATTERNS)

    @pytest.mark.parametrize(
        "model",
        ["gpt-4o", "claude-3.5-sonnet-20241022", "google/gemini-2.0-flash"],
    )
    def test_response_schema_models(self, model):
        assert model_matches(model, RESPONSE_SCHEMA_PATTERNS)

    def test_unknown_model_matches_nothing(self):
        model = "my-custom-local-model"
        assert not model_matches(model, FUNCTION_CALLING_PATTERNS)
        assert not model_matches(model, REASONING_EFFORT_PATTERNS)
        assert not model_matches(model, PROMPT_CACHE_PATTERNS)


class TestGetFeatures:
    def test_prefers_catalog_entry_over_patterns(self, monkeypatch):
        import backend.inference.catalog_loader as catalog_loader

        # Deliberately contradict pattern defaults to verify catalog-first behavior.
        fake_entry = SimpleNamespace(
            max_input_tokens=111,
            max_output_tokens=222,
            supports_function_calling=False,
            supports_reasoning_effort=False,
            supports_prompt_cache=False,
            supports_stop_words=False,
            supports_response_schema=False,
        )
        monkeypatch.setattr(catalog_loader, "lookup", lambda _model: fake_entry)

        features = get_features("gpt-5")

        assert features.max_input_tokens == 111
        assert features.max_output_tokens == 222
        assert features.supports_function_calling is False
        assert features.supports_reasoning_effort is False
        assert features.supports_prompt_cache is False
        assert features.supports_stop_words is False
        assert features.supports_response_schema is False

    def test_falls_back_to_patterns_when_model_unknown(self, monkeypatch):
        import backend.inference.catalog_loader as catalog_loader

        monkeypatch.setattr(catalog_loader, "lookup", lambda _model: None)
        monkeypatch.setattr(catalog_loader, "get_token_limits", lambda _model: (333, 444))

        features = get_features("o1-preview")

        assert features.max_input_tokens == 333
        assert features.max_output_tokens == 444
        assert features.supports_function_calling is True
        assert features.supports_reasoning_effort is True
        assert features.supports_prompt_cache is False
        assert features.supports_stop_words is False
        assert features.supports_response_schema is True
