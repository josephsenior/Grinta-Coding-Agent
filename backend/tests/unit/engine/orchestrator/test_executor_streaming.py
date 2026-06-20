from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from backend.engine.contracts import NoopSafetyManager
from backend.inference.exceptions import ContextWindowExceededError


class _Safety:
    def apply(self, response_text, actions):
        return True, actions


def _event_stream(sid: str):
    event_stream = MagicMock()
    event_stream.sid = sid
    return event_stream


def _assert_stream_chunk(
    chunk,
    *,
    expected_chunk: str,
    expected_accumulated: str,
    expected_final: bool,
) -> None:
    assert chunk.chunk == expected_chunk
    assert chunk.accumulated == expected_accumulated
    assert chunk.is_final is expected_final


def _planner_with_checkpoint_policy(
    *,
    max_age: float = 300.0,
    discard_stale_on_recovery: bool = True,
):
    planner = MagicMock()
    planner._config = SimpleNamespace(
        streaming_checkpoint_max_age_seconds=max_age,
        streaming_checkpoint_discard_stale_on_recovery=discard_stale_on_recovery,
    )
    return planner


def _mark_checkpoint_stale(checkpoint) -> None:
    raw = json.loads(checkpoint._wal_path.read_text(encoding='utf-8'))
    raw['created_at'] = 0.0
    checkpoint._wal_path.write_text(json.dumps(raw), encoding='utf-8')


def test_finalize_stream_tool_calls_filters_invalid_streamed_name() -> None:
    from backend.engine.executor import OrchestratorExecutor
    from backend.engine.executor_mixins._executor_types import _AsyncStreamingState

    executor = object.__new__(OrchestratorExecutor)
    state = _AsyncStreamingState(content_accumulate='[END_TOOL_CALL]')
    state.tool_calls_dict[0] = {
        'id': 'bad',
        'type': 'function',
        'function': {
            'name': 'Progress! <invoke name="execute_powershell',
            'arguments': '{"command":"pwd"}',
        },
    }

    assert executor._finalize_stream_tool_calls(state) is None


def test_finalize_stream_tool_calls_recovers_text_marker_after_bad_streamed_name() -> (
    None
):
    from backend.engine.executor import OrchestratorExecutor
    from backend.engine.executor_mixins._executor_types import _AsyncStreamingState

    executor = object.__new__(OrchestratorExecutor)
    state = _AsyncStreamingState(
        content_accumulate=(
            '[Tool call] execute_powershell({"command":"pwd","security_risk":"LOW"})'
        )
    )
    state.tool_calls_dict[0] = {
        'id': 'bad',
        'type': 'function',
        'function': {
            'name': 'execute_powershell is not registered',
            'arguments': '{}',
        },
    }

    calls = executor._finalize_stream_tool_calls(state)

    assert calls is not None
    assert len(calls) == 1
    assert calls[0]['function']['name'] == 'execute_powershell'


def test_final_stream_event_with_tool_call_suppresses_draft_reply():
    from backend.engine.executor import OrchestratorExecutor

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=MagicMock(),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )
    event_stream = _event_stream('test-final-stream-tool-call')

    executor._emit_final_stream_event(
        event_stream,
        content_accumulate='I will inspect the workspace.',
        visible_accum='I will inspect the workspace.',
        tool_calls_list=[
            {
                'id': 'call_1',
                'type': 'function',
                'function': {'name': 'read', 'arguments': '{}'},
            }
        ],
    )

    emitted = event_stream.add_event.call_args.args[0]
    assert emitted.is_final is True
    assert emitted.accumulated == ''
    assert emitted.suppress_live_response is True


def test_executor_emits_streaming_chunk_actions(monkeypatch):
    """Executor should emit StreamingChunkAction events even when provider streaming is unavailable."""
    # The executor keeps a proxy to a module name under the `app.*` namespace.
    # In unit tests we import via `backend.*`, so we register an alias to keep
    # the proxy resolvable.
    import backend.engine.function_calling.dispatch as fc
    from backend.engine.executor import OrchestratorExecutor

    sys.modules.setdefault('app.engine.function_calling', fc)

    # Stub function calling to avoid depending on tool parsing details here.
    from backend.engine import executor as executor_module

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: [],
    )

    llm = MagicMock()
    llm.completion.return_value = SimpleNamespace(
        id='r1',
        choices=[SimpleNamespace(message=SimpleNamespace(content='hello world'))],
    )

    planner = MagicMock()
    event_stream = _event_stream('test-sync-streaming-chunks')

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=planner,
        mcp_tools_provider=lambda: {},
    )

    executor.execute({'messages': [], 'stream': True}, event_stream)

    # At least one streaming event should be emitted.
    assert event_stream.add_event.call_count >= 1


def test_executor_content_to_str_supports_output_text_parts():
    from backend.engine.executor import OrchestratorExecutor

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    content = [
        {'type': 'output_text', 'text': 'Hello'},
        {'type': 'text', 'text': ' world'},
    ]
    assert executor._content_to_str(content) == 'Hello world'


