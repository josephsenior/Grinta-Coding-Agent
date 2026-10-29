"""Verify subscription routing and a model/tool/result exchange without inference."""

import pytest


def test_selected_function_restricts_namespace_without_unsupported_choice_field():
    client = ChatGPTPlanClient('gpt-6.1-sol')
    payload = client._build_payload(
        [{'role': 'user', 'content': 'test'}],
        {
            'tools': [
                {'type': 'function', 'function': {'name': name}}
                for name in ('chosen', 'other')
            ],
            'tool_choice': {'type': 'function', 'function': {'name': 'chosen'}},
        },
    )
    assert payload['tool_choice'] == 'required'
    assert [tool['name'] for tool in payload['tools'][0]['tools']] == ['chosen']


from backend.inference.clients.chatgpt_plan import ChatGPTPlanClient, ChatGPTPlanError
from backend.inference.clients.factory import get_direct_client


def test_factory_keeps_codex_separate():
    assert isinstance(
        get_direct_client('chatgpt-plan/gpt-6.1-sol', ''), ChatGPTPlanClient
    )
    assert (
        type(get_direct_client('codex/gpt-6.1-sol', '')).__name__
        == 'CodexResponsesClient'
    )


def test_no_api_key_or_codex_fallback(monkeypatch):
    from backend.inference.clients import chatgpt_plan_auth as auth

    def missing(profile):
        raise auth.PlanAuthError('No saved authorization')

    monkeypatch.setattr(auth, 'access_token', missing)
    monkeypatch.delenv('GRINTA_CHATGPT_PLAN_ACCESS_TOKEN', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'must-not-be-used')
    with pytest.raises(ChatGPTPlanError, match='authorization required'):
        ChatGPTPlanClient('gpt-6.1-sol')._credentials()


def test_tool_call_result_exchange(monkeypatch):
    client = ChatGPTPlanClient('gpt-6.1-sol')
    monkeypatch.setenv('GRINTA_CHATGPT_PLAN_ACCESS_TOKEN', 'offline-test-token')
    payloads = []

    class Responses:
        def create(self, **payload):
            payloads.append(payload)
            if len(payloads) == 1:
                output = [
                    {
                        'type': 'function_call',
                        'call_id': 'call-1',
                        'name': 'read_file',
                        'arguments': '{"path":"a.py"}',
                    }
                ]
            else:
                output = [
                    {
                        'type': 'message',
                        'role': 'assistant',
                        'content': [{'type': 'output_text', 'text': 'File read.'}],
                    }
                ]
            return iter(
                [
                    {
                        'type': 'response.completed',
                        'response': {
                            'id': 'r',
                            'model': 'gpt-6.1-sol',
                            'status': 'completed',
                            'output': output,
                            'usage': {'input_tokens': 10, 'output_tokens': 2},
                        },
                    }
                ]
            )

    class Transport:
        responses = Responses()

    monkeypatch.setattr(client, '_sync_responses_client', lambda *args: Transport())
    messages = [
        {'role': 'system', 'content': 'Use Grinta tools.'},
        {'role': 'user', 'content': 'Read a.py'},
    ]
    tools = [
        {
            'type': 'function',
            'function': {
                'name': 'read_file',
                'parameters': {
                    'type': 'object',
                    'properties': {'path': {'type': 'string'}},
                },
            },
        }
    ]
    first = client.completion(messages, tools=tools, reasoning_effort='medium')
    messages += [
        {'role': 'assistant', 'content': '', 'tool_calls': first.tool_calls},
        {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'x = 1'},
    ]
    second = client.completion(messages, tools=tools)
    assert second.content == 'File read.'
    assert second.usage['prompt_tokens'] == 10
    assert payloads[0]['tools'][0]['type'] == 'namespace'
    assert payloads[0]['store'] is False and payloads[0]['stream'] is True
    assert payloads[1]['input'][-1]['type'] == 'function_call_output'


@pytest.mark.parametrize(
    'kind',
    ['response.failed', 'response.incomplete', 'error', 'response.output_text.delta'],
)
def test_failed_or_interrupted_stream_rejected(kind):
    with pytest.raises(ChatGPTPlanError):
        ChatGPTPlanClient('gpt-6.1-sol')._response_from_events([{'type': kind}])
