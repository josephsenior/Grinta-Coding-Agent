"""Tests for backend.inference.direct_clients — LLMResponse, httpx pool, get_direct_client."""

# pylint: disable=protected-access,unsubscriptable-object,invalid-overridden-method

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.inference.direct_clients import (
    LLMResponse,
    _pool_key,
    aclose_shared_http_clients,
    get_direct_client,
    get_shared_async_http_client,
    get_shared_http_client,
)
from backend.inference.direct_clients_openai_ops import completion as openai_completion
from backend.inference.exceptions import BadRequestError


# ---------------------------------------------------------------------------
# LLMResponse
# ---------------------------------------------------------------------------
class TestLLMResponse:
    def test_basic_attributes(self):
        resp = LLMResponse(
            content='Hello!',
            model='gpt-4',
            usage={'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
            id='resp-123',
            finish_reason='stop',
        )
        assert resp.content == 'Hello!'
        assert resp.model == 'gpt-4'
        assert resp.id == 'resp-123'
        assert resp.finish_reason == 'stop'
        assert resp.tool_calls is None
        assert resp.usage['total_tokens'] == 15

    def test_choices_attribute(self):
        resp = LLMResponse(content='Hi', model='m', usage={}, finish_reason='length')
        assert len(resp.choices) == 1
        assert resp.choices[0].message.content == 'Hi'
        assert resp.choices[0].message.role == 'assistant'
        assert resp.choices[0].finish_reason == 'length'

    def test_with_tool_calls(self):
        tcs = [
            {
                'id': 'tc1',
                'type': 'function',
                'function': {'name': 'f', 'arguments': '{}'},
            }
        ]
        resp = LLMResponse(content='', model='m', usage={}, tool_calls=tcs)
        assert resp.tool_calls == tcs
        # message.tool_calls are ToolCall objects wrapping the dicts
        tc_list = resp.choices[0].message.tool_calls
        assert tc_list is not None
        assert len(tc_list) == 1
        assert tc_list[0].function.name == 'f'

    def test_to_dict(self):
        resp = LLMResponse(
            content='reply',
            model='gpt-4o',
            usage={'prompt_tokens': 1, 'completion_tokens': 2, 'total_tokens': 3},
            id='r1',
        )
        d = resp.to_dict()
        assert d['model'] == 'gpt-4o'
        assert d['id'] == 'r1'
        assert d['choices'][0]['message']['content'] == 'reply'
        assert d['usage']['total_tokens'] == 3

    def test_to_dict_with_tool_calls(self):
        tcs = [{'id': 'tc1'}]
        resp = LLMResponse(content='', model='m', usage={}, tool_calls=tcs)
        d = resp.to_dict()
        tool_calls = d['choices'][0]['message']['tool_calls']
        assert tool_calls is not None
        assert tool_calls[0]['id'] == 'tc1'
        assert tool_calls[0]['type'] == 'function'

    def test_to_dict_includes_reasoning_content(self):
        resp = LLMResponse(
            content='reply',
            model='deepseek-v4-flash',
            usage={},
            reasoning_content='thinking trace',
        )
        d = resp.to_dict()
        assert d['choices'][0]['message']['reasoning_content'] == 'thinking trace'
        assert resp.choices[0].message.reasoning_content == 'thinking trace'

    def test_getitem(self):
        resp = LLMResponse(content='x', model='m', usage={})
        assert resp['model'] == 'm'
        assert isinstance(resp['choices'], list)

    def test_response_id_kwarg(self):
        resp = LLMResponse(content='', model='m', usage={}, response_id='custom-id')
        assert resp.id == 'custom-id'


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
# Shared HTTP clients (pool management)
# ---------------------------------------------------------------------------
class TestSharedHttpClients:
    def test_get_shared_sync_client(self):
        client = get_shared_http_client('test_provider_sync', 'http://test')
        assert client is not None
        # Same key returns same instance
        client2 = get_shared_http_client('test_provider_sync', 'http://test')
        assert client is client2

    def test_get_shared_async_client(self):
        client = get_shared_async_http_client('test_provider_async', 'http://test')
        assert client is not None
        client2 = get_shared_async_http_client('test_provider_async', 'http://test')
        assert client is client2

    @pytest.mark.asyncio
    async def test_aclose_shared_clients_clears_pools(self):
        sync_client = get_shared_http_client('test_provider_close', 'http://test')
        async_client = get_shared_async_http_client(
            'test_provider_close_async', 'http://test'
        )

        await aclose_shared_http_clients()

        assert (
            get_shared_http_client('test_provider_close', 'http://test')
            is not sync_client
        )
        assert (
            get_shared_async_http_client('test_provider_close_async', 'http://test')
            is not async_client
        )
        await aclose_shared_http_clients()

    def test_openai_client_applies_default_timeout(self):
        from backend.inference.direct_clients import OpenAIClient

        with (
            patch('backend.inference.direct_clients.OpenAI'),
            patch('backend.inference.direct_clients.AsyncOpenAI'),
            patch('backend.inference.direct_clients._openai_completion') as completion,
        ):
            client = OpenAIClient('gpt-4o', 'sk-test', timeout=12)
            client.completion(messages=[])

        assert completion.call_args.kwargs['timeout'] == 12.0

    def test_anthropic_client_applies_default_timeout(self):
        from backend.inference.direct_clients import AnthropicClient

        with (
            patch('backend.inference.direct_clients.Anthropic'),
            patch('backend.inference.direct_clients.AsyncAnthropic'),
            patch(
                'backend.inference.direct_clients._anthropic_completion'
            ) as completion,
        ):
            client = AnthropicClient('claude-3', 'sk-test', timeout=9)
            client.completion(messages=[])

        assert completion.call_args.kwargs['timeout'] == 9.0

    def test_gemini_client_uses_configured_timeout_ms(self):
        from backend.inference.direct_clients import GeminiClient

        with (
            patch('google.genai.types.HttpOptions') as http_options,
            patch('backend.inference.direct_clients.genai.Client'),
        ):
            GeminiClient('gemini-2.5-pro', 'key', timeout=7)

        http_options.assert_called_once()
        call_kwargs = http_options.call_args.kwargs
        assert call_kwargs['timeout'] == 7000
        assert isinstance(
            call_kwargs['async_client_args']['transport'], httpx.AsyncBaseTransport
        )


# ---------------------------------------------------------------------------
# get_direct_client factory
# ---------------------------------------------------------------------------
class TestGetDirectClient:
    def test_anthropic_model(self):
        with (
            patch('backend.inference.direct_clients.Anthropic'),
            patch('backend.inference.direct_clients.AsyncAnthropic'),
        ):
            from backend.inference.direct_clients import AnthropicClient

            client = get_direct_client('anthropic/claude-3', api_key='sk-test')
            assert isinstance(client, AnthropicClient)

    def test_claude_model_requires_explicit_provider(self):
        with pytest.raises(ValueError, match='provider'):
            get_direct_client('claude-3.5-sonnet', api_key='sk-test')

    def test_gemini_model(self):
        with patch('backend.inference.direct_clients.genai'):
            from backend.inference.direct_clients import GeminiClient

            client = get_direct_client('google/gemini-pro', api_key='key')
            assert isinstance(client, GeminiClient)

    def test_xai_grok_model(self):
        with (
            patch('backend.inference.direct_clients.OpenAI'),
            patch('backend.inference.direct_clients.AsyncOpenAI'),
        ):
            from backend.inference.direct_clients import OpenAIClient

            client = get_direct_client('xai/grok-1', api_key='key')
            assert isinstance(client, OpenAIClient)

    def test_ollama_model(self):
        with (
            patch('backend.inference.direct_clients.OpenAI'),
            patch('backend.inference.direct_clients.AsyncOpenAI'),
        ):
            from backend.inference.direct_clients import OpenAIClient

            client = get_direct_client('ollama/llama3', api_key='')
            assert isinstance(client, OpenAIClient)
            assert client._model_name == 'llama3'  # prefix stripped

    def test_default_openai(self):
        with (
            patch('backend.inference.direct_clients.OpenAI'),
            patch('backend.inference.direct_clients.AsyncOpenAI'),
        ):
            from backend.inference.direct_clients import OpenAIClient

            client = get_direct_client('gpt-4o', api_key='sk-key')
            assert isinstance(client, OpenAIClient)


# ---------------------------------------------------------------------------
# AnthropicClient helpers
# ---------------------------------------------------------------------------
class TestAnthropicClientHelpers:
    def test_extract_tool_calls(self):
        from backend.inference.mappers.anthropic import extract_tool_calls

        text_block = MagicMock(type='text', text='Hello')
        tool_block = MagicMock(type='tool_use', id='tu1', input={'q': 'test'})
        tool_block.name = 'search'
        text, tcs = extract_tool_calls([text_block, tool_block])
        assert text == 'Hello'
        assert tcs is not None
        assert len(tcs) == 1
        assert tcs[0]['function']['name'] == 'search'
        parsed_args = json.loads(tcs[0]['function']['arguments'])
        assert parsed_args['q'] == 'test'

    def test_extract_no_tool_calls(self):
        from backend.inference.mappers.anthropic import extract_tool_calls

        text_block = MagicMock(type='text', text='Just text')
        text, tcs = extract_tool_calls([text_block])
        assert text == 'Just text'
        assert tcs is None

    def test_prepare_kwargs(self):
        from backend.inference.mappers.anthropic import prepare_kwargs

        messages = [
            {'role': 'system', 'content': 'Be helpful'},
            {'role': 'user', 'content': 'Hi'},
        ]
        filtered, kwargs = prepare_kwargs(messages, {}, default_model='claude-3')
        assert len(filtered) == 1
        assert filtered[0]['role'] == 'user'
        assert kwargs['system'] == 'Be helpful'
        assert kwargs['model'] == 'claude-3'

    def test_prepare_kwargs_combines_all_system_messages(self):
        from backend.inference.mappers.anthropic import prepare_kwargs

        messages = [
            {'role': 'system', 'content': 'Base system prompt'},
            {'role': 'system', 'content': 'Current mode: PLAN'},
            {'role': 'user', 'content': 'What mode are you in?'},
        ]

        filtered, kwargs = prepare_kwargs(messages, {}, default_model='claude-3')

        assert filtered == [{'role': 'user', 'content': 'What mode are you in?'}]
        assert kwargs['system'] == 'Base system prompt\n\nCurrent mode: PLAN'

    def test_prepare_kwargs_converts_openai_tools_to_anthropic_schema(self):
        from backend.inference.mappers.anthropic import prepare_kwargs

        messages = [{'role': 'user', 'content': 'Hi'}]
        tools = [
            {
                'type': 'function',
                'function': {
                    'name': 'read_file',
                    'description': 'Read a file',
                    'parameters': {
                        'type': 'object',
                        'properties': {'path': {'type': 'string'}},
                        'required': ['path'],
                    },
                },
            },
            {
                'type': 'function',
                'function': {'name': '', 'parameters': {}},
            },
        ]

        _, kwargs = prepare_kwargs(
            messages,
            {'tools': tools},
            default_model='minimax-m2.7',
        )

        assert kwargs['tools'] == [
            {
                'name': 'read_file',
                'description': 'Read a file',
                'input_schema': {
                    'type': 'object',
                    'properties': {'path': {'type': 'string'}},
                    'required': ['path'],
                },
            }
        ]

    def test_prepare_kwargs_defaults_empty_tool_parameters(self):
        from backend.inference.mappers.anthropic import prepare_kwargs

        messages = [{'role': 'user', 'content': 'Hi'}]
        tools = [
            {
                'type': 'function',
                'function': {'name': 'finish', 'description': 'Finish'},
            }
        ]

        _, kwargs = prepare_kwargs(
            messages,
            {'tools': tools},
            default_model='minimax-m2.7',
        )

        assert kwargs['tools'][0]['name'] == 'finish'
        assert kwargs['tools'][0]['input_schema'] == {
            'type': 'object',
            'properties': {},
        }

    def test_prepare_kwargs_converts_openai_tool_history_to_anthropic_blocks(self):
        from backend.inference.mappers.anthropic import prepare_kwargs

        messages = [
            {
                'role': 'assistant',
                'content': '',
                'tool_calls': [
                    {
                        'id': 'call_1',
                        'type': 'function',
                        'function': {
                            'name': 'read_file',
                            'arguments': '{"path": "README.md"}',
                        },
                    }
                ],
            },
            {
                'role': 'tool',
                'tool_call_id': 'call_1',
                'name': 'read_file',
                'content': 'file contents',
            },
        ]

        filtered, _ = prepare_kwargs(messages, {}, default_model='minimax-m2.7')

        assert filtered == [
            {
                'role': 'assistant',
                'content': [
                    {
                        'type': 'tool_use',
                        'id': 'call_1',
                        'name': 'read_file',
                        'input': {'path': 'README.md'},
                    }
                ],
            },
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'tool_result',
                        'tool_use_id': 'call_1',
                        'content': 'file contents',
                    }
                ],
            },
        ]

    def test_prepare_kwargs_flattens_unmatched_tool_result(self):
        from backend.inference.mappers.anthropic import prepare_kwargs

        messages = [
            {
                'role': 'tool',
                'tool_call_id': 'missing',
                'name': 'read_file',
                'content': 'orphaned result',
            }
        ]

        filtered, _ = prepare_kwargs(messages, {}, default_model='minimax-m2.7')

        assert filtered == [
            {
                'role': 'user',
                'content': '[Unmatched tool result from read_file]\norphaned result',
            }
        ]

    def test_prepare_stream_request_strips_openai_only_stream_kwargs(self):
        from backend.inference.direct_clients_anthropic_ops import (
            _prepare_anthropic_stream_request,
        )

        client = MagicMock(model_name='minimax-m2.7')
        client._provider_name = 'opencode-go'
        messages = [
            {'role': 'system', 'content': 'Be helpful'},
            {'role': 'system', 'content': 'Current mode: CHAT'},
            {'role': 'user', 'content': 'Hi'},
        ]
        original_kwargs = {
            'model': 'opencode-go/minimax-m2.7',
            'stream': True,
            'stream_options': {'include_usage': True},
            'extra_body': {'metadata': {'trace': '1'}},
            'temperature': 0.2,
            'tools': [
                {
                    'type': 'function',
                    'function': {
                        'name': 'read_file',
                        'parameters': {'type': 'object', 'properties': {}},
                    },
                }
            ],
        }

        filtered, system_msg, request_kwargs = _prepare_anthropic_stream_request(
            client,
            messages,
            original_kwargs,
        )

        assert filtered == [{'role': 'user', 'content': 'Hi'}]
        assert system_msg == 'Be helpful\n\nCurrent mode: CHAT'
        assert request_kwargs == {
            'max_tokens': 131072,
            'model': 'minimax-m2.7',
            'temperature': 0.2,
            'tools': [
                {
                    'name': 'read_file',
                    'input_schema': {'type': 'object', 'properties': {}},
                }
            ],
        }
        assert 'stream' not in request_kwargs
        assert 'stream_options' not in request_kwargs
        assert 'extra_body' not in request_kwargs
        assert original_kwargs['stream'] is True

    def test_prepare_kwargs_adds_required_max_tokens_default(self):
        from backend.inference.direct_clients_anthropic_ops import (
            prepare_anthropic_kwargs,
        )

        client = MagicMock(model_name='minimax-m2.7')
        client._provider_name = 'opencode-go'
        messages = [{'role': 'user', 'content': 'Hi'}]

        filtered, request_kwargs = prepare_anthropic_kwargs(client, messages, {})

        assert filtered == messages
        assert request_kwargs['model'] == 'minimax-m2.7'
        assert request_kwargs['max_tokens'] == 131072

    def test_prepare_kwargs_maps_max_completion_tokens_to_max_tokens(self):
        from backend.inference.direct_clients_anthropic_ops import (
            prepare_anthropic_kwargs,
        )

        client = MagicMock(model_name='minimax-m2.7')
        client._provider_name = 'opencode-go'
        messages = [{'role': 'user', 'content': 'Hi'}]

        _, request_kwargs = prepare_anthropic_kwargs(
            client,
            messages,
            {'max_completion_tokens': 321},
        )

        assert request_kwargs['max_tokens'] == 321
        assert 'max_completion_tokens' not in request_kwargs


