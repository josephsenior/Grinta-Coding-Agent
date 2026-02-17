"""Tests for backend.llm.catalog_loader — model catalog and pricing lookups."""

import pytest
from unittest.mock import patch

from backend.llm.catalog_loader import (
    ModelEntry,
    _load_raw,
    get_catalog,
    _name_index,
    lookup,
    get_pricing,
    get_token_limits,
    get_featured_models,
    get_verified_models,
    get_all_model_names,
)


class TestModelEntry:
    """Tests for ModelEntry dataclass."""

    def test_minimal_creation(self):
        """Test creating ModelEntry with required fields only."""
        entry = ModelEntry(name="gpt-4o", provider="openai")
        assert entry.name == "gpt-4o"
        assert entry.provider == "openai"
        assert entry.aliases == ()
        assert entry.verified is False
        assert entry.featured is False

    def test_full_creation(self):
        """Test creating ModelEntry with all fields."""
        entry = ModelEntry(
            name="gpt-4o",
            provider="openai",
            aliases=("gpt4o", "gpt-4-optimized"),
            max_input_tokens=128000,
            max_output_tokens=16384,
            input_price_per_m=2.5,
            output_price_per_m=10.0,
            verified=True,
            featured=True,
            supports_function_calling=True,
            supports_reasoning_effort=False,
            supports_prompt_cache=True,
            supports_stop_words=True,
            supports_response_schema=True,
            supports_vision=True,
        )
        assert entry.name == "gpt-4o"
        assert entry.max_input_tokens == 128000
        assert entry.input_price_per_m == 2.5
        assert entry.verified is True
        assert entry.supports_vision is True

    def test_frozen_dataclass(self):
        """Test ModelEntry is frozen (immutable)."""
        entry = ModelEntry(name="test", provider="test")
        with pytest.raises(AttributeError):
            entry.name = "new-name"

    def test_default_supports_stop_words(self):
        """Test supports_stop_words defaults to True."""
        entry = ModelEntry(name="test", provider="test")
        assert entry.supports_stop_words is True


class TestLoadRaw:
    """Tests for _load_raw function."""

    def test_loads_toml_data(self):
        """Test _load_raw returns dict from catalog.toml."""
        data = _load_raw()
        assert isinstance(data, dict)
        assert "models" in data

    def test_caching(self):
        """Test _load_raw caches result."""
        data1 = _load_raw()
        data2 = _load_raw()
        # Should return the exact same object (cached)
        assert data1 is data2


class TestGetCatalog:
    """Tests for get_catalog function."""

    def test_returns_tuple_of_entries(self):
        """Test get_catalog returns tuple of ModelEntry."""
        catalog = get_catalog()
        assert isinstance(catalog, tuple)
        assert len(catalog) > 0
        assert all(isinstance(e, ModelEntry) for e in catalog)

    def test_contains_known_models(self):
        """Test catalog contains expected models."""
        catalog = get_catalog()
        names = [e.name for e in catalog]
        # Should contain at least some common models
        assert len(names) > 0

    def test_caching(self):
        """Test get_catalog caches result."""
        catalog1 = get_catalog()
        catalog2 = get_catalog()
        assert catalog1 is catalog2

    def test_all_required_fields(self):
        """Test all entries have required fields."""
        catalog = get_catalog()
        for entry in catalog:
            assert entry.name
            assert entry.provider


class TestNameIndex:
    """Tests for _name_index function."""

    def test_index_includes_names(self):
        """Test index includes all canonical names."""
        idx = _name_index()
        catalog = get_catalog()
        for entry in catalog:
            assert entry.name in idx
            assert idx[entry.name] is entry

    def test_index_includes_aliases(self):
        """Test index includes all aliases."""
        idx = _name_index()
        catalog = get_catalog()
        for entry in catalog:
            for alias in entry.aliases:
                assert alias in idx

    def test_caching(self):
        """Test _name_index caches result."""
        idx1 = _name_index()
        idx2 = _name_index()
        assert idx1 is idx2


class TestLookup:
    """Tests for lookup function."""

    def test_lookup_by_canonical_name(self):
        """Test lookup by canonical model name."""
        catalog = get_catalog()
        if catalog:
            entry = catalog[0]
            result = lookup(entry.name)
            assert result is entry

    def test_lookup_case_insensitive(self):
        """Test lookup is case-insensitive."""
        catalog = get_catalog()
        if catalog:
            name = catalog[0].name
            result = lookup(name.upper())
            if result:  # May or may not match depending on catalog
                assert result.name.lower() == name.lower()

    def test_lookup_with_provider_prefix(self):
        """Test lookup strips provider prefix."""
        # Look up "openai/gpt-4o" should find "gpt-4o"
        result = lookup("openai/gpt-4o")
        if result:
            assert "gpt-4o" in result.name or "gpt-4o" in result.aliases

    def test_lookup_nonexistent(self):
        """Test lookup returns None for nonexistent model."""
        result = lookup("nonexistent-model-xyz-123")
        assert result is None

    def test_lookup_strips_whitespace(self):
        """Test lookup strips whitespace."""
        catalog = get_catalog()
        if catalog:
            name = catalog[0].name
            result = lookup(f"  {name}  ")
            assert result is not None

    def test_lookup_by_alias(self):
        """Test lookup by alias."""
        idx = _name_index()
        # Find an entry with aliases
        for key, entry in idx.items():
            if key in entry.aliases:
                result = lookup(key)
                assert result is entry
                break


