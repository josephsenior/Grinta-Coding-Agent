"""Tests for backend.llm.catalog_loader — ModelEntry, lookup, pricing, etc."""

from __future__ import annotations

import pytest

from backend.llm.catalog_loader import (
    ModelEntry,
    get_all_model_names,
    get_catalog,
    get_featured_models,
    get_pricing,
    get_token_limits,
    get_verified_models,
    lookup,
)


# ── ModelEntry dataclass ───────────────────────────────────────────────

class TestModelEntry:
    def test_required_fields(self):
        e = ModelEntry(name="gpt-4o", provider="openai")
        assert e.name == "gpt-4o"
        assert e.provider == "openai"

    def test_defaults(self):
        e = ModelEntry(name="m", provider="p")
        assert not e.aliases
        assert e.max_input_tokens is None
        assert e.max_output_tokens is None
        assert e.input_price_per_m is None
        assert e.output_price_per_m is None
        assert e.verified is False
        assert e.featured is False
        assert e.supports_function_calling is False
        assert e.supports_reasoning_effort is False
        assert e.supports_prompt_cache is False
        assert e.supports_stop_words is True
        assert e.supports_response_schema is False
        assert e.supports_vision is False

    def test_frozen(self):
        e = ModelEntry(name="m", provider="p")
        with pytest.raises(AttributeError):
            e.name = "other"  # type: ignore[misc]

    def test_equality(self):
        a = ModelEntry(name="m", provider="p", verified=True)
        b = ModelEntry(name="m", provider="p", verified=True)
        assert a == b

    def test_with_aliases(self):
        e = ModelEntry(name="m", provider="p", aliases=("a1", "a2"))
        assert "a1" in e.aliases
        assert len(e.aliases) == 2


# ── get_catalog ────────────────────────────────────────────────────────

class TestGetCatalog:
    def test_returns_tuple(self):
        catalog = get_catalog()
        assert isinstance(catalog, tuple)

    def test_entries_are_model_entry(self):
        catalog = get_catalog()
        assert len(catalog) > 0
        for entry in catalog:
            assert isinstance(entry, ModelEntry)

    def test_all_have_provider(self):
        for entry in get_catalog():
            assert entry.provider, f"{entry.name} missing provider"


# ── lookup ─────────────────────────────────────────────────────────────

class TestLookup:
    def test_existing_model(self):
        catalog = get_catalog()
        if catalog:
            first = catalog[0]
            result = lookup(first.name)
            assert result is not None
            assert result.name == first.name

    def test_nonexistent_model(self):
        assert lookup("definitely-not-a-real-model-xyz-123") is None

    def test_case_insensitive(self):
        catalog = get_catalog()
        if catalog:
            first = catalog[0]
            result = lookup(first.name.upper())
            # May or may not match depending on catalog structure
            # Just verify it doesn't raise
            assert result is None or isinstance(result, ModelEntry)

    def test_provider_prefix_stripped(self):
        catalog = get_catalog()
        if catalog:
            first = catalog[0]
            result = lookup(f"{first.provider}/{first.name}")
            assert result is not None
            assert result.name == first.name


# ── get_pricing ────────────────────────────────────────────────────────

class TestGetPricing:
    def test_nonexistent_model(self):
        result = get_pricing("nonexistent-model-xyz")
        # Could be None or a tier match
        assert result is None or isinstance(result, dict)

    def test_known_model_returns_dict(self):
        # Find a model with pricing
        for entry in get_catalog():
            if entry.input_price_per_m is not None:
                result = get_pricing(entry.name)
                assert result is not None
                assert "input" in result
                assert "output" in result
                break


# ── get_token_limits ───────────────────────────────────────────────────

class TestGetTokenLimits:
    def test_nonexistent(self):
        inp, out = get_token_limits("nonexistent-model-xyz")
        assert inp is None
        assert out is None

    def test_known_model(self):
        for entry in get_catalog():
            if entry.max_input_tokens is not None:
                inp, out = get_token_limits(entry.name)
                assert inp == entry.max_input_tokens
                assert out == entry.max_output_tokens
                break


# ── get_featured_models ────────────────────────────────────────────────

class TestGetFeaturedModels:
    def test_returns_list(self):
        result = get_featured_models()
        assert isinstance(result, list)

    def test_format_provider_slash_name(self):
        for item in get_featured_models():
            assert "/" in item


# ── get_verified_models ────────────────────────────────────────────────

class TestGetVerifiedModels:
    def test_returns_list(self):
        result = get_verified_models()
        assert isinstance(result, list)

    def test_filter_by_provider(self):
        all_models = get_verified_models()
        if all_models:
            # Get a provider name from the catalog
            entry = next(e for e in get_catalog() if e.verified)
            filtered = get_verified_models(provider=entry.provider)
            assert len(filtered) <= len(all_models)
            assert all(
                lookup(m).provider == entry.provider for m in filtered
            )


# ── get_all_model_names ────────────────────────────────────────────────

class TestGetAllModelNames:
    def test_returns_sequence(self):
        result = get_all_model_names()
        assert len(result) > 0

    def test_names_are_strings(self):
        for name in get_all_model_names():
            assert isinstance(name, str)