def test_executor_extract_last_user_text_supports_object_messages():
    from backend.engine.executor import OrchestratorExecutor

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    messages = cast(
        list[dict[str, Any]],
        [
            {'role': 'system', 'content': 'sys'},
            {
                'role': 'user',
                'content': [{'type': 'output_text', 'text': 'say hello back please'}],
            },
        ],
    )

    assert executor._extract_last_user_text(messages) == 'say hello back please'


def test_async_execute_emits_real_streaming_chunks(monkeypatch):
    """async_execute should stream real chunks via astream and emit StreamingChunkAction."""
    import backend.engine.function_calling.dispatch as fc
    from backend.engine.executor import OrchestratorExecutor

    monkeypatch.setenv('APP_STREAM_EMIT_INTERVAL_MS', '0')
    monkeypatch.setenv('APP_STREAM_EMIT_MIN_CHARS', '1')

    sys.modules.setdefault('app.engine.function_calling', fc)

    from backend.engine import executor as executor_module

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: [],
    )

    # Build fake async streaming chunks (OpenAI-style format)
    async def fake_astream(**kwargs):
        # sourcery skip: no-loop-in-tests
        for token in ['Hello', ', ', 'world', '!']:
            yield {
                'id': 'chatcmpl-test',
                'model': 'test-model',
                'choices': [{'delta': {'content': token}, 'finish_reason': None}],
            }
        # Final chunk with finish_reason
        yield {
            'id': 'chatcmpl-test',
            'model': 'test-model',
            'choices': [{'delta': {}, 'finish_reason': 'stop'}],
        }

    llm = MagicMock()
    llm.astream = fake_astream

    event_stream = _event_stream('test-async-real-streaming-chunks')

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    asyncio.run(executor.async_execute({'messages': []}, event_stream))

    calls = event_stream.add_event.call_args_list
    chunks = [c[0][0] for c in calls]
    non_final = [chunk for chunk in chunks if not chunk.is_final]
    final_chunks = [chunk for chunk in chunks if chunk.is_final]

    assert len(non_final) >= 4
    assert final_chunks
    assert final_chunks[-1].accumulated == 'Hello, world!'
    assert ''.join(chunk.chunk for chunk in non_final) == 'Hello, world!'


def test_async_execute_preserves_streamed_reasoning_content(monkeypatch):
    """DeepSeek thinking-mode streams must replay reasoning_content next turn."""
    import backend.engine.function_calling.dispatch as fc
    from backend.engine.executor import OrchestratorExecutor

    sys.modules.setdefault('app.engine.function_calling', fc)

    from backend.engine import executor as executor_module

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: [],
    )

    async def fake_astream(**kwargs):
        yield {
            'id': 'chatcmpl-reasoning',
            'model': 'deepseek-v4-flash',
            'choices': [
                {
                    'delta': {'reasoning_content': 'think one '},
                    'finish_reason': None,
                }
            ],
        }
        yield {
            'id': 'chatcmpl-reasoning',
            'model': 'deepseek-v4-flash',
            'choices': [
                {
                    'delta': {'reasoning_content': 'think two'},
                    'finish_reason': None,
                }
            ],
        }
        yield {
            'id': 'chatcmpl-reasoning',
            'model': 'deepseek-v4-flash',
            'choices': [{'delta': {'content': 'done'}, 'finish_reason': None}],
        }
        yield {
            'id': 'chatcmpl-reasoning',
            'model': 'deepseek-v4-flash',
            'choices': [{'delta': {}, 'finish_reason': 'stop'}],
        }

    llm = MagicMock()
    llm.astream = fake_astream

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    result = asyncio.run(
        executor.async_execute(
            {'messages': []},
            _event_stream('test-streamed-reasoning-content'),
        )
    )

    resp = result.response
    assert resp is not None
    assert resp.content == 'done'
    assert resp.reasoning_content == 'think one think two'
    assert resp.choices[0].message.reasoning_content == 'think one think two'
    assert (
        resp.to_dict()['choices'][0]['message']['reasoning_content']
        == 'think one think two'
    )


def test_async_execute_preserves_vercel_gateway_reasoning_delta(monkeypatch):
    """Vercel AI Gateway streams reasoning in delta.reasoning."""
    import backend.engine.function_calling.dispatch as fc
    from backend.engine.executor import OrchestratorExecutor

    sys.modules.setdefault('app.engine.function_calling', fc)

    from backend.engine import executor as executor_module

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: [],
    )

    async def fake_astream(**kwargs):
        yield {
            'id': 'chatcmpl-vercel-reasoning',
            'model': 'minimax/minimax-m3',
            'choices': [
                {
                    'delta': {'reasoning': 'Let me think. '},
                    'finish_reason': None,
                }
            ],
        }
        yield {
            'id': 'chatcmpl-vercel-reasoning',
            'model': 'minimax/minimax-m3',
            'choices': [
                {
                    'delta': {'reasoning': 'Step two.'},
                    'finish_reason': None,
                }
            ],
        }
        yield {
            'id': 'chatcmpl-vercel-reasoning',
            'model': 'minimax/minimax-m3',
            'choices': [{'delta': {'content': 'Answer.'}, 'finish_reason': None}],
        }
        yield {
            'id': 'chatcmpl-vercel-reasoning',
            'model': 'minimax/minimax-m3',
            'choices': [{'delta': {}, 'finish_reason': 'stop'}],
        }

    llm = MagicMock()
    llm.astream = fake_astream

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    result = asyncio.run(
        executor.async_execute(
            {'messages': []},
            _event_stream('test-vercel-gateway-reasoning-delta'),
        )
    )

    resp = result.response
    assert resp is not None
    assert resp.content == 'Answer.'
    assert resp.reasoning_content == 'Let me think. Step two.'


