"""Integration tests for unified remote model listing (registry + backends).

Exercises the full path from ``fetch_remote_models`` / ``list_model_names`` through
``model_list_backends.list_models_for_provider`` with mocked HTTP/SDK boundaries.
No live API keys or network calls are required.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.inference import registry
from backend.inference.model_list_backends import (
    OPENAI_COMPAT_PROVIDERS,
    list_models_for_provider,
    resolve_listing_base_url,
)
from backend.inference.registry import (
    build_model_entries_by_provider,
    fetch_remote_models,
    list_model_names,
)

_OPENAI_MODELS_PAYLOAD = {
    'data': [
        {'id': 'gpt-4o-mini'},
        {'id': 'gpt-4o'},
        {'id': ''},
        {'not_id': 'skip-me'},
    ]
}


@contextmanager
def _mock_httpx_get(
    *,
    status_code: int = 200,
    json_payload: dict[str, Any] | None = None,
    side_effect: Exception | None = None,
) -> Iterator[MagicMock]:
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_payload or _OPENAI_MODELS_PAYLOAD

    mock_client = MagicMock()
    if side_effect is not None:
        mock_client.get.side_effect = side_effect
    else:
        mock_client.get.return_value = mock_response
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch('backend.inference.model_list_backends.httpx.Client') as mock_cls:
        mock_cls.return_value = mock_client
        yield mock_client


@pytest.fixture(autouse=True)
def _clear_remote_model_cache() -> Iterator[None]:
    registry._remote_model_cache.clear()
    yield
    registry._remote_model_cache.clear()


@pytest.mark.integration
class TestOpenAICompatListingBackend:
    @pytest.mark.parametrize('provider', sorted(OPENAI_COMPAT_PROVIDERS))
    def test_list_models_parses_openai_compat_response(self, provider: str) -> None:
        with _mock_httpx_get() as client:
            models = list_models_for_provider(
                provider,
                api_key='sk-test-key',
            )

        assert models == ['gpt-4o', 'gpt-4o-mini']
        expected_base = resolve_listing_base_url(provider) or ''
        client.get.assert_called_once()
        called_url = client.get.call_args[0][0]
        assert called_url == f'{expected_base}/models'
        headers = client.get.call_args[1]['headers']
        assert headers['Authorization'] == 'Bearer sk-test-key'

    def test_missing_api_key_returns_empty(self) -> None:
        with _mock_httpx_get() as client:
            assert list_models_for_provider('groq', api_key=None) == []
        client.get.assert_not_called()

    def test_http_error_returns_empty(self) -> None:
        with _mock_httpx_get(status_code=401):
            assert list_models_for_provider('groq', api_key='gsk_test') == []

    def test_connection_error_returns_empty(self) -> None:
        with _mock_httpx_get(side_effect=httpx.ConnectError('offline')):
            assert list_models_for_provider('groq', api_key='gsk_test') == []

    def test_custom_base_url_overrides_default(self) -> None:
        custom = 'https://proxy.example/v1'
        with _mock_httpx_get() as client:
            models = list_models_for_provider(
                'groq',
                api_key='gsk_test',
                base_url=custom,
            )
        assert models == ['gpt-4o', 'gpt-4o-mini']
        assert client.get.call_args[0][0] == f'{custom}/models'


@pytest.mark.integration
class TestAnthropicListingBackend:
    def test_list_models_uses_anthropic_api(self) -> None:
        payload = {'data': [{'id': 'claude-sonnet-4-6'}, {'id': 'claude-haiku-4-5'}]}
        with _mock_httpx_get(json_payload=payload) as client:
            models = list_models_for_provider('anthropic', api_key='sk-ant-test')

        assert models == ['claude-haiku-4-5', 'claude-sonnet-4-6']
        client.get.assert_called_once_with(
            'https://api.anthropic.com/v1/models',
            headers={
                'x-api-key': 'sk-ant-test',
                'anthropic-version': '2023-06-01',
            },
        )


@pytest.mark.integration
class TestGoogleListingBackend:
    def test_list_models_filters_embedding_models(self) -> None:
        chat = MagicMock()
        chat.name = 'models/gemini-2.5-pro'
        embed = MagicMock()
        embed.name = 'models/text-embedding-004'

        mock_pager = MagicMock()
        mock_pager.__iter__ = MagicMock(return_value=iter([chat, embed]))

        mock_client = MagicMock()
        mock_client.models.list.return_value = mock_pager

        with patch('google.genai.Client', return_value=mock_client):
            models = list_models_for_provider('google', api_key='AIza-test')

        assert models == ['gemini-2.5-pro']
        mock_client.models.list.assert_called_once()


@pytest.mark.integration
class TestLocalListingBackend:
    def test_ollama_routes_to_provider_resolver(self) -> None:
        with patch(
            'backend.inference.provider_resolver.get_resolver'
        ) as mock_get_resolver:
            mock_get_resolver.return_value.get_available_local_models.return_value = [
                'llama3.2',
                'qwen2.5-coder',
            ]
            models = list_models_for_provider('ollama')

        assert models == ['llama3.2', 'qwen2.5-coder']
        mock_get_resolver.return_value.get_available_local_models.assert_called_once_with(
            'ollama'
        )


@pytest.mark.integration
class TestRegistryRemoteListingIntegration:
    def test_fetch_remote_models_caches_by_provider_and_key_prefix(self) -> None:
        with _mock_httpx_get(json_payload={'data': [{'id': 'remote-only'}]}) as client:
            first = fetch_remote_models('groq', 'gsk_cache_test_1')
            second = fetch_remote_models('groq', 'gsk_cache_test_1')

        assert first == ['remote-only']
        assert second == ['remote-only']
        assert client.get.call_count == 1

    def test_fetch_remote_models_bypasses_cache_when_disabled(self) -> None:
        with _mock_httpx_get(json_payload={'data': [{'id': 'remote-only'}]}) as client:
            fetch_remote_models('groq', 'gsk_nocache_1', use_cache=False)
            fetch_remote_models('groq', 'gsk_nocache_1', use_cache=False)

        assert client.get.call_count == 2

    def test_list_model_names_merges_catalog_and_remote_without_duplicates(
        self,
    ) -> None:
        catalog_model = 'llama-3.3-70b-versatile'
        with _mock_httpx_get(
            json_payload={'data': [{'id': catalog_model}, {'id': 'remote-extra'}]}
        ):
            names = list_model_names(
                'groq', api_key='gsk_merge_test', include_remote=True
            )

        assert catalog_model in names
        assert 'remote-extra' in names
        assert len(names) == len(set(names))
        assert names.index(catalog_model) < names.index('remote-extra')

    def test_build_model_entries_adds_remote_synthetic_entries(self) -> None:
        with _mock_httpx_get(json_payload={'data': [{'id': 'only-from-api'}]}):
            by_provider = build_model_entries_by_provider(
                provider='groq',
                api_key='gsk_entries_test',
                include_remote=True,
            )

        names = {entry.name for entry in by_provider['groq']}
        assert 'only-from-api' in names

    def test_unknown_provider_with_base_url_uses_openai_compat(self) -> None:
        custom = 'https://custom-inference.example/v1'
        with _mock_httpx_get(json_payload={'data': [{'id': 'custom-model'}]}) as client:
            models = fetch_remote_models(
                'replicate',
                'rk_test_key',
                base_url=custom,
            )

        assert models == ['custom-model']
        assert client.get.call_args[0][0] == f'{custom}/models'

    def test_hosted_provider_without_key_skips_remote_listing(self) -> None:
        with _mock_httpx_get() as client:
            assert fetch_remote_models('groq', None) == []
            names = list_model_names('groq', api_key=None, include_remote=True)

        client.get.assert_not_called()
        assert 'llama-3.3-70b-versatile' in names

    def test_fetch_remote_models_passes_resolved_default_base_url(self) -> None:
        with _mock_httpx_get(json_payload={'data': [{'id': 'gpt-4o'}]}) as client:
            models = fetch_remote_models('openai', 'sk-openai-test')

        assert models == ['gpt-4o']
        assert client.get.call_args[0][0] == 'https://api.openai.com/v1/models'

    def test_fetch_remote_models_cache_key_uses_resolved_base_url(self) -> None:
        with _mock_httpx_get(json_payload={'data': [{'id': 'gpt-4o'}]}) as client:
            fetch_remote_models('openai', 'sk_cache_openai')
            fetch_remote_models('openai', 'sk_cache_openai')

        assert client.get.call_count == 1
        cache_key = next(iter(registry._remote_model_cache))
        assert cache_key[0] == 'openai'
        assert cache_key[1] == 'https://api.openai.com/v1'

    def test_explicit_base_url_overrides_default_in_fetch(self) -> None:
        custom = 'https://proxy.example/v1'
        with _mock_httpx_get(json_payload={'data': [{'id': 'proxied'}]}) as client:
            models = fetch_remote_models('groq', 'gsk_override', base_url=custom)

        assert models == ['proxied']
        assert client.get.call_args[0][0] == f'{custom}/models'
        cache_key = next(iter(registry._remote_model_cache))
        assert cache_key[1] == custom


@pytest.mark.integration
class TestResolveListingBaseUrl:
    def test_openai_falls_back_to_public_api_root(self) -> None:
        assert resolve_listing_base_url('openai') == 'https://api.openai.com/v1'

    def test_groq_uses_registry_default(self) -> None:
        assert resolve_listing_base_url('groq') == 'https://api.groq.com/openai/v1'

    def test_explicit_override_wins(self) -> None:
        custom = 'https://custom.example/v1'
        assert resolve_listing_base_url('groq', custom) == custom

    def test_local_providers_return_none(self) -> None:
        assert resolve_listing_base_url('ollama') is None
