from unittest.mock import AsyncMock, patch

import pytest

from backend.cli.config_manager import _test_llm_call
from backend.inference.exceptions import AuthenticationError, NotFoundError, Timeout


@pytest.mark.asyncio
async def test_test_llm_call_routes_through_direct_client() -> None:
    client = AsyncMock()

    with patch(
        'backend.inference.direct_clients.get_direct_client', return_value=client
    ) as get_direct_client:
        result = await _test_llm_call('anthropic/claude-sonnet-4.6', 'key', None)

    assert result is True
    get_direct_client.assert_called_once_with(
        model='anthropic/claude-sonnet-4.6',
        api_key='key',
        base_url=None,
        timeout=15.0,
    )
    client.acompletion.assert_awaited_once()
    assert client.acompletion.call_args.kwargs['model'] == 'anthropic/claude-sonnet-4.6'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('exc', 'message'),
    [
        (Timeout('slow'), 'Connection timed out'),
        (AuthenticationError('bad key'), 'Invalid API key'),
        (NotFoundError('missing'), 'Model not found: gemini-3-flash-preview'),
    ],
)
async def test_test_llm_call_maps_direct_client_errors(exc: Exception, message: str) -> None:
    client = AsyncMock()
    client.acompletion.side_effect = exc

    with patch('backend.inference.direct_clients.get_direct_client', return_value=client):
        result = await _test_llm_call('google/gemini-3-flash-preview', 'key', None)

    assert isinstance(result, str)
    assert message in result