def test_async_execute_preserves_reasoning_details_delta(monkeypatch):
    """Gateway reasoning_details chunks must route to thinking, not visible text."""
    import backend.engine.function_calling.dispatch as fc
    from backend.engine.executor import OrchestratorExecutor

    sys.modules.setdefault('app.engine.function_calling', fc)

    from backend.engine import executor as executor_module

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: [],
    )

    async def fake_astream(**kwargs):
        yield {
            'id': 'chatcmpl-reasoning-details',
            'model': 'minimax/minimax-m3',
            'choices': [
                {
                    'delta': {
                        'reasoning_details': [
                            {
                                'type': 'reasoning.text',
                                'text': 'Plan the fix. ',
                                'index': 0,
                            }
                        ],
                    },
                    'finish_reason': None,
                }
            ],
        }
        yield {
            'id': 'chatcmpl-reasoning-details',
            'model': 'minimax/minimax-m3',
            'choices': [
                {
                    'delta': {
                        'content': [
                            {'type': 'reasoning.text', 'text': 'hidden thought'},
                            {'type': 'text', 'text': 'Visible answer.'},
                        ],
                    },
                    'finish_reason': None,
                }
            ],
        }
        yield {
            'id': 'chatcmpl-reasoning-details',
            'model': 'minimax/minimax-m3',
            'choices': [{'delta': {}, 'finish_reason': 'stop'}],
        }

    llm = MagicMock()
    llm.astream = fake_astream

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    result = asyncio.run(
        executor.async_execute(
            {'messages': []},
            _event_stream('test-reasoning-details-delta'),
        )
    )

    resp = result.response
    assert resp is not None
    assert resp.content == 'Visible answer.'
    assert resp.reasoning_content == 'Plan the fix. hidden thought'


def test_async_execute_preserves_redacted_thinking_in_content(monkeypatch):
    """MiniMax native format embeds thinking in content when reasoning_split is off."""
    import backend.engine.function_calling.dispatch as fc
    from backend.engine.executor import OrchestratorExecutor

    sys.modules.setdefault('app.engine.function_calling', fc)

    from backend.engine import executor as executor_module

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: [],
    )

    async def fake_astream(**kwargs):
        yield {
            'id': 'chatcmpl-inline-think',
            'model': 'minimax/minimax-m3',
            'choices': [
                {
                    'delta': {
                        'content': '<think>Plan step one. ',
                    },
                    'finish_reason': None,
                }
            ],
        }
        yield {
            'id': 'chatcmpl-inline-think',
            'model': 'minimax/minimax-m3',
            'choices': [
                {
                    'delta': {
                        'content': 'Step two.</think>Answer.',
                    },
                    'finish_reason': None,
                }
            ],
        }
        yield {
            'id': 'chatcmpl-inline-think',
            'model': 'minimax/minimax-m3',
            'choices': [{'delta': {}, 'finish_reason': 'stop'}],
        }

    llm = MagicMock()
    llm.astream = fake_astream

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    result = asyncio.run(
        executor.async_execute(
            {'messages': []},
            _event_stream('test-redacted-thinking-inline'),
        )
    )

    resp = result.response
    assert resp is not None
    assert resp.content == 'Answer.'
    assert resp.reasoning_content == 'Plan step one. Step two.'


def test_async_execute_clamps_completion_budget_before_stream_call(monkeypatch):
    import backend.engine.function_calling.dispatch as fc
    from backend.engine.executor import OrchestratorExecutor

    sys.modules.setdefault('app.engine.function_calling', fc)

    from backend.engine import executor as executor_module

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: [],
    )

    captured: dict[str, Any] = {}

    async def fake_astream(**kwargs):
        captured.update(kwargs)
        yield {
            'id': 'chatcmpl-clamped',
            'model': 'test-model',
            'choices': [{'delta': {'content': 'ok'}, 'finish_reason': None}],
        }
        yield {
            'id': 'chatcmpl-clamped',
            'model': 'test-model',
            'choices': [{'delta': {}, 'finish_reason': 'stop'}],
        }

    llm = MagicMock()
    llm.astream = fake_astream
    llm.context_window = MagicMock(return_value=650)
    llm.config = SimpleNamespace(
        model='test-model',
        max_input_tokens=600,
        max_output_tokens=300,
    )
    llm.features = SimpleNamespace(
        max_input_tokens=600,
        max_output_tokens=300,
    )

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    params = {'messages': [{'role': 'user', 'content': 'x' * 2000}]}
    expected = executor._apply_context_window_preflight(dict(params))

    asyncio.run(
        executor.async_execute(
            params,
            _event_stream('test-completion-budget-clamp'),
        )
    )

    assert captured['max_tokens'] == expected['max_tokens']
    assert captured['max_tokens'] < 300


