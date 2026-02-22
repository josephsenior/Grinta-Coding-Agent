from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock


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
        executor_module.codeact_function_calling,
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
        safety_manager=_Safety(),
        planner=planner,
        mcp_tool_name_provider=lambda: [],
    )

    executor.execute({"messages": [], "stream": True}, event_stream)

    # At least one streaming event should be emitted.
    assert event_stream.add_event.call_count >= 1
