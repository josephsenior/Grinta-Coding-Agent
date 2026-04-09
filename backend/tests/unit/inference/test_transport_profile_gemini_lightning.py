"""Tests: Gemini through Lightning AI preserves full capabilities.

Verifies that when a Google-family model is routed through Lightning's
OpenAI-compatible proxy:

  1. The right TransportProfile is resolved (cross-family detection)
  2. The full model identifier is preserved for the proxy (not stripped)
  3. Current-turn tool definitions pass through unmodified
  4. Vision/multimodal content passes through unmodified
  5. System/user/plain-assistant messages pass through unmodified
  6. Only prior tool-call *history* messages are flattened (the one lossy step)
  7. Extra metadata is stripped (rejected by Lightning's backend)
  8. Temperature, max_tokens, streaming flags pass through unmodified
  9. Native Google endpoint routes to GeminiClient instead
 10. OpenAI model on Lightning keeps tool replay intact
"""

from unittest.mock import MagicMock, patch

from backend.inference.direct_clients import (
    GeminiClient,
    OpenAIClient,
    TransportProfile,
    _resolve_transport_profile,
    get_direct_client,
)

LIGHTNING_URL = 'https://lightning.ai/api/v1'
GEMINI_MODEL = 'google/gemini-3-flash-preview'


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

def _mock_patches():
    """Return the four patches needed to instantiate OpenAIClient without I/O."""
    return [
        patch('backend.inference.direct_clients.AsyncOpenAI'),
        patch('backend.inference.direct_clients.OpenAI'),
        patch(
            'backend.inference.direct_clients.get_shared_async_http_client',
            return_value=MagicMock(),
        ),
        patch(
            'backend.inference.direct_clients.get_shared_http_client',
            return_value=MagicMock(),
        ),
    ]


def _gemini_lightning_client():
    """Create an OpenAIClient for Gemini-through-Lightning with correct profile."""
    profile = TransportProfile(
        supports_request_metadata=False,
        supports_tool_replay=False,
    )
    return OpenAIClient(
        GEMINI_MODEL,
        'test-key',
        base_url=LIGHTNING_URL,
        profile=profile,
    )


# ---------------------------------------------------------------------------
# 1. Profile resolution
# ---------------------------------------------------------------------------

class TestTransportProfileResolution:
    def test_google_on_lightning_gets_cross_family_profile(self):
        """Google model family + non-native endpoint → no metadata, no tool replay."""
        profile = _resolve_transport_profile('google', LIGHTNING_URL)
        assert profile.supports_request_metadata is False
        assert profile.supports_tool_replay is False

    def test_openai_on_openai_api_gets_full_profile(self):
        """OpenAI model + native endpoint → full capabilities."""
        profile = _resolve_transport_profile('openai', None)
        assert profile.supports_request_metadata is True
        assert profile.supports_tool_replay is True

    def test_openai_on_lightning_loses_metadata_keeps_tool_replay(self):
        """OpenAI model routed through Lightning → no metadata, but tool replay OK."""
        profile = _resolve_transport_profile('openai', LIGHTNING_URL)
        assert profile.supports_request_metadata is False
        assert profile.supports_tool_replay is True

    def test_deepseek_on_custom_endpoint(self):
        """Non-OpenAI, non-Google family → no metadata (not native OpenAI), tool replay fine."""
        profile = _resolve_transport_profile('deepseek', 'https://api.deepseek.com/v1')
        assert profile.supports_request_metadata is False
        assert profile.supports_tool_replay is True


# ---------------------------------------------------------------------------
# 2. Client routing and model name preservation
# ---------------------------------------------------------------------------

class TestClientRouting:
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
    def test_gemini_lightning_returns_openai_client(self, _h, _ah, _oai, _aoai):
        """Gemini on Lightning → OpenAIClient (not GeminiClient)."""
        client = get_direct_client(GEMINI_MODEL, api_key='key', base_url=LIGHTNING_URL)
        assert isinstance(client, OpenAIClient)

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
    def test_gemini_lightning_preserves_full_model_name(self, _h, _ah, _oai, _aoai):
        """The full model identifier must reach the proxy (e.g. 'google/gemini-3-flash-preview')."""
        client = get_direct_client(GEMINI_MODEL, api_key='key', base_url=LIGHTNING_URL)
        assert client.model_name == GEMINI_MODEL

    @patch('backend.inference.direct_clients.genai')
    def test_gemini_native_endpoint_returns_gemini_client(self, _genai):
        """Gemini on its own API → GeminiClient (native SDK, full capabilities)."""
        client = get_direct_client(
            GEMINI_MODEL,
            api_key='key',
            base_url='https://generativelanguage.googleapis.com/v1',
        )
        assert isinstance(client, GeminiClient)

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
    def test_gemini_lightning_with_transport_prefix_gets_cross_family_profile(
        self, _h, _ah, _oai, _aoai
    ):
        """openai/google/gemini-* (Lightning-canonicalized) must still get cross-family profile."""
        client = get_direct_client(
            'openai/google/gemini-3-flash-preview',
            api_key='key',
            base_url=LIGHTNING_URL,
        )
        assert isinstance(client, OpenAIClient)
        assert client._profile.supports_request_metadata is False
        assert client._profile.supports_tool_replay is False

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
    def test_gemini_lightning_transport_prefix_model_name_is_stripped(
        self, _h, _ah, _oai, _aoai
    ):
        """Model name sent to proxy should be 'google/gemini-*', not 'openai/google/gemini-*'."""
        client = get_direct_client(
            'openai/google/gemini-3-flash-preview',
            api_key='key',
            base_url=LIGHTNING_URL,
        )
        assert client.model_name == 'google/gemini-3-flash-preview'