def test_async_execute_raises_preflight_context_error_before_provider_call(
    monkeypatch,
):
    import backend.engine.function_calling.dispatch as fc
    from backend.engine.executor import OrchestratorExecutor

    sys.modules.setdefault('app.engine.function_calling', fc)

    from backend.engine import executor as executor_module

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: [],
    )

    llm = MagicMock()
    llm.astream = MagicMock()
    llm.context_window = MagicMock(return_value=240)
    llm.config = SimpleNamespace(
        model='test-model',
        max_input_tokens=220,
        max_output_tokens=64,
    )
    llm.features = SimpleNamespace(
        max_input_tokens=220,
        max_output_tokens=64,
    )

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    params = {'messages': [{'role': 'user', 'content': 'x' * 3000}]}

    with pytest.raises(ContextWindowExceededError):
        asyncio.run(
            executor.async_execute(
                params,
                _event_stream('test-preflight-context-error'),
            )
        )

    llm.astream.assert_not_called()


def test_async_execute_does_not_timeout_active_reasoning_stream(monkeypatch, tmp_path):
    """Active reasoning streams are governed by per-chunk stall timeouts."""
    import backend.engine.function_calling.dispatch as fc
    from backend.engine.executor import OrchestratorExecutor

    sys.modules.setdefault('app.engine.function_calling', fc)

    from backend.engine import executor as executor_module

    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('APP_LLM_STEP_TIMEOUT_SECONDS', '0.01')
    monkeypatch.setenv('APP_LLM_FIRST_CHUNK_TIMEOUT_SECONDS', '1')
    monkeypatch.setenv('APP_LLM_STREAM_CHUNK_TIMEOUT_SECONDS', '1')
    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: [],
    )

    async def fake_astream(**kwargs):
        yield {
            'id': 'chatcmpl-slow-thinking',
            'model': 'deepseek-v4-flash',
            'choices': [
                {
                    'delta': {'reasoning_content': 'still thinking'},
                    'finish_reason': None,
                }
            ],
        }
        await asyncio.sleep(0.03)
        yield {
            'id': 'chatcmpl-slow-thinking',
            'model': 'deepseek-v4-flash',
            'choices': [{'delta': {'content': 'done'}, 'finish_reason': None}],
        }
        yield {
            'id': 'chatcmpl-slow-thinking',
            'model': 'deepseek-v4-flash',
            'choices': [{'delta': {}, 'finish_reason': 'stop'}],
        }

    llm = MagicMock()
    llm.astream = fake_astream

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    result = asyncio.run(
        executor.async_execute(
            {'messages': []},
            _event_stream('test-non-streaming-fallback'),
        )
    )

    assert result.response is not None
    assert result.response.content == 'done'
    assert result.response.reasoning_content == 'still thinking'


def test_cancel_step_cancels_active_stream_and_discards_checkpoint(
    monkeypatch, tmp_path
):
    import backend.engine.function_calling.dispatch as fc
    from backend.engine.executor import OrchestratorExecutor

    sys.modules.setdefault('app.engine.function_calling', fc)

    from backend.engine import executor as executor_module

    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('APP_LLM_FIRST_CHUNK_TIMEOUT_SECONDS', '1')
    monkeypatch.setenv('APP_LLM_STREAM_CHUNK_TIMEOUT_SECONDS', '1')
    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: [],
    )

    async def run_case() -> None:
        first_chunk_seen = asyncio.Event()
        stream_closed = asyncio.Event()

        async def fake_astream(**kwargs):
            try:
                yield {
                    'id': 'chatcmpl-cancel',
                    'model': 'test-model',
                    'choices': [
                        {'delta': {'content': 'partial'}, 'finish_reason': None}
                    ],
                }
                first_chunk_seen.set()
                while True:
                    await asyncio.sleep(10)
            finally:
                stream_closed.set()

        llm = MagicMock()
        llm.astream = fake_astream

        executor = OrchestratorExecutor(
            llm=llm,
            safety_manager=cast(NoopSafetyManager, _Safety()),
            planner=MagicMock(),
            mcp_tools_provider=lambda: {},
        )

        task = asyncio.create_task(
            executor.async_execute(
                {'messages': []},
                _event_stream('test-streaming-cancel'),
            )
        )
        await asyncio.wait_for(first_chunk_seen.wait(), timeout=1)

        executor.cancel_step()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        await asyncio.wait_for(stream_closed.wait(), timeout=1)
        assert not list(tmp_path.rglob('streaming_wal.json'))

    asyncio.run(run_case())


