from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from backend.engine.safety import OrchestratorSafetyManager


class _Safety:
    def apply(self, response_text, actions):
        return True, actions


def test_executor_emits_streaming_chunk_actions(monkeypatch):
    """Executor should emit StreamingChunkAction events even when provider streaming is unavailable."""
    # The executor keeps a proxy to a module name under the `app.*` namespace.
    # In unit tests we import via `backend.*`, so we register an alias to keep
    # the proxy resolvable.
    import backend.engine.function_calling as fc
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
    event_stream = MagicMock()

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(OrchestratorSafetyManager, _Safety()),
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
        safety_manager=cast(OrchestratorSafetyManager, _Safety()),
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
        safety_manager=cast(OrchestratorSafetyManager, _Safety()),
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
    import backend.engine.function_calling as fc
    from backend.engine.executor import OrchestratorExecutor

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

    event_stream = MagicMock()

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(OrchestratorSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    asyncio.run(executor.async_execute({'messages': []}, event_stream))

    # Should have emitted streaming chunks (4 content chunks + 1 final marker)
    assert event_stream.add_event.call_count == 5

    # Check that the chunks were real streaming tokens
    calls = event_stream.add_event.call_args_list
    chunks = [c[0][0] for c in calls]

    # First 4 are content chunks
    assert chunks[0].chunk == 'Hello'
    assert chunks[1].chunk == ', '
    assert chunks[2].chunk == 'world'
    assert chunks[3].chunk == '!'
    assert chunks[3].accumulated == 'Hello, world!'
    assert not chunks[3].is_final

    # Last is the final marker
    assert chunks[4].is_final
    assert chunks[4].accumulated == 'Hello, world!'


def test_async_execute_accumulates_tool_calls(monkeypatch):
    """async_execute should accumulate streamed tool call deltas into complete tool calls."""
    import backend.engine.function_calling as fc
    from backend.engine.executor import OrchestratorExecutor
    from backend.ledger.action import MessageAction

    sys.modules.setdefault('app.engine.function_calling', fc)

    from backend.engine import executor as executor_module

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda response, **kwargs: [
            MessageAction(content='tool_call_detected', wait_for_response=True)
        ],
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
        safety_manager=cast(OrchestratorSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    result = asyncio.run(executor.async_execute({'messages': []}, MagicMock()))

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
    import backend.engine.function_calling as fc
    from backend.engine.executor import OrchestratorExecutor
    from backend.ledger.action import MessageAction

    sys.modules.setdefault('app.engine.function_calling', fc)

    from backend.engine import executor as executor_module

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda response, **kwargs: [
            MessageAction(content='tool_call_detected', wait_for_response=True)
        ],
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
        safety_manager=cast(OrchestratorSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    result = asyncio.run(executor.async_execute({'messages': []}, MagicMock()))

    resp = result.response
    assert resp is not None
    assert resp.tool_calls is not None
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc['id'] == 'call_dup'
    assert tc['function']['name'] == 'analyze_project_structure'
    assert tc['function']['arguments'] == '{"command": "tree", "path": ".", "depth": 2}'


def test_get_checkpoint_clears_stale_wal_when_persisted_control_event_proves_progress(
    monkeypatch, tmp_path
):
    from backend.core.enums import AgentState
    from backend.engine.executor import OrchestratorExecutor
    from backend.engine.streaming_checkpoint import StreamingCheckpoint
    from backend.ledger.observation import AgentStateChangedObservation

    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path))

    event_stream = MagicMock()
    event_stream.sid = 'sid-1'
    control_event = AgentStateChangedObservation('', agent_state=AgentState.FINISHED)
    control_event.id = 9
    event_stream.search_events.return_value = [control_event]

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=cast(OrchestratorSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    checkpoint = StreamingCheckpoint(str(tmp_path / 'streaming_checkpoints' / 'sid-1'))
    checkpoint.begin({'messages': []}, anchor_event_id=5)

    resolved = executor._get_checkpoint(event_stream)

    assert resolved.inspect_recovery().status == 'clean'
    assert not executor._recovery_blocked_reasons


def test_get_checkpoint_blocks_when_no_persisted_control_event_supersedes_wal(
    monkeypatch, tmp_path
):
    from backend.engine.executor import OrchestratorExecutor
    from backend.engine.streaming_checkpoint import StreamingCheckpoint

    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path))

    event_stream = MagicMock()
    event_stream.sid = 'sid-2'
    event_stream.search_events.return_value = []

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=cast(OrchestratorSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    checkpoint = StreamingCheckpoint(str(tmp_path / 'streaming_checkpoints' / 'sid-2'))
    checkpoint.begin({'messages': []}, anchor_event_id=5)

    executor._get_checkpoint(event_stream)

    assert 'sid-2' in executor._recovery_blocked_reasons


def test_response_to_actions_passes_through_plain_message_after_guard_disabled(
    monkeypatch,
):
    """Hallucination guard is disabled — plain messages always pass through."""
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
        safety_manager=OrchestratorSafetyManager(),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="I've created grinta_feedback.md for you.")
            )
        ]
    )

    actions = executor._response_to_actions(response)

    assert len(actions) == 1
    assert actions[0].content == "I've created grinta_feedback.md for you."  # type: ignore


def test_response_to_actions_allows_conversational_plain_message(monkeypatch):
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
        safety_manager=OrchestratorSafetyManager(),
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
    assert actions[0].content == 'I have prepared a rating of the system and the tools for you.'  # type: ignore


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
        safety_manager=OrchestratorSafetyManager(),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="I've prepared two approaches for your feedback.")
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
        safety_manager=OrchestratorSafetyManager(),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='tool call'))]
    )
    actions = executor._response_to_actions(response)

    assert len(actions) == 1
    assert isinstance(actions[0], AgentThinkAction)
    assert '[TOOL_CALL_RECOVERABLE_ERROR]' in (actions[0].thought or '')
    assert 'bad JSON arguments' in (actions[0].thought or '')


def test_response_to_actions_converts_common_tool_call_validation_error_to_recoverable_action(
    monkeypatch,
):
    from backend.engine import executor as executor_module
    from backend.engine.common import FunctionCallValidationError
    from backend.engine.executor import OrchestratorExecutor
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
        safety_manager=OrchestratorSafetyManager(),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='tool call'))]
    )
    actions = executor._response_to_actions(response)

    assert len(actions) == 1
    assert isinstance(actions[0], AgentThinkAction)
    assert '[TOOL_CALL_RECOVERABLE_ERROR]' in (actions[0].thought or '')
    assert 'malformed tool call payload' in (actions[0].thought or '')
