"""Unit tests for backend.inference.registry."""

from __future__ import annotations

from unittest.mock import patch

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


@patch(
    'backend.inference.registry.fetch_remote_models',
    return_value=['gpt-4o', 'new-api-model'],
)
def test_build_model_entries_api_first_with_catalog_overlay(mock_fetch) -> None:
    entries = build_model_entries_by_provider(provider='openai', api_key='sk-test')
    names = {entry.name for entry in entries['openai']}
    assert 'new-api-model' in names
    assert 'gpt-4o' in names
    assert (
        'gpt-5' not in names
    )  # featured catalog stub omitted when API listing succeeds
    mock_fetch.assert_called_once()


@patch('backend.inference.registry.fetch_remote_models', return_value=[])
def test_build_model_entries_catalog_fallback_when_api_empty(mock_fetch) -> None:
    entries = build_model_entries_by_provider(provider='openai', api_key='sk-test')
    names = {entry.name for entry in entries['openai']}
    assert 'gpt-5' in names
    mock_fetch.assert_called_once()


@patch('backend.inference.registry.fetch_remote_models', return_value=['remote-only'])
def test_list_model_names_api_first_skips_static_when_remote_returns(
    mock_fetch,
) -> None:
    names = list_model_names('groq', api_key='gsk_test')
    assert names == ['remote-only']
    mock_fetch.assert_called_once()


@patch('backend.inference.registry.fetch_remote_models', return_value=[])
def test_list_model_names_falls_back_to_catalog_when_remote_empty(mock_fetch) -> None:
    names = list_model_names('groq', api_key='gsk_test')
    assert 'llama-3.3-70b-versatile' in names
    mock_fetch.assert_called_once()