def test_async_execute_accumulates_tool_calls(monkeypatch):
    """async_execute should accumulate streamed tool call deltas into complete tool calls."""
    import backend.engine.function_calling.dispatch as fc
    from backend.engine.executor import OrchestratorExecutor
    from backend.ledger.action import AgentThinkAction

    sys.modules.setdefault('app.engine.function_calling', fc)

    from backend.engine import executor as executor_module

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda response, **kwargs: [AgentThinkAction(thought='tool_call_detected')],
    )

    # Simulate streamed tool call deltas
    async def fake_astream(**kwargs):
        yield {
            'id': 'chatcmpl-tc',
            'model': 'test-model',
            'choices': [
                {
                    'delta': {
                        'tool_calls': [
                            {
                                'index': 0,
                                'id': 'call_abc',
                                'function': {'name': 'read_file', 'arguments': '{"pa'},
                            }
                        ]
                    }
                }
            ],
        }
        yield {
            'id': 'chatcmpl-tc',
            'model': 'test-model',
            'choices': [
                {
                    'delta': {
                        'tool_calls': [
                            {
                                'index': 0,
                                'function': {'arguments': 'th": "/tmp/test.py"}'},
                            }
                        ]
                    }
                }
            ],
        }
        yield {
            'id': 'chatcmpl-tc',
            'model': 'test-model',
            'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}],
        }

    llm = MagicMock()
    llm.astream = fake_astream

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    event_stream = _event_stream('test-stream-accumulates-tool-calls')
    result = asyncio.run(executor.async_execute({'messages': []}, event_stream))

    # The response should have assembled the tool call from fragments
    resp = result.response
    assert resp is not None
    assert resp.tool_calls is not None
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc['id'] == 'call_abc'
    assert tc['function']['name'] == 'read_file'
    assert tc['function']['arguments'] == '{"path": "/tmp/test.py"}'


def test_async_execute_handles_cumulative_tool_call_name_and_args(monkeypatch):
    """Stream assembly should not duplicate tool names for cumulative chunks."""
    import backend.engine.function_calling.dispatch as fc
    from backend.engine.executor import OrchestratorExecutor
    from backend.ledger.action import AgentThinkAction

    sys.modules.setdefault('app.engine.function_calling', fc)

    from backend.engine import executor as executor_module

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda response, **kwargs: [AgentThinkAction(thought='tool_call_detected')],
    )

    async def fake_astream(**kwargs):
        yield {
            'id': 'chatcmpl-cum',
            'model': 'test-model',
            'choices': [
                {
                    'delta': {
                        'tool_calls': [
                            {
                                'index': 0,
                                'id': 'call_dup',
                                'function': {
                                    'name': 'analyze_project_structure',
                                    'arguments': '{"command": "tree", "path": "."}',
                                },
                            }
                        ]
                    }
                }
            ],
        }
        # Provider resends cumulative name + full arguments on next chunk.
        yield {
            'id': 'chatcmpl-cum',
            'model': 'test-model',
            'choices': [
                {
                    'delta': {
                        'tool_calls': [
                            {
                                'index': 0,
                                'function': {
                                    'name': 'analyze_project_structure',
                                    'arguments': '{"command": "tree", "path": ".", "depth": 2}',
                                },
                            }
                        ]
                    }
                }
            ],
        }
        yield {
            'id': 'chatcmpl-cum',
            'model': 'test-model',
            'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}],
        }

    llm = MagicMock()
    llm.astream = fake_astream

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    event_stream = _event_stream('test-stream-cumulative-tool-call')
    result = asyncio.run(executor.async_execute({'messages': []}, event_stream))

    resp = result.response
    assert resp is not None
    assert resp.tool_calls is not None
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc['id'] == 'call_dup'
    assert tc['function']['name'] == 'analyze_project_structure'
    assert tc['function']['arguments'] == '{"command": "tree", "path": ".", "depth": 2}'


def _stream_chunks_to_tool_args(chunks: list[str]) -> str:
    """Drive `chunks` through the live streaming path and return assembled args."""
    import backend.engine.function_calling.dispatch as fc
    from backend.engine.executor import OrchestratorExecutor
    from backend.ledger.action import AgentThinkAction

    sys.modules.setdefault('app.engine.function_calling', fc)
    from backend.engine import executor as executor_module

    captured: dict[str, Any] = {}

    def _record(response, **kwargs):
        captured['response'] = response
        return [AgentThinkAction(thought='tc_detected')]

    executor_module.orchestrator_function_calling.response_to_actions = _record  # type: ignore[assignment]

    async def fake_astream(**kwargs):
        for piece in chunks:
            yield {
                'id': 'chatcmpl-x',
                'model': 'test-model',
                'choices': [
                    {
                        'delta': {
                            'tool_calls': [
                                {
                                    'index': 0,
                                    'id': 'call_x',
                                    'function': {
                                        'name': 'read',
                                        'arguments': piece,
                                    },
                                }
                            ]
                        }
                    }
                ],
            }
        yield {
            'id': 'chatcmpl-x',
            'model': 'test-model',
            'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}],
        }

    llm = MagicMock()
    llm.astream = fake_astream

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    event_stream = _event_stream(f'test-stream-chunks-{abs(hash(tuple(chunks)))}')
    asyncio.run(executor.async_execute({'messages': []}, event_stream))
    resp = captured.get('response')
    assert resp is not None
    assert resp.tool_calls is not None
    return resp.tool_calls[0]['function']['arguments']


