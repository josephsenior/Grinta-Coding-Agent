from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock
from typing import Any, cast

from backend.engines.orchestrator.safety import OrchestratorSafetyManager


class _Safety:
    def apply(self, response_text, actions):
        return True, actions


def test_executor_emits_streaming_chunk_actions(monkeypatch):
    """Executor should emit StreamingChunkAction events even when provider streaming is unavailable."""
    from backend.engines.orchestrator.executor import OrchestratorExecutor

    # The executor keeps a proxy to a module name under the `forge.*` namespace.
    # In unit tests we import via `backend.*`, so we register an alias to keep
    # the proxy resolvable.
    import backend.engines.orchestrator.function_calling as fc

    sys.modules.setdefault("forge.engines.orchestrator.function_calling", fc)

    # Stub function calling to avoid depending on tool parsing details here.
    from backend.engines.orchestrator import executor as executor_module

    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        "response_to_actions",
        lambda *args, **kwargs: [],
    )

    llm = MagicMock()
    llm.completion.return_value = SimpleNamespace(
        id="r1",
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello world"))],
    )

    planner = MagicMock()
    event_stream = MagicMock()

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(OrchestratorSafetyManager, _Safety()),
        planner=planner,
        mcp_tools_provider=lambda: {},
    )

    executor.execute({"messages": [], "stream": True}, event_stream)

    # At least one streaming event should be emitted.
    assert event_stream.add_event.call_count >= 1


def test_executor_content_to_str_supports_output_text_parts():
    from backend.engines.orchestrator.executor import OrchestratorExecutor

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=cast(OrchestratorSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    content = [
        {"type": "output_text", "text": "Hello"},
        {"type": "text", "text": " world"},
    ]
    assert executor._content_to_str(content) == "Hello world"


def test_executor_extract_last_user_text_supports_object_messages():
    from backend.engines.orchestrator.executor import OrchestratorExecutor

    executor = OrchestratorExecutor(
        llm=MagicMock(),
        safety_manager=cast(OrchestratorSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    messages = cast(
        list[dict[str, Any]],
        [
        {"role": "system", "content": "sys"},
        {
            "role": "user",
            "content": [{"type": "output_text", "text": "say hello back please"}],
        },
        ],
    )

    assert executor._extract_last_user_text(messages) == "say hello back please"


def test_async_execute_emits_real_streaming_chunks(monkeypatch):
    """async_execute should stream real chunks via astream and emit StreamingChunkAction."""
    from backend.engines.orchestrator.executor import OrchestratorExecutor

    import backend.engines.orchestrator.function_calling as fc
    sys.modules.setdefault("forge.engines.orchestrator.function_calling", fc)

    from backend.engines.orchestrator import executor as executor_module
    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        "response_to_actions",
        lambda *args, **kwargs: [],
    )

    # Build fake async streaming chunks (OpenAI-style format)
    async def fake_astream(**kwargs):
        for token in ["Hello", ", ", "world", "!"]:
            yield {
                "id": "chatcmpl-test",
                "model": "test-model",
                "choices": [{"delta": {"content": token}, "finish_reason": None}],
            }
        # Final chunk with finish_reason
        yield {
            "id": "chatcmpl-test",
            "model": "test-model",
            "choices": [{"delta": {}, "finish_reason": "stop"}],
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

    result = asyncio.run(executor.async_execute({"messages": []}, event_stream))

    # Should have emitted streaming chunks (4 content chunks + 1 final marker)
    assert event_stream.add_event.call_count == 5

    # Check that the chunks were real streaming tokens
    calls = event_stream.add_event.call_args_list
    chunks = [c[0][0] for c in calls]

    # First 4 are content chunks
    assert chunks[0].chunk == "Hello"
    assert chunks[1].chunk == ", "
    assert chunks[2].chunk == "world"
    assert chunks[3].chunk == "!"
    assert chunks[3].accumulated == "Hello, world!"
    assert not chunks[3].is_final

    # Last is the final marker
    assert chunks[4].is_final
    assert chunks[4].accumulated == "Hello, world!"


def test_async_execute_accumulates_tool_calls(monkeypatch):
    """async_execute should accumulate streamed tool call deltas into complete tool calls."""
    from backend.engines.orchestrator.executor import OrchestratorExecutor
    from backend.events.action import MessageAction

    import backend.engines.orchestrator.function_calling as fc
    sys.modules.setdefault("forge.engines.orchestrator.function_calling", fc)

    from backend.engines.orchestrator import executor as executor_module
    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        "response_to_actions",
        lambda response, **kwargs: [
            MessageAction(content="tool_call_detected", wait_for_response=True)
        ],
    )

    # Simulate streamed tool call deltas
    async def fake_astream(**kwargs):
        yield {
            "id": "chatcmpl-tc",
            "model": "test-model",
            "choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_abc", "function": {"name": "read_file", "arguments": '{"pa'}}
            ]}}],
        }
        yield {
            "id": "chatcmpl-tc",
            "model": "test-model",
            "choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": 'th": "/tmp/test.py"}'}}
            ]}}],
        }
        yield {
            "id": "chatcmpl-tc",
            "model": "test-model",
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
        }

    llm = MagicMock()
    llm.astream = fake_astream

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=cast(OrchestratorSafetyManager, _Safety()),
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    result = asyncio.run(executor.async_execute({"messages": []}, MagicMock()))

    # The response should have assembled the tool call from fragments
    resp = result.response
    assert resp is not None
    assert resp.tool_calls is not None
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc["id"] == "call_abc"
    assert tc["function"]["name"] == "read_file"
    assert tc["function"]["arguments"] == '{"path": "/tmp/test.py"}'
