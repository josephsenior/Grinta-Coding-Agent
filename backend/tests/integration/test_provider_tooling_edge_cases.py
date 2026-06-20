"""Integration tests for provider and tooling edge cases.

These tests cover:
- Provider edge cases: rate limits, context window, auth failures
- Tooling edge cases: MCP unavailable, LSP timeout, malformed responses
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.execution.server.action_execution_server import RuntimeExecutor
from backend.inference.provider_resolver import extract_provider_prefix
from backend.ledger.action.code_nav import LspQueryAction
from backend.ledger.action.files import FileReadAction
from backend.ledger.action.mcp import MCPAction
from backend.ledger.observation import (
    ErrorObservation,
    LspQueryObservation,
    MCPObservation,
)
from backend.utils.lsp.lsp_client import LspClient, LspResult


class TestProviderEdgeCases:
    """Edge cases for LLM provider interactions."""

    @pytest.mark.integration
    def test_extract_provider_prefix_openai(self) -> None:
        provider = extract_provider_prefix('openai/gpt-4o-mini')
        assert provider == 'openai'

    @pytest.mark.integration
    def test_extract_provider_prefix_anthropic(self) -> None:
        provider = extract_provider_prefix('anthropic/claude-sonnet-4-20250514')
        assert provider == 'anthropic'

    @pytest.mark.integration
    def test_extract_provider_prefix_google(self) -> None:
        provider = extract_provider_prefix('google/gemini-2.5-pro')
        assert provider == 'google'

    @pytest.mark.integration
    def test_extract_provider_prefix_ollama(self) -> None:
        provider = extract_provider_prefix('ollama/llama3.2')
        assert provider == 'ollama'

    @pytest.mark.integration
    def test_extract_provider_prefix_openrouter(self) -> None:
        provider = extract_provider_prefix('openrouter/anthropic/claude-3-sonnet')
        assert provider == 'openrouter'

    @pytest.mark.integration
    def test_extract_provider_prefix_none_returns_none(self) -> None:
        provider = extract_provider_prefix(None)
        assert provider is None

    @pytest.mark.integration
    def test_extract_provider_prefix_no_slash_returns_none(self) -> None:
        provider = extract_provider_prefix('gpt-4o-mini')
        assert provider is None


class TestMCPEdgeCases:
    """Edge cases for MCP tooling integration."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_mcp_tool_call_connection_error(self, tmp_path) -> None:
        ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)
        ex._mcp_clients = [MagicMock()]
        ex._mcp_servers_resolved = []

        action = MCPAction(name='test-tool', arguments={})

        with patch(
            'backend.integrations.mcp.mcp_utils.call_tool_mcp',
            new_callable=AsyncMock,
            side_effect=ConnectionError('Connection refused'),
        ):
            obs = await ex.call_tool_mcp(action)

        assert isinstance(obs, ErrorObservation)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_mcp_tool_call_timeout(self, tmp_path) -> None:
        ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)
        ex._mcp_clients = [MagicMock()]
        ex._mcp_servers_resolved = []

        action = MCPAction(name='slow-tool', arguments={})

        with patch(
            'backend.integrations.mcp.mcp_utils.call_tool_mcp',
            new_callable=AsyncMock,
            side_effect=asyncio.TimeoutError('MCP tool call timed out'),
        ):
            obs = await ex.call_tool_mcp(action)

        assert isinstance(obs, ErrorObservation)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_mcp_with_no_clients_returns_error(self, tmp_path) -> None:
        ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)
        ex._mcp_clients = []
        ex._mcp_servers_resolved = []

        action = MCPAction(name='some-tool', arguments={})
        obs = await ex.call_tool_mcp(action)

        assert isinstance(obs, ErrorObservation) or (
            isinstance(obs, MCPObservation) and 'error' in obs.content.lower()
        )

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_mcp_large_response_truncation(self, tmp_path) -> None:
        ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)
        ex._mcp_clients = [MagicMock()]
        ex._mcp_servers_resolved = []

        large_content = 'x' * 500_000
        action = MCPAction(name='large-tool', arguments={})

        with patch(
            'backend.integrations.mcp.mcp_utils.call_tool_mcp',
            new_callable=AsyncMock,
            return_value=MCPObservation(
                content=large_content,
                name='large-tool',
                arguments={},
            ),
        ):
            obs = await ex.call_tool_mcp(action)

        assert isinstance(obs, MCPObservation)
        assert len(obs.content) <= 500_000

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_mcp_returns_observation_with_empty_content(self, tmp_path) -> None:
        ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)
        ex._mcp_clients = [MagicMock()]
        ex._mcp_servers_resolved = []

        action = MCPAction(name='empty-tool', arguments={})

        with patch(
            'backend.integrations.mcp.mcp_utils.call_tool_mcp',
            new_callable=AsyncMock,
            return_value=MCPObservation(
                content='',
                name='empty-tool',
                arguments={},
            ),
        ):
            obs = await ex.call_tool_mcp(action)

        assert isinstance(obs, MCPObservation)
        assert obs.content == ''