def test_append_only_delta_preserves_content_even_when_chunk_is_substring_of_prefix():
    r"""Regression: ``_merge_stream_fragment`` used to silently drop a delta if
    it appeared anywhere in the accumulated prefix.

    Observed in logs (Kimi K2.5, CSS body): after streaming ~500 chars of
    CSS, a later delta of ``";\\n    justify"`` was erased because the
    substring ``";\\n    "`` already appeared earlier. The file on disk
    then read ``margin-top: 25px-content: center;`` instead of the correct
    ``margin-top: 25px;\\n    justify-content: center;``.
    """
    # Simulate: prefix of arguments ends with "};\n    " pattern, then a
    # short whitespace+punctuation delta that *happens* to reappear inside
    # the prefix. Plain concatenation must preserve it verbatim.
    prefix = (
        '{"path": "styles.css", "old_string": "/* old */", "new_string": '
        '"h1 {\\n    color: #fff;\\n    margin-bottom: 20px;\\n}\\n\\n'
        '.controls {\\n    margin-top: 25px'
    )
    mid = ';\\n    justify'
    tail = '-content: center;\\n}"}'
    result = _stream_chunks_to_tool_args([prefix, mid, tail])
    assert result == prefix + mid + tail, (
        'append-only delta was mutated by merge heuristics; got:\n' + result
    )
    assert 'justify-content' in result
    # The specific corruption pattern we saw in the bug report must not appear.
    assert '25px-content' not in result


def test_append_only_delta_preserves_plain_closing_brace_chunk():
    """Regression: a single-char ``"}"`` delta after the object opener was
    dropped because it was a suffix of existing content like ``{"command": "x"}``.

    We must never drop a delta just because it is a suffix of the accumulator.
    """
    # existing ends with "}"; next delta starts with "}," extending the object.
    # With the old overlap heuristic this could merge to ``{"a":"b","c":"d"`` —
    # dropping characters at the boundary. The new logic must give the full JSON.
    parts = ['{"a":"b"', '}', '  ']
    result = _stream_chunks_to_tool_args(parts)
    assert result == '{"a":"b"}  '


def test_suffix_prefix_overlap_is_not_silently_trimmed():
    """Regression for the ``for (let col++) {`` corruption.

    When existing ends with ``"col"`` and the next delta starts with ``"col"``
    (e.g. identifier ``column`` split across chunks, or two uses of ``col`` back-to-back),
    the old overlap heuristic ate one copy, producing ``col`` instead of ``colcol``.
    """
    parts = ['for (let col', 'col++)']
    result = _stream_chunks_to_tool_args(parts)
    assert result == 'for (let colcol++)'


def test_cumulative_snapshot_still_detected_when_provider_resends_full_args():
    """The second chunk restates everything from the first, with extra fields.

    Behaviour for snapshot providers is preserved: the second chunk should
    replace rather than concatenate.
    """
    parts = [
        '{"command": "tree", "path": "."}',
        '{"command": "tree", "path": ".", "depth": 2}',
    ]
    result = _stream_chunks_to_tool_args(parts)
    assert result == '{"command": "tree", "path": ".", "depth": 2}'


def test_exact_duplicate_chunk_is_collapsed():
    """Provider retried the same chunk — we must collapse, not double."""
    parts = ['{"a":1', '{"a":1', ',"b":2}']
    result = _stream_chunks_to_tool_args(parts)
    assert result == '{"a":1,"b":2}'


def test_get_checkpoint_clears_stale_wal_when_persisted_control_event_proves_progress(
    monkeypatch, tmp_path
):
    from backend.core.enums import AgentState
    from backend.engine.executor import OrchestratorExecutor
    from backend.engine.streaming_checkpoint import StreamingCheckpoint
    from backend.ledger.observation import AgentStateChangedObservation

    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path))

    event_stream = _event_stream('sid-1')
    event_stream.sid = 'sid-1'
    control_event = AgentStateChangedObservation('', agent_state=AgentState.FINISHED)
    control_event.id = 9
    event_stream.search_events.return_value = [control_event]

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    checkpoint = StreamingCheckpoint(str(tmp_path / 'streaming_checkpoints' / 'sid-1'))
    checkpoint.begin({'messages': []}, anchor_event_id=5)

    resolved = executor._get_checkpoint(event_stream)

    assert resolved.inspect_recovery().status == 'clean'


def test_get_checkpoint_blocks_when_no_persisted_control_event_supersedes_wal(
    monkeypatch, tmp_path
):
    from backend.engine.executor import OrchestratorExecutor
    from backend.engine.streaming_checkpoint import (
        StreamingCheckpoint,
        StreamingCheckpointRecoveryError,
    )

    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path))

    event_stream = _event_stream('sid-2')
    event_stream.sid = 'sid-2'
    event_stream.search_events.return_value = []

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    checkpoint = StreamingCheckpoint(str(tmp_path / 'streaming_checkpoints' / 'sid-2'))
    checkpoint.begin({'messages': []}, anchor_event_id=5)

    with pytest.raises(StreamingCheckpointRecoveryError):
        executor._get_checkpoint(event_stream)

    assert checkpoint._wal_path.exists()


def test_get_checkpoint_blocks_stale_wal_when_auto_discard_disabled(
    monkeypatch, tmp_path
):
    from backend.engine.executor import OrchestratorExecutor
    from backend.engine.streaming_checkpoint import (
        StreamingCheckpoint,
        StreamingCheckpointRecoveryError,
    )

    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path))

    event_stream = _event_stream('sid-3')
    event_stream.sid = 'sid-stale'
    event_stream.search_events.return_value = []

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=cast(NoopSafetyManager, _Safety()),
        planner=_planner_with_checkpoint_policy(
            max_age=1.0,
            discard_stale_on_recovery=False,
        ),
        mcp_tools_provider=lambda: {},
    )

    checkpoint_path = tmp_path / 'streaming_checkpoints' / 'sid-stale'
    checkpoint = StreamingCheckpoint(
        str(checkpoint_path),
        max_checkpoint_age_sec=1.0,
        discard_stale_on_recovery=False,
    )
    checkpoint.begin({'messages': []}, anchor_event_id=5)
    _mark_checkpoint_stale(checkpoint)

    with pytest.raises(StreamingCheckpointRecoveryError):
        executor._get_checkpoint(event_stream)

    assert checkpoint._wal_path.exists()