# ---------------------------------------------------------------------------
# 3. Request parameters that must survive unchanged
# ---------------------------------------------------------------------------

class TestRequestParamsPreserved:
    def setup_method(self):
        patches = _mock_patches()
        self.mocks = [p.start() for p in patches]
        self.patches = patches
        self.client = _gemini_lightning_client()

    def teardown_method(self):
        for p in self.patches:
            p.stop()

    def test_tools_kwarg_is_not_stripped(self):
        """Current-turn tool definitions must reach the model unchanged."""
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
            }
        ]
        kwargs = {'tools': tools, 'tool_choice': 'auto'}
        result = self.client._strip_unsupported_params(kwargs)
        assert result['tools'] == tools
        assert result['tool_choice'] == 'auto'

    def test_temperature_and_max_tokens_pass_through(self):
        """Inference hyperparameters must not be stripped."""
        kwargs = {'temperature': 0.7, 'max_tokens': 4096}
        result = self.client._strip_unsupported_params(kwargs)
        assert result['temperature'] == 0.7
        assert result['max_tokens'] == 4096

    def test_metadata_is_stripped(self):
        """extra_body.metadata must be removed (Lightning rejects it)."""
        kwargs = {
            'extra_body': {
                'metadata': {'trace_version': '0.55.0', 'session_id': 'abc'},
                'other_field': 'keep_me',
            }
        }
        result = self.client._strip_unsupported_params(kwargs)
        assert 'metadata' not in result.get('extra_body', {})
        assert result['extra_body']['other_field'] == 'keep_me'

    def test_metadata_only_extra_body_is_removed_entirely(self):
        """extra_body with only metadata should be removed completely."""
        kwargs = {'extra_body': {'metadata': {'k': 'v'}}}
        result = self.client._strip_unsupported_params(kwargs)
        assert 'extra_body' not in result


# ---------------------------------------------------------------------------
# 4. Message content that must survive unchanged
# ---------------------------------------------------------------------------

class TestMessageContentPreserved:
    def setup_method(self):
        patches = _mock_patches()
        self.mocks = [p.start() for p in patches]
        self.patches = patches
        self.client = _gemini_lightning_client()

    def teardown_method(self):
        for p in self.patches:
            p.stop()

    def test_system_message_passes_through(self):
        messages = [{'role': 'system', 'content': 'You are a helpful assistant.'}]
        result = self.client._clean_messages(messages)
        assert result == messages

    def test_plain_user_message_passes_through(self):
        messages = [
            {'role': 'system', 'content': 'You are helpful.'},
            {'role': 'user', 'content': 'What is 2+2?'},
        ]
        result = self.client._clean_messages(messages)
        assert result == messages

    def test_plain_assistant_reply_passes_through(self):
        messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there!'},
        ]
        result = self.client._clean_messages(messages)
        assert result == messages

    def test_vision_image_url_content_passes_through(self):
        """Multimodal image content must not be modified."""
        messages = [
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': 'What is in this image?'},
                    {
                        'type': 'image_url',
                        'image_url': {'url': 'https://example.com/image.png'},
                    },
                ],
            }
        ]
        result = self.client._clean_messages(messages)
        assert result == messages

    def test_vision_base64_content_passes_through(self):
        """Base64-encoded image content must not be modified."""
        messages = [
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': 'Describe this:'},
                    {
                        'type': 'image_url',
                        'image_url': {
                            'url': 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==',
                            'detail': 'high',
                        },
                    },
                ],
            }
        ]
        result = self.client._clean_messages(messages)
        assert result == messages

    def test_tool_ok_field_is_stripped(self):
        """Internal tool_ok marker must be removed before sending."""
        messages = [
            {
                'role': 'tool',
                'name': 'read_file',
                'content': 'file contents',
                'tool_call_id': 'call_1',
                'tool_ok': True,
            }
        ]
        result = self.client._clean_messages(messages)
        # tool message gets converted to user message in cross-family normalization
        assert all('tool_ok' not in msg for msg in result)


# ---------------------------------------------------------------------------
# 5. History normalization (the one capability difference)
# ---------------------------------------------------------------------------

