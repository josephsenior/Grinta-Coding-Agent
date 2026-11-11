"""Unit tests for backend.inference.clients — factory routing and LLMResponse."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.inference.clients import (
    LLMResponse,
    _pool_key,
    get_direct_client,
)
from backend.inference.clients.codex_app_server import (
    CodexResponsesClient,
    _find_codex_executable,
)

# ---------------------------------------------------------------------------
# Helper: mock the SDK constructors to avoid real HTTP clients
# ---------------------------------------------------------------------------


def _mock_openai_sdk():
    """Return a patch context that makes OpenAI + AsyncOpenAI constructors no-ops."""
    return [
        patch('backend.inference.clients.OpenAI'),
        patch('backend.inference.clients.AsyncOpenAI'),
        patch(
            'backend.inference.clients.get_shared_http_client',
            return_value=MagicMock(spec=True),
        ),
        patch(
            'backend.inference.clients.get_shared_async_http_client',
            return_value=MagicMock(spec=True),
        ),
    ]


def test_codex_executable_resolution_accepts_windows_desktop_install() -> None:
    desktop_executable = (
        r'C:\Users\user\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe'
    )
    with (
        patch('backend.inference.clients.codex_app_server.sys.platform', 'win32'),
        patch(
            'backend.inference.clients.codex_app_server.shutil.which',
            side_effect=[None, desktop_executable],
        ) as which,
    ):
        assert _find_codex_executable() == desktop_executable

    assert which.call_args_list == [
        (('codex.cmd',),),
        (('codex.exe',),),
    ]


def test_codex_app_server_uses_file_credential_store() -> None:
    client = CodexResponsesClient()
    process = MagicMock()
    process.poll.return_value = None
    process.stdin = MagicMock()
    process.stdout = MagicMock()
    process.stderr = MagicMock()

    with (
        patch(
            'backend.inference.clients.codex_app_server._find_codex_executable',
            return_value='codex',
        ),
        patch(
            'backend.inference.clients.codex_app_server.subprocess.Popen',
            return_value=process,
        ) as popen,
        patch.object(client, '_request', return_value={}),
        patch.object(client, '_notify'),
    ):
        client._ensure_started()

    assert popen.call_args.args[0] == [
        'codex',
        'app-server',
        '--stdio',
        '--config',
        'cli_auth_credentials_store="file"',
    ]


def test_codex_model_list_uses_account_catalog() -> None:
    client = CodexResponsesClient()
    with (
        patch.object(client, '_ensure_started'),
        patch.object(client, '_ensure_authenticated_locked'),
        patch.object(
            client,
            '_request',
            side_effect=[
                {
                    'data': [
                        {
                            'id': 'first-id',
                            'model': 'gpt-5.6-luna',
                            'isDefault': True,
                        },
                        {'id': 'fallback-id'},
                    ],
                    'nextCursor': 'next',
                },
                {'data': [{'id': 'second-id', 'model': 'gpt-5.4-mini'}]},
            ],
        ),
    ):
        assert client.list_available_models() == [
            'gpt-5.6-luna',
            'fallback-id',
            'gpt-5.4-mini',
        ]
        assert client._resolved_model_name() == 'gpt-5.6-luna'


def test_codex_credentials_prefer_complete_auth_file(tmp_path) -> None:
    auth_path = tmp_path / 'auth.json'
    auth_path.write_text(
        json.dumps(
            {
                'auth_mode': 'chatgpt',
                'tokens': {
                    'access_token': 'access-token',
                    'account_id': 'account-id',
                },
            }
        ),
        encoding='utf-8',
    )
    client = CodexResponsesClient()

    with (
        patch.object(client, '_codex_home', return_value=tmp_path),
        patch.object(client, '_ensure_started') as ensure_started,
    ):
        assert client._credentials() == ('access-token', 'account-id')

    ensure_started.assert_not_called()


def test_codex_payload_uses_grinta_instructions_and_native_tools() -> None:
    client = CodexResponsesClient(model_name='gpt-5.6-sol')
    client._reasoning_by_call_id['call-1'] = [
        {
            'type': 'reasoning',
            'encrypted_content': 'opaque-state',
            'summary': [],
        }
    ]
    payload = client._build_payload(
        [
            {'role': 'system', 'content': 'You are the Grinta harness.'},
            {
                'role': 'assistant',
                'content': '',
                'tool_calls': [
                    {
                        'id': 'call-1',
                        'type': 'function',
                        'function': {'name': 'read', 'arguments': '{"path":"a.py"}'},
                    }
                ],
            },
            {
                'role': 'tool',
                'tool_call_id': 'call-1',
                'name': 'read',
                'content': 'print("ok")',
            },
        ],
        {
            'reasoning_effort': 'xhigh',
            'tools': [
                {
                    'type': 'function',
                    'function': {
                        'name': 'read',
                        'description': 'Read a file.',
                        'parameters': {
                            'type': 'object',
                            'properties': {'path': {'type': 'string'}},
                            'required': ['path'],
                        },
                    },
                }
            ],
            'tool_choice': 'auto',
            'parallel_tool_calls': True,
        },
    )

    assert payload['instructions'] == 'You are the Grinta harness.'
    assert payload['reasoning'] == {'effort': 'xhigh', 'summary': 'detailed'}
    assert payload['tools'][0]['name'] == 'read'
    assert 'function' not in payload['tools'][0]
    assert payload['parallel_tool_calls'] is True
    assert payload['input'] == [
        {
            'type': 'reasoning',
            'encrypted_content': 'opaque-state',
            'summary': [],
        },
        {
            'type': 'function_call',
            'call_id': 'call-1',
            'name': 'read',
            'arguments': '{"path":"a.py"}',
        },
        {
            'type': 'function_call_output',
            'call_id': 'call-1',
            'output': 'print("ok")',
        },
    ]


def test_codex_one_shot_completion_consumes_required_response_stream() -> None:
    events = [
        {'type': 'response.created', 'response': {'id': 'resp-1'}},
        {'type': 'response.output_text.delta', 'delta': 'GRINTA_PROVIDER_OK'},
        {
            'type': 'response.completed',
            'response': {
                'id': 'resp-1',
                'model': 'gpt-5.6-sol',
                'status': 'completed',
                'output': [],
                'usage': {
                    'input_tokens': 5,
                    'output_tokens': 3,
                    'total_tokens': 8,
                },
            },
        },
    ]
    responses = SimpleNamespace(create=MagicMock(return_value=events))
    client = CodexResponsesClient(model_name='gpt-5.6-sol')
    with (
        patch.object(client, '_credentials', return_value=('token', 'account')),
        patch.object(
            client,
            '_sync_responses_client',
            return_value=SimpleNamespace(responses=responses),
        ),
    ):
        result = client.completion(
            [{'role': 'user', 'content': 'Reply with the marker.'}],
            max_tokens=32,
        )

    assert result.content == 'GRINTA_PROVIDER_OK'
    assert result.usage == {
        'prompt_tokens': 5,
        'completion_tokens': 3,
        'total_tokens': 8,
        'reasoning_tokens': 0,
    }
    responses.create.assert_called_once()
    assert responses.create.call_args.kwargs['stream'] is True
    assert 'max_output_tokens' not in responses.create.call_args.kwargs


def test_codex_complete_file_credentials_skip_broker_refresh(
    tmp_path,
) -> None:
    auth_path = tmp_path / 'auth.json'
    auth_path.write_text(
        json.dumps(
            {
                'auth_mode': 'chatgpt',
                'tokens': {
                    'access_token': 'secret-access',
                    'account_id': 'account-1',
                },
            }
        ),
        encoding='utf-8',
    )
    client = CodexResponsesClient()
    with (
        patch.object(client, '_ensure_started'),
        patch.object(client, '_ensure_authenticated_locked') as authenticate,
        patch.object(client, '_codex_home', return_value=tmp_path),
    ):
        assert client._credentials() == ('secret-access', 'account-1')
    authenticate.assert_not_called()


class _CodexAsyncStream:
    def __init__(self, events):
        self._events = iter(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._events)
        except StopIteration:
            raise StopAsyncIteration from None


@pytest.mark.asyncio
async def test_codex_stream_maps_reasoning_tools_and_usage_to_grinta() -> None:
    events = [
        {'type': 'response.created', 'response': {'id': 'resp-1'}},
        {
            'type': 'response.reasoning_summary_text.delta',
            'item_id': 'reasoning-1',
            'delta': 'Inspecting the request. ',
        },
        {
            'type': 'response.output_item.done',
            'output_index': 0,
            'item': {
                'type': 'reasoning',
                'encrypted_content': 'opaque-reasoning',
                'summary': [],
            },
        },
        {
            'type': 'response.output_item.added',
            'output_index': 1,
            'item': {
                'type': 'function_call',
                'id': 'item-1',
                'call_id': 'call-1',
                'name': 'read',
            },
        },
        {
            'type': 'response.function_call_arguments.delta',
            'output_index': 1,
            'item_id': 'item-1',
            'delta': '{"path":"a.py"}',
        },
        {
            'type': 'response.output_item.done',
            'output_index': 1,
            'item': {
                'type': 'function_call',
                'id': 'item-1',
                'call_id': 'call-1',
                'name': 'read',
                'arguments': '{"path":"a.py"}',
            },
        },
        {
            'type': 'response.completed',
            'response': {
                'id': 'resp-1',
                'output': [],
                'usage': {
                    'input_tokens': 100,
                    'output_tokens': 50,
                    'total_tokens': 150,
                    'output_tokens_details': {'reasoning_tokens': 40},
                },
            },
        },
    ]
    responses = SimpleNamespace(
        create=AsyncMock(return_value=_CodexAsyncStream(events))
    )
    client = CodexResponsesClient(model_name='gpt-5.6-sol')
    with (
        patch.object(client, '_credentials', return_value=('token', 'account')),
        patch.object(
            client,
            '_async_responses_client',
            return_value=SimpleNamespace(responses=responses),
        ),
    ):
        chunks = [
            chunk
            async for chunk in client.astream(
                [
                    {'role': 'system', 'content': 'Grinta'},
                    {'role': 'user', 'content': 'Read'},
                ],
                tools=[],
                reasoning_effort='high',
            )
        ]

    assert chunks[0]['choices'][0]['delta'] == {
        'reasoning_content': 'Inspecting the request. ',
        '_reasoning_item_id': 'reasoning-1',
    }
    tool_chunks = [
        chunk['choices'][0]['delta']['tool_calls'][0]
        for chunk in chunks
        if chunk.get('choices') and chunk['choices'][0]['delta'].get('tool_calls')
    ]
    assert tool_chunks[0]['id'] == 'call-1'
    assert tool_chunks[0]['function']['name'] == 'read'
    assert tool_chunks[1]['function']['arguments'] == '{"path":"a.py"}'
    assert chunks[-1]['usage']['reasoning_tokens'] == 40
    assert client._reasoning_by_call_id['call-1'][0]['encrypted_content'] == (
        'opaque-reasoning'
    )


# ---------------------------------------------------------------------------
# _pool_key
# ---------------------------------------------------------------------------


class TestPoolKey:
    def test_with_base_url(self):
        assert (
            _pool_key('openai', 'https://api.openai.com')
            == 'openai::https://api.openai.com'
        )

    def test_without_base_url(self):
        assert _pool_key('anthropic', None) == 'anthropic::default'


# ---------------------------------------------------------------------------
# LLMResponse
# ---------------------------------------------------------------------------


class TestLLMResponse:
    def test_construction(self):
        r = LLMResponse(
            content='Hello',
            model='gpt-4o',
            usage={'prompt_tokens': 10, 'completion_tokens': 5},
        )
        assert r.content == 'Hello'
        assert r.model == 'gpt-4o'
        assert r.usage == {'prompt_tokens': 10, 'completion_tokens': 5}
        assert r.finish_reason == 'stop'
        assert r.tool_calls is None

    def test_choices_attribute(self):
        r = LLMResponse(content='Hi', model='m', usage={})
        assert len(r.choices) == 1
        assert r.choices[0].message.content == 'Hi'
        assert r.choices[0].message.role == 'assistant'
        assert r.choices[0].finish_reason == 'stop'

    def test_to_dict(self):
        r = LLMResponse(content='reply', model='m', usage={'prompt_tokens': 1})
        d = r.to_dict()
        assert d['choices'][0]['message']['content'] == 'reply'
        assert d['choices'][0]['message']['role'] == 'assistant'
        assert d['model'] == 'm'

    def test_to_dict_includes_tool_calls(self):
        tc = [
            {
                'id': 't1',
                'type': 'function',
                'function': {'name': 'f', 'arguments': '{}'},
            }
        ]
        r = LLMResponse(content='', model='m', usage={}, tool_calls=tc)
        d = r.to_dict()
        assert d['choices'][0]['message']['tool_calls'] == tc

    def test_getitem_dict_access(self):
        r = LLMResponse(content='x', model='m', usage={})
        assert r['model'] == 'm'
        assert len(r['choices']) == 1

    def test_custom_finish_reason(self):
        r = LLMResponse(content='', model='m', usage={}, finish_reason='length')
        assert r.finish_reason == 'length'
        assert r.choices[0].finish_reason == 'length'


# ---------------------------------------------------------------------------
# get_direct_client — routing
# ---------------------------------------------------------------------------


class TestGetDirectClientRouting:
    """Verify factory routes models to the correct client classes."""

    @patch('backend.inference.clients.AsyncOpenAI')
    @patch('backend.inference.clients.OpenAI')
    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_openai_default(self, _h, _ah, _oai, _aoai):
        client = get_direct_client('openai/gpt-5', api_key='sk-test')
        assert type(client).__name__ == 'OpenAIClient'
        assert client._model_name == 'gpt-5'

    def test_codex_routes_to_responses_provider(self):
        client = get_direct_client('codex/default', api_key='')
        assert type(client).__name__ == 'CodexResponsesClient'
        assert client._model_name == 'default'

    @patch('backend.inference.clients.Anthropic')
    @patch('backend.inference.clients.AsyncAnthropic')
    def test_anthropic_routing(self, _async, _sync):
        client = get_direct_client('anthropic/claude-3.5-sonnet', api_key='key')
        assert type(client).__name__ == 'AnthropicClient'

    @patch('backend.inference.clients.Anthropic')
    @patch('backend.inference.clients.AsyncAnthropic')
    def test_claude_routing(self, _async, _sync):
        client = get_direct_client('anthropic/claude-sonnet-4-5', api_key='key')
        assert type(client).__name__ == 'AnthropicClient'

    @patch('backend.inference.providers.gemini_ops.genai')
    def test_gemini_alias_prefix_rejected(self, _genai):
        with pytest.raises(ValueError):
            get_direct_client('gemini/gemini-2.5-flash', api_key='key')

    @patch('backend.inference.providers.gemini_ops.genai')
    def test_google_routing(self, _genai):
        client = get_direct_client('google/gemini-1.5-pro', api_key='key')
        assert type(client).__name__ == 'GeminiClient'

    @patch('backend.inference.clients.AsyncOpenAI')
    @patch('backend.inference.clients.OpenAI')
    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_lightning_routing_strips_provider_prefix(self, _h, _ah, _oai, _aoai):
        client = get_direct_client(
            'lightning/google/gemini-3-flash-preview',
            api_key='key',
        )
        assert type(client).__name__ == 'OpenAIClient'
        assert client._model_name == 'google/gemini-3-flash-preview'

    @patch('backend.inference.clients.AsyncOpenAI')
    @patch('backend.inference.clients.OpenAI')
    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_xai_grok_routing(self, _h, _ah, _oai, _aoai):
        client = get_direct_client('xai/grok-3', api_key='key')
        assert type(client).__name__ == 'OpenAIClient'

    @patch('backend.inference.clients.AsyncOpenAI')
    @patch('backend.inference.clients.OpenAI')
    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_grok_routing(self, _h, _ah, _oai, _aoai):
        client = get_direct_client('xai/grok-build-0.1', api_key='key')
        assert type(client).__name__ == 'OpenAIClient'

    @patch('backend.inference.clients.AsyncOpenAI')
    @patch('backend.inference.clients.OpenAI')
    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_ollama_routing_strips_prefix(self, _h, _ah, _oai, _aoai):
        client = get_direct_client('ollama/llama3.2', api_key='')
        assert type(client).__name__ == 'OpenAIClient'
        assert client._model_name == 'llama3.2'

    @patch('backend.inference.clients.AsyncOpenAI')
    @patch('backend.inference.clients.OpenAI')
    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_ollama_defaults_base_url(self, _h, _ah, _oai, _aoai):
        client = get_direct_client('ollama/codestral', api_key='')
        assert client._model_name == 'codestral'

    @patch('backend.inference.clients.AsyncOpenAI')
    @patch('backend.inference.clients.OpenAI')
    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_ollama_custom_base_url_respected(self, _h, _ah, _oai, _aoai):
        client = get_direct_client(
            'ollama/phi3',
            api_key='',
            base_url='http://remote:11434/v1',
        )
        assert client._model_name == 'phi3'

    @patch('backend.inference.clients.AsyncOpenAI')
    @patch('backend.inference.clients.OpenAI')
    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_ollama_without_prefix(self, _h, _ah, _oai, _aoai):
        """Ambiguous local-looking names no longer route without an explicit prefix."""
        with pytest.raises(ValueError, match='Provider is ambiguous'):
            get_direct_client('ollama-test-model', api_key='')

    @patch('backend.inference.clients.AsyncOpenAI')
    @patch('backend.inference.clients.OpenAI')
    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_unknown_model_defaults_to_openai(self, _h, _ah, _oai, _aoai):
        with pytest.raises(ValueError, match='Provider is ambiguous'):
            get_direct_client('my-custom-model', api_key='key')

    @patch('backend.inference.clients.AsyncOpenAI')
    @patch('backend.inference.clients.OpenAI')
    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_explicit_custom_openai_model_routes(self, _h, _ah, _oai, _aoai):
        client = get_direct_client('openai/my-custom-model', api_key='key')
        assert type(client).__name__ == 'OpenAIClient'

    @patch('backend.inference.clients.AsyncOpenAI')
    @patch('backend.inference.clients.OpenAI')
    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_custom_base_url_passthrough(self, _h, _ah, _oai, _aoai):
        client = get_direct_client(
            'openai/my-model', api_key='key', base_url='http://localhost:8080/v1'
        )
        assert type(client).__name__ == 'OpenAIClient'

    @patch('backend.inference.clients.Anthropic')
    @patch('backend.inference.clients.AsyncAnthropic')
    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_opencode_go_minimax_routes_to_anthropic_messages(
        self, _h, _ah, _async_anth, _anth
    ):
        client = get_direct_client('opencode-go/minimax-m2.7', api_key='key')
        assert type(client).__name__ == 'AnthropicClient'
        assert client._model_name == 'minimax-m2.7'

    @patch('backend.inference.clients.AsyncOpenAI')
    @patch('backend.inference.clients.OpenAI')
    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_opencode_go_qwen_routes_to_openai_compatible(self, _h, _ah, _oai, _aoai):
        client = get_direct_client('opencode-go/deepseek-v4-flash', api_key='key')
        assert type(client).__name__ == 'OpenAIClient'
        assert client._model_name == 'deepseek-v4-flash'

    @pytest.mark.parametrize(
        ('provider', 'surface', 'expected'),
        [
            (
                'opencode',
                'openai',
                'https://opencode.ai/inference/openai/v1',
            ),
            (
                'opencode',
                'anthropic',
                'https://opencode.ai/inference/anthropic/v1',
            ),
            (
                'opencode',
                'google',
                'https://opencode.ai/inference/google/v1beta',
            ),
            (
                'opencode-go',
                'openai',
                'https://opencode.ai/inference/go/openai/v1',
            ),
            (
                'opencode-go',
                'anthropic',
                'https://opencode.ai/inference/go/anthropic/v1',
            ),
            (
                'opencode-go',
                'google',
                'https://opencode.ai/inference/go/google/v1beta',
            ),
        ],
    )
    def test_opencode_surface_base_urls(self, provider, surface, expected):
        from backend.inference.clients.factory import _opencode_surface_base_url

        assert _opencode_surface_base_url(provider, surface, None) == expected
        legacy = (
            'https://opencode.ai/zen/go/v1'
            if provider == 'opencode-go'
            else 'https://opencode.ai/zen/v1'
        )
        assert _opencode_surface_base_url(provider, surface, legacy) == expected

    def test_opencode_custom_base_url_is_preserved(self):
        from backend.inference.clients.factory import _opencode_surface_base_url

        custom = 'https://proxy.example/v1'
        assert _opencode_surface_base_url('opencode', 'anthropic', custom) == custom

    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_opencode_gemini_new_model_uses_native_base(self, _h, _ah):
        client = get_direct_client('opencode/gemini-4-argon', api_key='key')
        assert client._url == (
            'https://opencode.ai/inference/google/v1beta/models/'
            'gemini-4-argon:generateContent'
        )
        assert client._headers['x-opencode-session']
        assert client._headers['User-Agent'].startswith('Grinta/')

    @patch('backend.inference.clients.openai_client.AsyncOpenAI')
    @patch('backend.inference.clients.openai_client.OpenAI')
    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_opencode_chat_new_model_uses_openai_inference_base(
        self, _h, _ah, _oai, _aoai
    ):
        client = get_direct_client('opencode/deepseek-v4.1-flash', api_key='key')
        assert client._api_base_url == 'https://opencode.ai/inference/openai/v1'
        headers = _oai.call_args.kwargs['default_headers']
        assert headers['x-opencode-session']
        assert headers['User-Agent'].startswith('Grinta/')
        async_headers = _aoai.call_args.kwargs['default_headers']
        assert async_headers['x-opencode-session'] == headers['x-opencode-session']


# ---------------------------------------------------------------------------
# DirectLLMClient.model_name validation
# ---------------------------------------------------------------------------


class TestDirectLLMClientModelName:
    @patch('backend.inference.clients.AsyncOpenAI')
    @patch('backend.inference.clients.OpenAI')
    @patch(
        'backend.inference.clients.get_shared_async_http_client',
        return_value=MagicMock(),
    )
    @patch(
        'backend.inference.clients.get_shared_http_client',
        return_value=MagicMock(),
    )
    def test_model_name_set(self, _h, _ah, _oai, _aoai):
        client = get_direct_client('openai/gpt-5', api_key='k')
        assert client.model_name == 'gpt-5'
