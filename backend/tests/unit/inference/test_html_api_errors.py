"""Tests for HTML-instead-of-JSON LLM error formatting."""

from unittest.mock import MagicMock, patch

from backend.inference.direct_clients import OpenAIClient, TransportProfile
from backend.inference.exceptions import (
    AuthenticationError,
    BadRequestError,
    format_html_api_error_response,
    is_html_api_body,
)
from backend.inference.llm import _map_provider_exception


def test_is_html_api_body() -> None:
    assert is_html_api_body('<!DOCTYPE html><html>')
    assert is_html_api_body('  \n<html lang="en">')
    assert not is_html_api_body('{"error": "invalid"}')
    assert not is_html_api_body('Error code: 401 - Unauthorized')


def test_format_html_api_error_response_includes_hints() -> None:
    msg = format_html_api_error_response(
        '<!DOCTYPE html><html><body>oops</body></html>',
        base_url='https://lightning.ai/api/v1',
        model='google/gemini-3-flash-preview',
    )
    assert 'HTML' in msg
    assert 'lightning.ai' in msg
    assert 'gemini-3-flash' in msg
    assert 'llm_base_url' in msg


def test_openai_client_maps_html_to_bad_request() -> None:
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
    def _run(_h, _ah, _oai, _aoai):
        client = OpenAIClient(
            'google/gemini-3-flash-preview',
            'key',
            base_url='https://lightning.ai/api/v1',
            profile=TransportProfile(),
        )
        exc = Exception('<!DOCTYPE html><html></html>')
        mapped = client._map_openai_error(exc)
        assert isinstance(mapped, BadRequestError)
        assert 'HTML' in str(mapped)
        assert 'lightning.ai' in str(mapped)

    _run()


def test_openai_client_maps_html_401_to_auth() -> None:
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
    def _run(_h, _ah, _oai, _aoai):
        client = OpenAIClient('m', 'k', base_url='https://example.com/v1')

        class Html401(Exception):
            status_code = 401

        mapped = client._map_openai_error(Html401('<!DOCTYPE html><title>Login</title>'))
        assert isinstance(mapped, AuthenticationError)

    _run()


def test_map_provider_exception_html_fallback() -> None:
    mapped = _map_provider_exception(
        RuntimeError('<!DOCTYPE html><html><body>x</body></html>'),
        'my-model',
    )
    assert 'HTML' in str(mapped)