class TestHistoryNormalization:
    def setup_method(self):
        patches = _mock_patches()
        self.mocks = [p.start() for p in patches]
        self.patches = patches
        self.client = _gemini_lightning_client()

    def teardown_method(self):
        for p in self.patches:
            p.stop()

    def test_prior_tool_call_message_is_flattened(self):
        """Prior assistant tool-call message must become plain text."""
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
                            'arguments': '{"path": "/etc/hosts"}',
                        },
                    }
                ],
            }
        ]
        result = self.client._clean_messages(messages)
        assert len(result) == 1
        assert result[0]['role'] == 'assistant'
        assert 'tool_calls' not in result[0]
        flat = result[0]['content']
        assert '[Tool call]' in flat
        assert '/etc/hosts' in flat
        assert '({"path"' not in flat

    def test_prior_tool_result_becomes_user_message(self):
        """Prior tool result must become a user message."""
        messages = [
            {
                'role': 'tool',
                'name': 'read_file',
                'tool_call_id': 'call_1',
                'content': '127.0.0.1 localhost',
            }
        ]
        result = self.client._clean_messages(messages)
        assert len(result) == 1
        assert result[0]['role'] == 'user'
        assert '[Tool result from read_file]' in result[0]['content']
        assert '127.0.0.1 localhost' in result[0]['content']

    def test_mixed_conversation_only_normalizes_tool_messages(self):
        """Plain messages pass through; only tool-call history gets flattened."""
        messages = [
            {'role': 'system', 'content': 'You are helpful.'},
            {'role': 'user', 'content': 'Read /etc/hosts'},
            {
                'role': 'assistant',
                'content': 'I will read the file.',
                'tool_calls': [
                    {
                        'id': 'call_1',
                        'type': 'function',
                        'function': {
                            'name': 'read_file',
                            'arguments': '{"path": "/etc/hosts"}',
                        },
                    }
                ],
            },
            {
                'role': 'tool',
                'name': 'read_file',
                'tool_call_id': 'call_1',
                'content': '127.0.0.1 localhost',
            },
            {'role': 'assistant', 'content': 'Here are the contents.'},
            {'role': 'user', 'content': 'Now summarize it'},
        ]
        result = self.client._clean_messages(messages)

        # System/user messages unchanged
        assert result[0] == {'role': 'system', 'content': 'You are helpful.'}
        assert result[1] == {'role': 'user', 'content': 'Read /etc/hosts'}

        # Prior tool-call assistant message → flattened
        assert result[2]['role'] == 'assistant'
        assert 'tool_calls' not in result[2]
        assert '[Tool call]' in result[2]['content']
        assert '/etc/hosts' in result[2]['content']

        # Prior tool result → user message
        assert result[3]['role'] == 'user'
        assert '[Tool result from read_file]' in result[3]['content']

        # Subsequent plain messages unchanged
        assert result[4] == {'role': 'assistant', 'content': 'Here are the contents.'}
        assert result[5] == {'role': 'user', 'content': 'Now summarize it'}

    def test_assistant_thinking_text_preserved_in_flattened_message(self):
        """Any text content alongside tool calls is preserved in the flatten."""
        messages = [
            {
                'role': 'assistant',
                'content': 'Let me look that up for you.',
                'tool_calls': [
                    {
                        'id': 'call_1',
                        'type': 'function',
                        'function': {'name': 'search', 'arguments': '{"q": "grinta"}'},
                    }
                ],
            }
        ]
        result = self.client._clean_messages(messages)
        assert 'Let me look that up for you.' in result[0]['content']
        assert '[Tool call]' in result[0]['content']
        assert 'grinta' in result[0]['content']

    def test_multiple_tool_calls_in_one_message(self):
        """Multiple tool calls in one assistant turn all get flattened."""
        messages = [
            {
                'role': 'assistant',
                'content': '',
                'tool_calls': [
                    {
                        'id': 'call_1',
                        'type': 'function',
                        'function': {'name': 'read_file', 'arguments': '{"path":"a"}'},
                    },
                    {
                        'id': 'call_2',
                        'type': 'function',
                        'function': {'name': 'list_dir', 'arguments': '{"path":"/"}'},
                    },
                ],
            }
        ]
        result = self.client._clean_messages(messages)
        assert len(result) == 1
        joined = result[0]['content']
        assert '[Tool call]' in joined
        assert 'a' in joined
        assert '/' in joined
        assert '({"path"' not in joined


# ---------------------------------------------------------------------------
# 6. Same-family (OpenAI) on Lightning preserves tool replay
# ---------------------------------------------------------------------------

class TestOpenAIOnLightningPreservesToolReplay:
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
    def test_openai_model_on_lightning_keeps_tool_history(self, _h, _ah, _oai, _aoai):
        """OpenAI model through Lightning: tool history must NOT be flattened."""
        client = get_direct_client(
            'openai/gpt-4o-mini',
            api_key='key',
            base_url=LIGHTNING_URL,
        )
        assert isinstance(client, OpenAIClient)
        assert client._profile.supports_tool_replay is True

        # Tool-call history must pass through intact
        messages = [
            {
                'role': 'assistant',
                'content': '',
                'tool_calls': [
                    {
                        'id': 'call_1',
                        'type': 'function',
                        'function': {'name': 'task_tracker', 'arguments': '{}'},
                    }
                ],
            }
        ]
        result = client._clean_messages(messages)
        assert result[0].get('tool_calls') is not None
