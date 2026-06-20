"""Integration tests for static catalog and local model listing."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.inference.catalog.provider_catalog import (
    build_model_entries_by_provider,
    list_model_names,
)


@pytest.mark.integration
class TestRegistryModelListing:
    def test_list_model_names_returns_catalog_for_hosted(self) -> None:
        names = list_model_names('groq')
        assert 'llama-3.3-70b-versatile' in names

    def test_build_model_entries_returns_catalog_for_hosted(self) -> None:
        by_provider = build_model_entries_by_provider(provider='openai')
        names = {entry.name for entry in by_provider['openai']}
        assert 'gpt-5' in names

    @patch('backend.inference.registry.get_local_model_names')
    def test_list_model_names_probes_local(self, mock_local) -> None:
        mock_local.return_value = ['llama3.2', 'qwen2.5-coder']
        names = list_model_names('ollama')
        assert names == ['llama3.2', 'qwen2.5-coder']
        mock_local.assert_called_once_with('ollama')

    @patch('backend.inference.provider_resolver.get_resolver')
    def test_local_listing_routes_to_provider_resolver(self, mock_get_resolver) -> None:
        mock_get_resolver.return_value.get_available_local_models.return_value = [
            'llama3.2',
            'qwen2.5-coder',
        ]
        names = list_model_names('ollama')
        assert names == ['llama3.2', 'qwen2.5-coder']
        mock_get_resolver.return_value.get_available_local_models.assert_called_once_with(
            'ollama'
        )