def test_get_checkpoint_clears_stale_wal_for_resumed_session_with_persisted_control_event(
    monkeypatch, tmp_path
):
    from backend.core.enums import AgentState
    from backend.engine.executor import OrchestratorExecutor
    from backend.engine.streaming_checkpoint import StreamingCheckpoint
    from backend.ledger import EventSource
    from backend.ledger.observation import (
        AgentStateChangedObservation,
        NullObservation,
    )
    from backend.ledger.stream import EventStream
    from backend.persistence.file_store.local_file_store import LocalFileStore

    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path / 'appdata'))
    monkeypatch.setenv('APP_SQLITE_EVENTS', '0')

    file_store = LocalFileStore(str(tmp_path / 'events'))
    initial_stream = EventStream(
        'sid-resume-progress',
        file_store,
        worker_count=0,
        async_write=False,
    )
    try:
        initial_stream.add_event(NullObservation('before'), EventSource.AGENT)
        initial_stream.add_event(
            AgentStateChangedObservation('', agent_state=AgentState.FINISHED),
            EventSource.AGENT,
        )
    finally:
        initial_stream.close()

    checkpoint = StreamingCheckpoint(
        str(tmp_path / 'appdata' / 'streaming_checkpoints' / 'sid-resume-progress'),
        max_checkpoint_age_sec=1.0,
        discard_stale_on_recovery=False,
    )
    checkpoint.begin({'messages': []}, anchor_event_id=0)
    _mark_checkpoint_stale(checkpoint)

    resumed_stream = EventStream(
        'sid-resume-progress',
        file_store,
        worker_count=0,
        async_write=False,
    )
    try:
        executor = OrchestratorExecutor(
            llm=MagicMock(),
            safety_manager=cast(NoopSafetyManager, _Safety()),
            planner=_planner_with_checkpoint_policy(
                max_age=1.0,
                discard_stale_on_recovery=False,
            ),
            mcp_tools_provider=lambda: {},
        )

        resolved = executor._get_checkpoint(resumed_stream)

        assert resolved.inspect_recovery().status == 'clean'
        assert not checkpoint._wal_path.exists()
    finally:
        resumed_stream.close()


def test_get_checkpoint_blocks_resumed_session_without_superseding_control_event(
    monkeypatch, tmp_path
):
    from backend.engine.executor import OrchestratorExecutor
    from backend.engine.streaming_checkpoint import (
        StreamingCheckpoint,
        StreamingCheckpointRecoveryError,
    )
    from backend.ledger import EventSource
    from backend.ledger.observation import NullObservation
    from backend.ledger.stream import EventStream
    from backend.persistence.file_store.local_file_store import LocalFileStore

    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path / 'appdata'))
    monkeypatch.setenv('APP_SQLITE_EVENTS', '0')

    file_store = LocalFileStore(str(tmp_path / 'events'))
    initial_stream = EventStream(
        'sid-resume-blocked',
        file_store,
        worker_count=0,
        async_write=False,
    )
    try:
        initial_stream.add_event(NullObservation('before'), EventSource.AGENT)
    finally:
        initial_stream.close()

    checkpoint = StreamingCheckpoint(
        str(tmp_path / 'appdata' / 'streaming_checkpoints' / 'sid-resume-blocked'),
        max_checkpoint_age_sec=1.0,
        discard_stale_on_recovery=False,
    )
    checkpoint.begin({'messages': []}, anchor_event_id=0)
    _mark_checkpoint_stale(checkpoint)

    resumed_stream = EventStream(
        'sid-resume-blocked',
        file_store,
        worker_count=0,
        async_write=False,
    )
    try:
        executor = OrchestratorExecutor(
            llm=MagicMock(),
            safety_manager=cast(NoopSafetyManager, _Safety()),
            planner=_planner_with_checkpoint_policy(
                max_age=1.0,
                discard_stale_on_recovery=False,
            ),
            mcp_tools_provider=lambda: {},
        )

        with pytest.raises(StreamingCheckpointRecoveryError):
            executor._get_checkpoint(resumed_stream)

        assert checkpoint._wal_path.exists()
    finally:
        resumed_stream.close()


def test_response_to_actions_gates_plain_message_in_agent_mode(
    monkeypatch,
):
    """Before tracker commitment, Agent mode can answer in plain prose."""
    from backend.engine import executor as executor_module
    from backend.engine.executor import OrchestratorExecutor
    from backend.ledger.action import MessageAction

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: [
            MessageAction(content="I've created grinta_feedback.md for you.")
        ],
    )

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=NoopSafetyManager(),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="I've created grinta_feedback.md for you."
                )
            )
        ]
    )

    actions = executor._response_to_actions(response)

    assert len(actions) == 1
    assert isinstance(actions[0], MessageAction)
    assert actions[0].content == "I've created grinta_feedback.md for you."


