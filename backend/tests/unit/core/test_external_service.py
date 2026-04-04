"""Tests for backend.core.external_service — ExternalServiceBase."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.external_service import ExternalServiceBase


class TestExternalServiceInit:
    def test_defaults(self):
        svc = ExternalServiceBase()
        assert svc.endpoint is None
        assert svc.api_key is None
        assert svc.enabled is False
        assert svc._session is None

    def test_custom_values(self):
        svc = ExternalServiceBase(
            endpoint='https://example.com/api',
            api_key='secret',
            enabled=True,
        )
        assert svc.endpoint == 'https://example.com/api'
        assert svc.api_key == 'secret'
        assert svc.enabled is True


class TestIsReady:
    def test_not_ready_when_disabled(self):
        svc = ExternalServiceBase(endpoint='http://x.com', enabled=False)
        assert svc._is_ready() is False

    def test_not_ready_when_no_endpoint(self):
        svc = ExternalServiceBase(endpoint=None, enabled=True)
        assert svc._is_ready() is False

    def test_not_ready_when_empty_endpoint(self):
        svc = ExternalServiceBase(endpoint='', enabled=True)
        assert svc._is_ready() is False

    def test_ready(self):
        svc = ExternalServiceBase(endpoint='http://x.com', enabled=True)
        assert svc._is_ready() is True


class TestGetParsedEndpoint:
    def test_parses_valid_url(self):
        svc = ExternalServiceBase(endpoint='https://api.example.com/events')
        parsed = svc._get_parsed_endpoint()
        assert parsed.scheme == 'https'
        assert parsed.netloc == 'api.example.com'
        assert parsed.path == '/events'

    def test_parses_none_endpoint(self):
        svc = ExternalServiceBase(endpoint=None)
        parsed = svc._get_parsed_endpoint()
        assert parsed.scheme == ''
        assert parsed.netloc == ''


class TestGetAuthHeaders:
    def _make_svc(self, api_key=None):
        return ExternalServiceBase(api_key=api_key)

    def test_no_api_key(self):
        svc = self._make_svc(api_key=None)
        from urllib.parse import urlparse

        parsed = urlparse('https://api.example.com/events')
        headers = svc._get_auth_headers(parsed)
        assert headers == {'Content-Type': 'application/json'}
        assert 'Authorization' not in headers

    def test_pagerduty_token(self):
        svc = self._make_svc(api_key='my_pd_key')
        from urllib.parse import urlparse

        parsed = urlparse('https://events.pagerduty.com/v2/enqueue')
        headers = svc._get_auth_headers(parsed)
        assert headers['Authorization'] == 'Token token=my_pd_key'

    def test_datadog_header(self):
        svc = self._make_svc(api_key='dd_key')
        from urllib.parse import urlparse

        parsed = urlparse('https://http-intake.logs.datadog.com/api/v2')
        headers = svc._get_auth_headers(parsed)
        assert headers['DD-API-KEY'] == 'dd_key'

    def test_logzio_header(self):
        svc = self._make_svc(api_key='logz_key')
        from urllib.parse import urlparse

        parsed = urlparse('https://listener.logzio.io')
        headers = svc._get_auth_headers(parsed)
        assert headers['X-API-KEY'] == 'logz_key'

    def test_generic_bearer(self):
        svc = self._make_svc(api_key='generic_key')
        from urllib.parse import urlparse

        parsed = urlparse('https://custom-service.example.com/events')
        headers = svc._get_auth_headers(parsed)
        assert headers['Authorization'] == 'Bearer generic_key'


class TestGetSession:
    @pytest.mark.asyncio
    async def test_creates_session(self):
        svc = ExternalServiceBase(endpoint='http://x.com', enabled=True)
        assert svc._session is None
        with patch(
            'backend.core.external_service.aiohttp.ClientSession'
        ) as MockSession:
            mock_instance = MagicMock()
            mock_instance.closed = False
            MockSession.return_value = mock_instance
            session = await svc._get_session()
            assert session is mock_instance
            assert svc._session is mock_instance

    @pytest.mark.asyncio
    async def test_reuses_open_session(self):
        svc = ExternalServiceBase(endpoint='http://x.com', enabled=True)
        mock_session = MagicMock()
        mock_session.closed = False
        svc._session = mock_session
        session = await svc._get_session()
        assert session is mock_session

    @pytest.mark.asyncio
    async def test_recreates_closed_session(self):
        svc = ExternalServiceBase(endpoint='http://x.com', enabled=True)
        old_session = MagicMock()
        old_session.closed = True
        svc._session = old_session

        with patch(
            'backend.core.external_service.aiohttp.ClientSession'
        ) as MockSession:
            new_session = MagicMock()
            new_session.closed = False
            MockSession.return_value = new_session
            session = await svc._get_session()
            assert session is new_session


class TestPrepareRequest:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_ready(self):
        svc = ExternalServiceBase(endpoint=None, enabled=False)
        result = await svc._prepare_request()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_tuple_when_ready(self):
        svc = ExternalServiceBase(
            endpoint='https://api.example.com', api_key='key', enabled=True
        )
        with patch(
            'backend.core.external_service.aiohttp.ClientSession'
        ) as MockSession:
            mock_instance = MagicMock()
            mock_instance.closed = False
            MockSession.return_value = mock_instance
            result = await svc._prepare_request()
            assert result is not None
            session, parsed, headers = result
            assert session is mock_instance
            assert parsed.netloc == 'api.example.com'
            assert 'Authorization' in headers


class TestSendRequest:
    @pytest.mark.asyncio
    async def test_returns_false_when_not_ready(self):
        svc = ExternalServiceBase(endpoint=None, enabled=False)
        result = await svc._send_request(
            build_payload=lambda p: {},
            execute_request=AsyncMock(return_value=True),
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_executes_request_and_returns_result(self):
        svc = ExternalServiceBase(
            endpoint='https://api.example.com', api_key='k', enabled=True
        )
        execute = AsyncMock(return_value=True)

        with patch(
            'backend.core.external_service.aiohttp.ClientSession'
        ) as MockSession:
            mock_instance = MagicMock()
            mock_instance.closed = False
            MockSession.return_value = mock_instance
            result = await svc._send_request(
                build_payload=lambda p: {'data': 'test'},
                execute_request=execute,
            )
            assert result is True
            execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        svc = ExternalServiceBase(
            endpoint='https://api.example.com', api_key='k', enabled=True
        )
        execute = AsyncMock(side_effect=RuntimeError('network error'))

        with patch(
            'backend.core.external_service.aiohttp.ClientSession'
        ) as MockSession:
            mock_instance = MagicMock()
            mock_instance.closed = False
            MockSession.return_value = mock_instance
            result = await svc._send_request(
                build_payload=lambda p: {},
                execute_request=execute,
                error_msg='Test error',
            )
            assert result is False