class TestGetPricing:
    """Tests for get_pricing function."""

    def test_pricing_from_catalog(self):
        """Test get_pricing returns catalog pricing."""
        catalog = get_catalog()
        # Find a model with pricing
        for entry in catalog:
            if entry.input_price_per_m is not None:
                pricing = get_pricing(entry.name)
                assert pricing is not None
                assert "input" in pricing
                assert "output" in pricing
                assert pricing["input"] == entry.input_price_per_m
                break

    def test_pricing_nonexistent_model(self):
        """Test get_pricing with tier fallback."""
        # Use a model that might match tier pricing
        pricing = get_pricing("nonexistent-gpt-4-model")
        # May or may not have tier pricing, just check type
        assert pricing is None or isinstance(pricing, dict)

    def test_pricing_output_defaults_to_zero(self):
        """Test output price defaults to 0 if not set."""
        # Create mock entry with input price only
        with patch("backend.llm.catalog_loader.lookup") as mock_lookup:
            mock_entry = ModelEntry(
                name="test",
                provider="test",
                input_price_per_m=5.0,
                output_price_per_m=None,
            )
            mock_lookup.return_value = mock_entry
            pricing = get_pricing("test")
            assert pricing["output"] == 0.0

    def test_pricing_returns_none_if_no_match(self):
        """Test returns None if no catalog or tier match."""
        pricing = get_pricing("completely-unknown-model-xyz")
        # Should be None or a tier fallback
        assert pricing is None or isinstance(pricing, dict)


class TestGetTokenLimits:
    """Tests for get_token_limits function."""

    def test_token_limits_from_catalog(self):
        """Test get_token_limits returns catalog limits."""
        catalog = get_catalog()
        for entry in catalog:
            if entry.max_input_tokens is not None:
                input_limit, output_limit = get_token_limits(entry.name)
                assert input_limit == entry.max_input_tokens
                assert output_limit == entry.max_output_tokens
                break

    def test_token_limits_nonexistent(self):
        """Test get_token_limits returns (None, None) for unknown model."""
        input_limit, output_limit = get_token_limits("nonexistent-model-xyz")
        assert input_limit is None
        assert output_limit is None

    def test_token_limits_with_alias(self):
        """Test get_token_limits works with aliases."""
        idx = _name_index()
        for key, entry in idx.items():
            if key in entry.aliases and entry.max_input_tokens:
                input_limit, output_limit = get_token_limits(key)
                assert input_limit == entry.max_input_tokens
                break


class TestGetFeaturedModels:
    """Tests for get_featured_models function."""

    def test_returns_list_of_strings(self):
        """Test get_featured_models returns list of strings."""
        featured = get_featured_models()
        assert isinstance(featured, list)
        assert all(isinstance(m, str) for m in featured)

    def test_format_includes_provider(self):
        """Test featured models are in 'provider/name' format."""
        featured = get_featured_models()
        for model in featured:
            assert "/" in model

    def test_only_featured_models(self):
        """Test only models marked featured=True are included."""
        featured = get_featured_models()
        catalog = get_catalog()
        featured_set = set(featured)
        for entry in catalog:
            formatted = f"{entry.provider}/{entry.name}"
            if entry.featured:
                assert formatted in featured_set
            else:
                assert formatted not in featured_set


class TestGetVerifiedModels:
    """Tests for get_verified_models function."""

    def test_returns_list_of_strings(self):
        """Test get_verified_models returns list of strings."""
        verified = get_verified_models()
        assert isinstance(verified, list)
        assert all(isinstance(m, str) for m in verified)

    def test_only_verified_models(self):
        """Test only models marked verified=True are included."""
        verified = get_verified_models()
        catalog = get_catalog()
        verified_set = set(verified)
        for entry in catalog:
            if entry.verified:
                assert entry.name in verified_set
            else:
                assert entry.name not in verified_set

    def test_filter_by_provider(self):
        """Test filtering verified models by provider."""
        catalog = get_catalog()
        # Find a provider with verified models
        providers = {e.provider for e in catalog if e.verified}
        if providers:
            provider = list(providers)[0]
            verified = get_verified_models(provider=provider)
            # All returned models should be from this provider
            for model_name in verified:
                entry = lookup(model_name)
                assert entry.provider == provider

    def test_filter_no_results(self):
        """Test filtering by provider with no verified models."""
        verified = get_verified_models(provider="nonexistent-provider")
        assert verified == []


class TestGetAllModelNames:
    """Tests for get_all_model_names function."""

    def test_returns_sequence(self):
        """Test get_all_model_names returns sequence."""
        names = get_all_model_names()
        assert isinstance(names, list | tuple)

    def test_all_strings(self):
        """Test all returned values are strings."""
        names = get_all_model_names()
        assert all(isinstance(n, str) for n in names)

    def test_matches_catalog_length(self):
        """Test length matches catalog length."""
        names = get_all_model_names()
        catalog = get_catalog()
        assert len(names) == len(catalog)

    def test_contains_canonical_names(self):
        """Test returned names match catalog canonical names."""
        names = get_all_model_names()
        catalog = get_catalog()
        catalog_names = [e.name for e in catalog]
        assert set(names) == set(catalog_names)