def test_response_to_actions_gates_conversational_plain_message(monkeypatch):
    from backend.engine import executor as executor_module
    from backend.engine.executor import OrchestratorExecutor
    from backend.ledger.action import MessageAction

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: [
            MessageAction(
                content='I have prepared a rating of the system and the tools for you.'
            )
        ],
    )

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=NoopSafetyManager(),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='I have prepared a rating of the system and the tools for you.'
                )
            )
        ]
    )

    actions = executor._response_to_actions(response)

    assert len(actions) == 1
    assert isinstance(actions[0], MessageAction)
    assert (
        actions[0].content
        == 'I have prepared a rating of the system and the tools for you.'
    )


def test_response_to_actions_allows_structured_non_runnable_action(monkeypatch):
    from backend.engine import executor as executor_module
    from backend.engine.executor import OrchestratorExecutor
    from backend.ledger.action import ProposalAction

    proposal = ProposalAction(
        options=[{'approach': 'Direct answer', 'pros': [], 'cons': []}],
        rationale='Prepared options for the user.',
    )

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: [proposal],
    )

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=NoopSafetyManager(),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="I've prepared two approaches for your feedback."
                )
            )
        ]
    )

    actions = executor._response_to_actions(response)

    assert actions == [proposal]


def test_response_to_actions_converts_core_tool_call_validation_error_to_recoverable_action(
    monkeypatch,
):
    from backend.core.errors import FunctionCallValidationError
    from backend.engine import executor as executor_module
    from backend.engine.executor import OrchestratorExecutor
    from backend.ledger.action import AgentThinkAction

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: (_ for _ in ()).throw(
            FunctionCallValidationError('bad JSON arguments')
        ),
    )

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=NoopSafetyManager(),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='tool call'))]
    )
    actions = executor._response_to_actions(response)

    assert len(actions) == 1
    assert isinstance(actions[0], AgentThinkAction)
    assert '[TOOL_CALL_RECOVERABLE_ERROR]' not in (actions[0].thought or '')
    assert actions[0].kind == AgentThinkAction.KIND_RECOVERABLE_ERROR
    assert 'bad JSON arguments' in (actions[0].thought or '')


def test_response_to_actions_adds_task_status_alias_hint(monkeypatch):
    from backend.core.errors import FunctionCallValidationError
    from backend.engine import executor as executor_module
    from backend.engine.executor import OrchestratorExecutor
    from backend.ledger.action import AgentThinkAction

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: (_ for _ in ()).throw(
            FunctionCallValidationError(
                "Invalid task status 'doing'. Use one of: blocked, in_progress, done, skipped, todo."
            )
        ),
    )

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=NoopSafetyManager(),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='tool call'))]
    )
    actions = executor._response_to_actions(response)

    assert len(actions) == 1
    assert isinstance(actions[0], AgentThinkAction)
    thought = actions[0].thought or ''
    assert '`todo`, `in_progress`, `done`, `skipped`, `blocked`' in thought


def test_response_to_actions_converts_common_tool_call_validation_error_to_recoverable_action(
    monkeypatch,
):
    from backend.engine import executor as executor_module
    from backend.engine.executor import OrchestratorExecutor
    from backend.engine.response_processing import FunctionCallValidationError
    from backend.ledger.action import AgentThinkAction

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *args, **kwargs: (_ for _ in ()).throw(
            FunctionCallValidationError('malformed tool call payload')
        ),
    )

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=NoopSafetyManager(),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='tool call'))]
    )
    actions = executor._response_to_actions(response)

    assert len(actions) == 1
    assert isinstance(actions[0], AgentThinkAction)
    assert '[TOOL_CALL_RECOVERABLE_ERROR]' not in (actions[0].thought or '')
    assert actions[0].kind == AgentThinkAction.KIND_RECOVERABLE_ERROR
    assert 'malformed tool call payload' in (actions[0].thought or '')


def test_fallback_completion_inline_thinking_parsing():
    """Verify that fallback completions containing inline thinking tags are parsed correctly."""
    from backend.engine.executor import OrchestratorExecutor
    from backend.engine.executor_mixins._executor_types import _AsyncStreamingState

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=MagicMock(),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    state = _AsyncStreamingState()
    # Partially accumulated stream content:
    state.content_accumulate = (
        'Let me start by:\n1. Doing research\n2. Exploring the current directory to '
    )
    state.thinking_accumulate = 'Raft-based key-value store simulation.'

    # Non-streaming fallback response carrying both inline thinking and full content:
    fallback_text = (
        '<think>Raft-based key-value store simulation.</think>'
        "Let me start by:\n1. Doing research\n2. Exploring the current directory to understand what's there"
    )
    fallback = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=fallback_text))]
    )

    # Apply fallback
    import anyio

    anyio.run(executor._apply_fallback_completion, fallback, state, None)

    # Check results: content and thinking should be parsed and merged with no duplicates!
    assert state.thinking_accumulate == 'Raft-based key-value store simulation.'
    assert state.content_accumulate == (
        "Let me start by:\n1. Doing research\n2. Exploring the current directory to understand what's there"
    )
