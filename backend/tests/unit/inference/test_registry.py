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
    resolve_include_remote_model_listing,
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


def test_resolve_include_remote_model_listing_defaults_false(monkeypatch) -> None:
    monkeypatch.delenv('GRINTA_INCLUDE_REMOTE_MODEL_LISTING', raising=False)
    assert resolve_include_remote_model_listing() is False
    assert resolve_include_remote_model_listing(True) is True


def test_build_model_entries_uses_catalog_by_default() -> None:
    entries = build_model_entries_by_provider(provider='mistral')
    assert 'mistral-large-latest' in {e.name for e in entries['mistral']}


@patch(
    'backend.inference.registry.fetch_remote_models',
    return_value=['gpt-4o', 'new-api-model'],
)
def test_build_model_entries_merges_remote_when_opted_in(mock_fetch) -> None:
    entries = build_model_entries_by_provider(
        provider='openai',
        api_key='sk-test',
        include_remote=True,
    )
    names = {entry.name for entry in entries['openai']}
    assert 'new-api-model' in names
    assert 'gpt-4o' in names
    assert 'gpt-5' in names
    mock_fetch.assert_called_once()


@patch('backend.inference.registry.fetch_remote_models', return_value=[])
def test_build_model_entries_catalog_only_without_remote_opt_in(mock_fetch) -> None:
    entries = build_model_entries_by_provider(provider='openai', api_key='sk-test')
    names = {entry.name for entry in entries['openai']}
    assert 'gpt-5' in names
    mock_fetch.assert_not_called()


@patch('backend.inference.registry.fetch_remote_models', return_value=['remote-only'])
def test_list_model_names_catalog_first_without_remote_opt_in(mock_fetch) -> None:
    names = list_model_names('groq', api_key='gsk_test')
    assert 'llama-3.3-70b-versatile' in names
    assert 'remote-only' not in names
    mock_fetch.assert_not_called()


@patch('backend.inference.registry.fetch_remote_models', return_value=['remote-only'])
def test_list_model_names_merges_remote_when_opted_in(mock_fetch) -> None:
    names = list_model_names('groq', api_key='gsk_test', include_remote=True)
    assert 'llama-3.3-70b-versatile' in names
    assert 'remote-only' in names
    mock_fetch.assert_called_once()