# ---------------------------------------------------------------------------
# OpenAIClient helpers
# ---------------------------------------------------------------------------
class TestOpenAIClientHelpers:
    def test_extract_openai_tool_calls(self):
        from backend.inference.mappers.openai import extract_tool_calls

        tc = MagicMock()
        tc.id = 'call_1'
        tc.type = 'function'
        tc.function.name = 'search'
        tc.function.arguments = '{"q":"test"}'
        msg = MagicMock(tool_calls=[tc])
        result = extract_tool_calls(msg)
        assert result is not None
        assert len(result) == 1
        assert result[0]['id'] == 'call_1'

    def test_extract_no_tool_calls(self):
        from backend.inference.mappers.openai import extract_tool_calls

        msg = MagicMock(tool_calls=None)
        assert extract_tool_calls(msg) is None

    def test_extract_empty_tool_calls(self):
        from backend.inference.mappers.openai import extract_tool_calls

        msg = MagicMock(tool_calls=[])
        assert extract_tool_calls(msg) is None

    def test_sanitize_openai_metadata_values_to_strings(self):
        from backend.inference.direct_clients import _sanitize_openai_compatible_kwargs

        kwargs = {
            'extra_body': {
                'metadata': {
                    'session_id': 'abc',
                    'trace_version': 1,
                    'tags': ['model:gpt-4', 'agent:orchestrator'],
                    'extra': {'a': 1},
                }
            }
        }

        sanitized = _sanitize_openai_compatible_kwargs(kwargs)
        metadata = sanitized['extra_body']['metadata']
        assert metadata['session_id'] == 'abc'
        assert metadata['trace_version'] == '1'
        assert metadata['tags'] == 'model:gpt-4,agent:orchestrator'
        assert metadata['extra'] == '{"a":1}'

    def test_opencode_non_chat_model_fails_fast(self):
        client = MagicMock()
        client._provider_name = 'opencode'
        client.model_name = 'gpt-5.5'
        client._clean_messages.return_value = [{'role': 'user', 'content': 'hi'}]
        client._strip_unsupported_params.side_effect = lambda kwargs: kwargs
        client._extract_openai_tool_calls.return_value = None

        with pytest.raises(BadRequestError, match='/responses'):
            openai_completion(client, [{'role': 'user', 'content': 'hi'}])

        client.client.chat.completions.create.assert_not_called()

    def test_opencode_chat_model_calls_chat_completions(self):
        response = MagicMock()
        response.choices = [
            MagicMock(message=MagicMock(content='ok'), finish_reason='stop')
        ]
        response.model = 'deepseek-v4-flash-free'
        response.usage = None
        response.id = 'resp-1'

        client = MagicMock()
        client._provider_name = 'opencode'
        client.model_name = 'deepseek-v4-flash-free'
        client._clean_messages.return_value = [{'role': 'user', 'content': 'hi'}]
        client._strip_unsupported_params.side_effect = lambda kwargs: kwargs
        client._extract_openai_tool_calls.return_value = None
        client.client.chat.completions.create.return_value = response

        result = openai_completion(client, [{'role': 'user', 'content': 'hi'}])
        assert result.content == 'ok'
        client.client.chat.completions.create.assert_called_once()

    def test_opencode_go_minimax_fails_fast_on_chat_completions(self):
        client = MagicMock()
        client._provider_name = 'opencode-go'
        client.model_name = 'minimax-m2.7'
        client._clean_messages.return_value = [{'role': 'user', 'content': 'hi'}]
        client._strip_unsupported_params.side_effect = lambda kwargs: kwargs
        client._extract_openai_tool_calls.return_value = None

        with pytest.raises(BadRequestError, match='/messages'):
            openai_completion(client, [{'role': 'user', 'content': 'hi'}])

        client.client.chat.completions.create.assert_not_called()

    def test_deepseek_thinking_history_recovers_stale_assistant_messages(self):
        from backend.inference.direct_clients_openai_ops import (
            _recover_deepseek_thinking_history,
        )

        client = MagicMock()
        client._provider_name = 'opencode-go'
        client.model_name = 'deepseek-v4-flash'
        messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'start'},
            {
                'role': 'assistant',
                'content': 'I will inspect the file.',
                'tool_calls': [
                    {
                        'id': 'call_1',
                        'type': 'function',
                        'function': {
                            'name': 'read_file',
                            'arguments': '{"path":"a.py"}',
                        },
                    }
                ],
            },
            {
                'role': 'tool',
                'name': 'read_file',
                'tool_call_id': 'call_1',
                'content': 'print("ok")',
            },
            {
                'role': 'assistant',
                'content': 'Done.',
                'reasoning_content': 'kept reasoning',
            },
        ]

        recovered = _recover_deepseek_thinking_history(client, messages)

        assert recovered[0] == messages[0]
        assert recovered[1] == messages[1]
        assert recovered[2]['role'] == 'user'
        assert 'I will inspect the file.' in recovered[2]['content']
        assert 'Read File' in recovered[2]['content']
        assert 'tool_calls' not in recovered[2]
        assert recovered[3]['role'] == 'user'
        assert 'Tool result from read_file' in recovered[3]['content']
        assert recovered[4] == messages[4]


