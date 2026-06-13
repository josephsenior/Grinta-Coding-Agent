"""Unit tests for backend.inference.registry."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.inference.registry import (
    build_model_entries_by_provider,
    get_listable_providers,
    get_static_model_names,
    include_remote_listing_for_provider,
    list_model_names,
    normalize_provider_name,
    provider_label,
)


def test_normalize_provider_name() -> None:
    assert normalize_provider_name('  OpenAI ') == 'openai'
    assert normalize_provider_name('') is None
    assert normalize_provider_name(None) is None


def test_get_listable_providers_includes_local() -> None:
    providers = get_listable_providers()
    assert 'openai' in providers
    assert 'ollama' in providers
    assert 'digitalocean' not in providers


def test_groq_static_catalog() -> None:
    models = get_static_model_names('groq')
    assert 'llama-3.3-70b-versatile' in models


def test_provider_label_local() -> None:
    assert provider_label('lm_studio') == 'LM Studio'


def test_include_remote_listing_requires_key_for_dynamic_provider() -> None:
    assert include_remote_listing_for_provider('groq', None) is False
    assert include_remote_listing_for_provider('groq', 'gsk_test') is True


def test_build_model_entries_merges_catalog() -> None:
    entries = build_model_entries_by_provider(provider='mistral', include_remote=False)
    assert 'mistral-large-latest' in {e.name for e in entries['mistral']}


@patch('backend.inference.registry.fetch_remote_models', return_value=['remote-model'])
def test_list_model_names_includes_remote_when_requested(mock_fetch) -> None:
    names = list_model_names('groq', api_key='gsk_test')
    assert 'remote-model' in names
    mock_fetch.assert_called_once()
