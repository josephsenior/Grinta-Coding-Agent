"""A once-only content allowance is distinct from processed model usage."""

import pytest

from backend.inference.comparison_budget import AttemptBudget, BudgetExceeded


def message(role, text):
    return {'role': role, 'content': text}


def test_replayed_history_and_generated_reply_are_not_charged_twice():
    b = AttemptBudget.pilot()
    user = message('user', 'Inspect this source code.')
    reply = {
        'type': 'message',
        'role': 'assistant',
        'content': [
            {'type': 'output_text', 'text': 'I will inspect it.', 'annotations': []},
        ],
    }
    b.observe_request({'input': [user]})
    b.observe_response([reply])
    first = b.snapshot()['used_tokens']
    b.observe_request({'input': [user, message('assistant', 'I will inspect it.')]})
    assert b.snapshot()['used_tokens'] == first
    # Replayed input can exceed the content allowance in actual processed usage.
    b.charge(2_000_000, 10)
    assert b.snapshot()['used_tokens'] == first
    assert b.snapshot()['processed_tokens'] == 2_000_010
    assert b.snapshot()['processed_input_tokens'] == 2_000_000


def test_new_tool_result_counts_once_and_tool_call_replay_matches():
    b = AttemptBudget.pilot()
    call = {
        'type': 'function_call',
        'call_id': 'call-1',
        'name': 'read_file',
        'arguments': '{"path":"a.py"}',
    }
    b.observe_response([call])
    before = b.counted_tokens
    result = {'type': 'function_call_output', 'call_id': 'call-1', 'output': 'a = 1'}
    b.observe_request({'input': [call, result]})
    after = b.counted_tokens
    assert after > before
    b.observe_request({'input': [call, result]})
    assert b.counted_tokens == after


def test_identical_new_replies_are_distinct_occurrences():
    b = AttemptBudget.pilot()
    reply = message('assistant', 'Checking.')
    b.observe_response([reply])
    once = b.counted_tokens
    b.observe_response([reply])
    assert b.counted_tokens == 2 * once
    b.observe_request({'input': [reply, reply]})
    assert b.counted_tokens == 2 * once


def test_repeated_instructions_and_tool_schema_count_once():
    b = AttemptBudget.pilot()
    payload = {
        'input': [],
        'instructions': 'Solve the task.',
        'tools': [{'type': 'function', 'name': 'read_file'}],
    }
    b.observe_request(payload)
    once = b.counted_tokens
    b.observe_request(payload)
    assert b.counted_tokens == once


def test_context_limit_stops_request_before_another_model_call():
    b = AttemptBudget(tokens=1, accounting='once_only_context')
    with pytest.raises(BudgetExceeded, match='token_limit'):
        b.observe_request({'input': [message('user', 'New content.')]})
    assert b.snapshot()['processed_tokens'] == 0
    assert b.snapshot()['token_overshoot'] > 0


def test_response_content_overshoot_stops_following_work():
    b = AttemptBudget(tokens=1, accounting='once_only_context')
    with pytest.raises(BudgetExceeded, match='token_limit'):
        b.observe_response([message('assistant', 'New answer.')])
    with pytest.raises(BudgetExceeded, match='token_limit'):
        b.check()


def test_reasoning_remains_in_actual_usage_without_counting_encrypted_bytes():
    b = AttemptBudget.pilot()
    b.observe_response([{'type': 'reasoning', 'encrypted_content': 'opaque bytes'}])
    b.charge(20, 10)
    assert b.counted_tokens == 0
    assert b.snapshot()['processed_output_tokens'] == 10


def test_provider_and_host_relay_see_identical_content_across_tool_roundtrip():
    from backend.inference.clients.chatgpt_plan import ChatGPTPlanClient
    from backend.inference.comparison_scope import active_budget

    remote, host = AttemptBudget.pilot(), AttemptBudget.pilot()
    client = ChatGPTPlanClient('gpt-6.1-sol')
    messages = [{'role': 'user', 'content': 'Read a.py'}]
    output = [
        {
            'type': 'function_call',
            'call_id': 'c1',
            'name': 'read_file',
            'arguments': '{"path":"a.py"}',
        }
    ]
    token = active_budget.set(remote)
    try:
        payload = client._build_payload(messages, {'reasoning_effort': 'medium'})
        host.observe_request(payload)
        response = client._response_from_events(
            [
                {
                    'type': 'response.completed',
                    'response': {
                        'output': output,
                        'usage': {'input_tokens': 2000000, 'output_tokens': 5},
                    },
                }
            ]
        )
        host.charge(2000000, 5)
        host.observe_response(output)
        converted = client._to_llm_response(response)
        messages += [
            {'role': 'assistant', 'content': '', 'tool_calls': converted.tool_calls},
            {'role': 'tool', 'tool_call_id': 'c1', 'content': 'a = 1'},
        ]
        payload = client._build_payload(messages, {'reasoning_effort': 'medium'})
        host.observe_request(payload)
        assert remote.snapshot()['used_tokens'] == host.snapshot()['used_tokens']
        assert (
            remote.snapshot()['processed_tokens'] == host.snapshot()['processed_tokens']
        )
        assert host.snapshot()['processed_tokens'] > host.tokens
    finally:
        active_budget.reset(token)