# ---------------------------------------------------------------------------
# GeminiClient helpers
# ---------------------------------------------------------------------------
class TestGeminiClientHelpers:
    def test_convert_messages(self):
        from backend.inference.mappers.gemini import convert_messages

        messages = [
            {'role': 'system', 'content': 'System prompt'},
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there'},
        ]
        system, gemini, _caching = convert_messages(messages)
        assert system == 'System prompt'
        assert len(gemini) == 2
        assert gemini[0]['role'] == 'user'
        assert gemini[1]['role'] == 'model'

    def test_extract_generation_config(self):
        from backend.inference.mappers.gemini import extract_generation_config

        kwargs = {
            'model': 'models/gemini-pro',
            'temperature': 0.7,
            'max_tokens': 100,
            'top_p': 0.9,
        }
        model_name, gen_cfg, _tools = extract_generation_config(kwargs)
        assert model_name == 'gemini-pro'  # Strip "models/"
        assert gen_cfg['temperature'] == 0.7
        assert gen_cfg['max_output_tokens'] == 100
        assert 'model' not in kwargs  # Popped

    def test_gemini_usage_none(self):
        from backend.inference.mappers.gemini import gemini_usage

        resp = MagicMock(usage_metadata=None)
        usage = gemini_usage(resp)
        assert usage['prompt_tokens'] == 0
        assert usage['total_tokens'] == 0

    def test_gemini_usage_valid(self):
        from backend.inference.mappers.gemini import gemini_usage

        meta = MagicMock(
            prompt_token_count=10, candidates_token_count=20, total_token_count=30
        )
        resp = MagicMock(usage_metadata=meta)
        usage = gemini_usage(resp)
        assert usage['prompt_tokens'] == 10
        assert usage['completion_tokens'] == 20
        assert usage['total_tokens'] == 30

    def test_extract_gemini_tool_calls(self):
        from backend.inference.mappers.gemini import extract_tool_calls

        fc = MagicMock()
        fc.name = 'search'
        fc.args = {'q': 'hello'}
        part = MagicMock(function_call=fc)
        candidate = MagicMock()
        candidate.content = {'parts': [part]}
        resp = MagicMock(candidates=[candidate])
        tcs = extract_tool_calls(resp)
        assert tcs is not None
        assert len(tcs) == 1
        assert tcs[0]['function']['name'] == 'search'

    def test_extract_gemini_no_tool_calls(self):
        from backend.inference.mappers.gemini import extract_tool_calls

        part = MagicMock(function_call=None)
        candidate = MagicMock()
        candidate.content = {'parts': [part]}
        resp = MagicMock(candidates=[candidate])
        assert extract_tool_calls(resp) is None

    def test_extract_gemini_finish_reason_from_dict_shape(self):
        from backend.inference.mappers.gemini import extract_finish_reason

        response = {
            'candidates': [
                {
                    'finishReason': 'SAFETY',
                    'content': {'parts': []},
                }
            ]
        }
        assert extract_finish_reason(response) == 'SAFETY'

    def test_extract_gemini_block_reason_from_prompt_feedback(self):
        from backend.inference.mappers.gemini import extract_block_reason

        response = {
            'promptFeedback': {
                'blockReason': 'SAFETY',
            }
        }
        assert extract_block_reason(response) == 'SAFETY'

    def test_ensure_non_empty_gemini_content_synthesizes_for_empty_response(self):
        from backend.inference.mappers.gemini import ensure_non_empty_content

        response = {
            'candidates': [{'finishReason': 'SAFETY', 'content': {'parts': []}}],
            'promptFeedback': {'blockReason': 'SAFETY'},
        }
        content = ensure_non_empty_content(
            response,
            content='',
            tool_calls=None,
        )

        assert 'blocked by safety' in content.lower()

    def test_ensure_non_empty_gemini_content_keeps_text_when_present(self):
        from backend.inference.mappers.gemini import ensure_non_empty_content

        content = ensure_non_empty_content(
            response={},
            content='hello',
            tool_calls=None,
        )
        assert content == 'hello'

    def test_ensure_non_empty_gemini_content_keeps_empty_for_tool_calls(self):
        from backend.inference.mappers.gemini import ensure_non_empty_content

        content = ensure_non_empty_content(
            response={},
            content='',
            tool_calls=[
                {
                    'id': 'tc1',
                    'type': 'function',
                    'function': {'name': 'x', 'arguments': '{}'},
                }
            ],
        )
        assert content == ''


# ---------------------------------------------------------------------------
# DirectLLMClient.model_name property
# ---------------------------------------------------------------------------
class TestDirectLLMClientModelName:
    def test_model_name_not_set(self):
        from backend.inference.direct_clients import DirectLLMClient

        class TestClient(DirectLLMClient):
            def completion(self, messages, **kwargs):
                pass

            async def acompletion(self, messages, **kwargs):
                pass

            async def astream(self, messages, **kwargs):
                yield {}

        c = TestClient()
        with pytest.raises(NotImplementedError):
            _ = c.model_name

    def test_model_name_set(self):
        with (
            patch('backend.inference.direct_clients.OpenAI'),
            patch('backend.inference.direct_clients.AsyncOpenAI'),
        ):
            from backend.inference.direct_clients import OpenAIClient

            c = OpenAIClient('gpt-4', 'key')
            assert c.model_name == 'gpt-4'
