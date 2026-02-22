from __future__ import annotations

import sys
from types import SimpleNamespace


class _Safety:
    def apply(self, response_text, actions):
        return True, actions


class _LLMStub:
    def __init__(self, response_content: str):
        self._response_content = response_content
        self.last_kwargs = None

        # Provide a minimal features object
        self.features = SimpleNamespace(supports_stop_words=True)

    def is_function_calling_active(self) -> bool:
        return False

    def completion(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            id="r1",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self._response_content)
                )
            ],
        )


def test_executor_tool_call_fallback_parses_finish_action():
    from backend.engines.orchestrator.executor import OrchestratorExecutor
    from backend.engines.orchestrator.tools import create_finish_tool
    from backend.events.action import PlaybookFinishAction

    # The executor keeps a proxy to a module name under the `forge.*` namespace.
    # In unit tests we import via `backend.*`, so we register an alias to keep
    # the proxy resolvable.
    import backend.engines.orchestrator.function_calling as fc

    sys.modules.setdefault("forge.engines.orchestrator.function_calling", fc)

    llm = _LLMStub(
        "Sure.\n<function=finish>\n"
        "<parameter=message>done</parameter>\n"
        "</function>"
    )

    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=_Safety(),
        planner=SimpleNamespace(),
        mcp_tool_name_provider=lambda: [],
    )

    tools = [create_finish_tool()]
    result = executor.execute(
        {"messages": [{"role": "user", "content": "hi"}], "tools": tools},
        event_stream=None,
    )

    assert result.actions
    assert isinstance(result.actions[0], PlaybookFinishAction)

    # Ensure native tool payloads were stripped for the provider call.
    assert llm.last_kwargs is not None
    assert "tools" not in llm.last_kwargs
    assert "tool_choice" not in llm.last_kwargs
    assert "stop" in llm.last_kwargs
