from unittest.mock import MagicMock, patch

from backend.inference.direct_clients import OpenAIClient, TransportProfile


class TestCrossFamilyMessageNormalization:
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
    def test_cross_family_proxy_flattens_tool_history(self, _h, _ah, _oai, _aoai):
        """Google-family model on OpenAI-compatible proxy → flatten tool history."""
        profile = TransportProfile(
            supports_request_metadata=False,
            supports_tool_replay=False,
        )
        client = OpenAIClient(
            'google/gemini-3-flash-preview',
            'key',
            base_url='https://lightning.ai/api/v1',
            profile=profile,
        )

        cleaned = client._clean_messages(
            [
                {
                    'role': 'assistant',
                    'content': '',
                    'tool_calls': [
                        {
                            'id': 'call_1',
                            'type': 'function',
                            'function': {
                                'name': 'task_tracker',
                                'arguments': '{"command":"show_tasks"}',
                            },
                        }
                    ],
                },
                {
                    'role': 'tool',
                    'tool_call_id': 'call_1',
                    'name': 'task_tracker',
                    'content': '[]',
                    'tool_ok': True,
                },
            ]
        )

        assert cleaned == [
            {
                'role': 'assistant',
                'content': '[Tool call] task_tracker({"command":"show_tasks"})',
            },
            {
                'role': 'user',
                'content': '[Tool result from task_tracker]\n[]',
            },
        ]

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
    def test_same_family_proxy_keeps_tool_history(self, _h, _ah, _oai, _aoai):
        """OpenAI model on OpenAI-compatible proxy → keep tool history intact."""
        profile = TransportProfile(
            supports_request_metadata=False,
            supports_tool_replay=True,
        )
        client = OpenAIClient(
            'gpt-4o-mini',
            'key',
            base_url='http://localhost:8080/v1',
            profile=profile,
        )
        original = [
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

        cleaned = client._clean_messages(original)

        assert cleaned == original
