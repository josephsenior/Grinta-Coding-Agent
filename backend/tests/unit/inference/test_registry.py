"""Unit tests for backend.inference.registry."""

from __future__ import annotations

from unittest.mock import patch

from backend.inference.catalog.provider_catalog import (
    build_model_entries_by_provider,
    get_listable_providers,
    get_provider_ids,
    get_static_model_names,
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
    assert 'digitalocean' in providers
    assert set(get_provider_ids()).issubset(set(providers))


def test_groq_static_catalog() -> None:
    models = get_static_model_names('groq')
    assert 'llama-3.3-70b-versatile' in models


def test_provider_label_local() -> None:
    assert provider_label('lm_studio') == 'LM Studio'


def test_build_model_entries_uses_catalog() -> None:
    entries = build_model_entries_by_provider(provider='mistral')
    assert 'mistral-large-latest' in {e.name for e in entries['mistral']}


def test_list_model_names_returns_catalog_for_hosted() -> None:
    names = list_model_names('groq')
    assert 'llama-3.3-70b-versatile' in names


@patch('backend.inference.registry.get_local_model_names', return_value=['llama3.2'])
def test_list_model_names_probes_local(mock_local) -> None:
    names = list_model_names('ollama')
    assert names == ['llama3.2']
    mock_local.assert_called_once_with('ollama')


@patch('backend.inference.registry.get_local_model_names', return_value=[])
def test_build_model_entries_local_probe(mock_local) -> None:
    entries = build_model_entries_by_provider(provider='ollama')
    assert entries['ollama'] == []
    mock_local.assert_called_once_with('ollama')
