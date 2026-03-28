"""Tests for backend.gateway.cli.cli_utils — ModelInfo, ProviderInfo, extract helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from backend.gateway.cli.cli_utils import (
    ModelInfo,
    ProviderInfo,
    _add_model_to_provider,
    _ensure_runtime_config,
    _get_provider_key,
    _should_skip_model,
    extract_model_and_provider,
    is_number,
    organize_models_and_providers,
    split_is_actually_version,
)


# ── ModelInfo Pydantic model ─────────────────────────────────────────


class TestModelInfo:
    def test_create(self):
        m = ModelInfo(provider="openai", model="gpt-4", separator="/")
        assert m.provider == "openai"
        assert m.model == "gpt-4"
        assert m.separator == "/"

    def test_getitem(self):
        m = ModelInfo(provider="anthropic", model="claude-3", separator="/")
        assert m["provider"] == "anthropic"
        assert m["model"] == "claude-3"
        assert m["separator"] == "/"

    def test_getitem_invalid_key(self):
        m = ModelInfo(provider="p", model="m", separator="/")
        with pytest.raises(KeyError, match="no key"):
            m["nonexistent"]


# ── ProviderInfo Pydantic model ──────────────────────────────────────


class TestProviderInfo:
    def test_create(self):
        p = ProviderInfo(separator="/", models=["gpt-4", "gpt-3.5"])
        assert p.separator == "/"
        assert len(p.models) == 2

    def test_default_models(self):
        p = ProviderInfo(separator=".")
        assert p.models == []

    def test_getitem(self):
        p = ProviderInfo(separator="/", models=["m1"])
        assert p["separator"] == "/"
        assert p["models"] == ["m1"]

    def test_getitem_invalid(self):
        p = ProviderInfo(separator="/")
        with pytest.raises(KeyError):
            p["bad"]

    def test_get_existing(self):
        p = ProviderInfo(separator="/", models=["a"])
        assert p.get("separator") == "/"

    def test_get_missing(self):
        p = ProviderInfo(separator="/")
        assert p.get("nonexistent") is None


# ── is_number ────────────────────────────────────────────────────────


class TestIsNumber:
    def test_digit(self):
        assert is_number("5") is True

    def test_letter(self):
        assert is_number("a") is False

    def test_zero(self):
        assert is_number("0") is True


# ── split_is_actually_version ────────────────────────────────────────


class TestSplitIsActuallyVersion:
    def test_version_split(self):
        # e.g. "claude-3.5-sonnet" → ["claude-3", "5-sonnet"] → True
        assert split_is_actually_version(["claude-3", "5-sonnet"]) is True

    def test_provider_split(self):
        # e.g. "openai.gpt-4" → ["openai", "gpt-4"] → False
        assert split_is_actually_version(["openai", "gpt-4"]) is False

    def test_single_element(self):
        assert split_is_actually_version(["gpt-4"]) is False

    def test_empty_second(self):
        assert split_is_actually_version(["a", ""]) is False


# ── _should_skip_model ───────────────────────────────────────────────


class TestShouldSkipModel:
    def test_skips_anthropic_dot(self):
        assert _should_skip_model("anthropic", ".") is True

    def test_allows_anthropic_slash(self):
        assert _should_skip_model("anthropic", "/") is False

    def test_allows_openai(self):
        assert _should_skip_model("openai", ".") is False


# ── _get_provider_key ────────────────────────────────────────────────


class TestGetProviderKey:
    def test_with_provider(self):
        assert _get_provider_key("openai") == "openai"

    def test_none(self):
        assert _get_provider_key(None) == "other"


# ── _ensure_runtime_config ───────────────────────────────────────────


class TestEnsureRuntimeConfig:
    def test_adds_missing_runtime(self):
        config: dict[str, Any] = {}
        _ensure_runtime_config(config)
        assert "runtime" in config
        assert "trusted_dirs" in config["runtime"]

    def test_adds_missing_trusted_dirs(self):
        config: dict[str, Any] = {"runtime": {}}
        _ensure_runtime_config(config)
        assert config["runtime"]["trusted_dirs"] == []

    def test_preserves_existing(self):
        config = {"runtime": {"trusted_dirs": ["/a"]}}
        _ensure_runtime_config(config)
        assert config["runtime"]["trusted_dirs"] == ["/a"]


# ── _add_model_to_provider ───────────────────────────────────────────


class TestAddModelToProvider:
    def test_adds_new_provider(self):
        d: dict[str, ProviderInfo] = {}
        _add_model_to_provider(d, "openai", "/", "gpt-4")
        assert "openai" in d
        assert d["openai"].models == ["gpt-4"]

    def test_appends_to_existing(self):
        d = {"openai": ProviderInfo(separator="/", models=["gpt-4"])}
        _add_model_to_provider(d, "openai", "/", "gpt-3.5")
        assert d["openai"].models == ["gpt-4", "gpt-3.5"]


# ── extract_model_and_provider ───────────────────────────────────────


class TestExtractModelAndProvider:
    def test_slash_separated(self):
        result = extract_model_and_provider("openai/gpt-4")
        assert result.provider == "openai"
        assert result.model == "gpt-4"
        assert result.separator == "/"

    def test_dot_separated_provider(self):
        result = extract_model_and_provider("mistral.mistral-large")
        assert result.provider == "mistral"
        assert result.model == "mistral-large"
        assert result.separator == "."

    @patch("backend.gateway.cli.cli_utils.VERIFIED_OPENAI_MODELS", ["gpt-4o"])
    def test_known_openai_model(self):
        result = extract_model_and_provider("gpt-4o")
        assert result.provider == "openai"
        assert result.model == "gpt-4o"

    @patch("backend.gateway.cli.cli_utils.VERIFIED_ANTHROPIC_MODELS", ["claude-3-opus"])
    @patch("backend.gateway.cli.cli_utils.VERIFIED_OPENAI_MODELS", [])
    def test_known_anthropic_model(self):
        result = extract_model_and_provider("claude-3-opus")
        assert result.provider == "anthropic"
        assert result.model == "claude-3-opus"

    @patch("backend.gateway.cli.cli_utils.VERIFIED_OPENAI_MODELS", [])
    @patch("backend.gateway.cli.cli_utils.VERIFIED_ANTHROPIC_MODELS", [])
    @patch("backend.gateway.cli.cli_utils.VERIFIED_MISTRAL_MODELS", [])
    def test_unknown_bare_model(self):
        result = extract_model_and_provider("some-random-model")
        assert result.provider == ""
        assert result.model == "some-random-model"

    def test_version_number_not_split(self):
        # "claude-3.5-sonnet" — the '.5' starts with digit → version, not provider
        result = extract_model_and_provider("claude-3.5-sonnet")
        # Should stay as one piece since split_is_actually_version returns True
        # Falls through to verified model or unknown
        assert result.model  # non-empty


# ── organize_models_and_providers ────────────────────────────────────


class TestOrganizeModelsAndProviders:
    def test_groups_by_provider(self):
        models = ["openai/gpt-4", "openai/gpt-3.5", "anthropic/claude-3"]
        result = organize_models_and_providers(models)
        assert "openai" in result
        assert len(result["openai"].models) == 2
        assert "anthropic" in result

    def test_skips_anthropic_dot(self):
        models = ["anthropic.some-model"]
        result = organize_models_and_providers(models)
        assert "anthropic" not in result

    @patch("backend.gateway.cli.cli_utils.VERIFIED_OPENAI_MODELS", [])
    @patch("backend.gateway.cli.cli_utils.VERIFIED_ANTHROPIC_MODELS", [])
    @patch("backend.gateway.cli.cli_utils.VERIFIED_MISTRAL_MODELS", [])
    def test_unknown_goes_to_other(self):
        models = ["unknown-model"]
        result = organize_models_and_providers(models)
        assert "other" in result

    def test_empty_list(self):
        result = organize_models_and_providers([])
        assert result == {}
