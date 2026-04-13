from unittest.mock import MagicMock, patch

from backend.inference.direct_clients import get_direct_client


class TestOpenAICompatibleMetadataRouting:
    @patch('backend.inference.direct_clients.AsyncOpenAI')
    @patch('backend.inference.direct_clients.OpenAI')
    @patch(
        'backend.inference.direct_clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.direct_clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_default_openai_endpoint_keeps_metadata(self, _h, _ah, _oai, _aoai):
        client = get_direct_client('gpt-4o', api_key='sk-test')
        assert client._profile.supports_request_metadata is True  # type: ignore

    @patch('backend.inference.direct_clients.AsyncOpenAI')
    @patch('backend.inference.direct_clients.OpenAI')
    @patch(
        'backend.inference.direct_clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.direct_clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_custom_openai_compatible_endpoint_disables_metadata(
        self, _h, _ah, _oai, _aoai
    ):
        client = get_direct_client(
            'openai/my-model',
            api_key='key',
            base_url='http://localhost:8080/v1',
        )
        assert client._profile.supports_request_metadata is False  # type: ignore

    @patch('backend.inference.direct_clients.AsyncOpenAI')
    @patch('backend.inference.direct_clients.OpenAI')
    @patch(
        'backend.inference.direct_clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.direct_clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_lightning_route_with_openai_prefix_disables_metadata(
        self, _h, _ah, _oai, _aoai
    ):
        client = get_direct_client(
            'openai/google/gemini-3-flash-preview',
            api_key='key',
            base_url='https://lightning.ai/api/v1',
        )
        assert client._profile.supports_request_metadata is False  # type: ignore