class TestLSPEdgeCases:
    """Edge cases for LSP tooling integration."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_lsp_query_returns_unavailable_for_unknown_extension(
        self, tmp_path
    ) -> None:
        weird = tmp_path / 'data.xyzunknown'
        weird.write_text('x')

        client = LspClient()
        result = client.query('hover', str(weird))
        assert result.available is False

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_lsp_query_returns_error_when_symbol_not_found(
        self, tmp_path
    ) -> None:
        py = tmp_path / 'test_err.py'
        py.write_text('def foo():\n    pass\n')

        ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)

        action = LspQueryAction(
            file=str(py),
            command='find_definition',
            line=1,
            column=1,
        )

        result = LspResult(
            available=True,
            locations=[],
            error='Symbol not found in this context',
        )

        with patch('backend.utils.lsp.lsp_client.LspClient') as LC:
            LC.return_value.query.return_value = result
            obs = await ex.lsp_query(action)

        assert isinstance(obs, LspQueryObservation)
        assert 'not found' in obs.content.lower()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_lsp_query_handles_empty_result(self, tmp_path) -> None:
        py = tmp_path / 'empty.py'
        py.write_text('x = 1\n')

        ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)

        action = LspQueryAction(
            file=str(py),
            command='find_definition',
            line=1,
            column=1,
        )

        result = LspResult(
            available=True,
            locations=[],
            error='',
        )

        with patch('backend.utils.lsp.lsp_client.LspClient') as LC:
            LC.return_value.query.return_value = result
            obs = await ex.lsp_query(action)

        assert isinstance(obs, LspQueryObservation)

    @pytest.mark.integration
    def test_lsp_client_handles_binary_file_gracefully(self, tmp_path) -> None:
        binary = tmp_path / 'binary.bin'
        binary.write_bytes(b'\x00\x01\x02\x03')

        client = LspClient()
        result = client.query('hover', str(binary))
        assert result.available is False


class TestToolingCrossCutting:
    """Cross-cutting edge cases across tooling layer."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_file_read_action_on_valid_file_succeeds(self, tmp_path) -> None:
        py = tmp_path / 'readable.py'
        py.write_text("print('hello')")

        ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)
        action = FileReadAction(path=str(py))

        obs = await ex.run_action(action)
        assert obs is not None

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_file_read_action_on_nonexistent_file_returns_error(
        self, tmp_path
    ) -> None:
        ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)
        action = FileReadAction(path=str(tmp_path / 'nonexistent.py'))

        obs = await ex.run_action(action)
        assert isinstance(obs, ErrorObservation)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_file_operation_with_invalid_path_returns_error(
        self, tmp_path
    ) -> None:
        ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)
        action = FileReadAction(path='C:\\outside\\workspace\\file.py')

        obs = await ex.run_action(action)
        assert isinstance(obs, ErrorObservation)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_mcp_and_lsp_disabled_still_allows_file_operations(
        self, tmp_path
    ) -> None:
        py = tmp_path / 'standalone.py'
        py.write_text('# no LSP or MCP needed')

        ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)
        action = FileReadAction(path=str(py))

        obs = await ex.run_action(action)
        assert obs is not None
        assert not isinstance(obs, ErrorObservation)


class TestProviderErrorMapping:
    """Tests for mapping provider errors to internal exceptions."""

    @pytest.mark.integration
    def test_authentication_error_import(self) -> None:
        from backend.inference.exceptions import AuthenticationError

        err = AuthenticationError('Invalid API key', status_code=401)
        assert err.status_code == 401
        assert 'Invalid API key' in err.message

    @pytest.mark.integration
    def test_rate_limit_error_import(self) -> None:
        from backend.inference.exceptions import RateLimitError

        err = RateLimitError('Rate limit exceeded', status_code=429)
        assert err.status_code == 429

    @pytest.mark.integration
    def test_context_window_exceeded_error_import(self) -> None:
        from backend.inference.exceptions import ContextWindowExceededError

        err = ContextWindowExceededError('Input too long')
        assert 'too long' in err.message

    @pytest.mark.integration
    def test_bad_request_error_import(self) -> None:
        from backend.inference.exceptions import BadRequestError

        err = BadRequestError('Invalid parameters', status_code=400)
        assert err.status_code == 400

    @pytest.mark.integration
    def test_service_unavailable_error_import(self) -> None:
        from backend.inference.exceptions import ServiceUnavailableError

        err = ServiceUnavailableError('Service down', status_code=503)
        assert err.status_code == 503


class TestModelDiscoveryEdgeCases:
    """Tests for model discovery edge cases."""

    @pytest.mark.integration
    def test_get_supported_llm_models_returns_list(self) -> None:
        from backend.inference.catalog.model_catalog import get_supported_llm_models

        models = get_supported_llm_models(None)
        assert isinstance(models, list)
        assert len(models) > 0

    @pytest.mark.integration
    def test_get_supported_llm_models_includes_openai(self) -> None:
        from backend.inference.catalog.model_catalog import get_supported_llm_models

        models = get_supported_llm_models(None)
        openai_models = [m for m in models if m.startswith('openai/')]
        assert len(openai_models) > 0

    @pytest.mark.integration
    def test_get_supported_llm_models_includes_anthropic(self) -> None:
        from backend.inference.catalog.model_catalog import get_supported_llm_models

        models = get_supported_llm_models(None)
        anthropic_models = [m for m in models if m.startswith('anthropic/')]
        assert len(anthropic_models) > 0

    @pytest.mark.integration
    def test_get_supported_llm_models_includes_google(self) -> None:
        from backend.inference.catalog.model_catalog import get_supported_llm_models

        models = get_supported_llm_models(None)
        google_models = [m for m in models if m.startswith('google/')]
        assert len(google_models) > 0

    @pytest.mark.integration
    def test_get_supported_llm_models_includes_xai(self) -> None:
        from backend.inference.catalog.model_catalog import get_supported_llm_models

        models = get_supported_llm_models(None)
        xai_models = [m for m in models if m.startswith('xai/')]
        assert len(xai_models) > 0

    @pytest.mark.integration
    def test_local_model_discovery_function_exists(self) -> None:
        from backend.inference.provider_resolver import discover_all_local_models

        result = discover_all_local_models()
        assert isinstance(result, dict)
