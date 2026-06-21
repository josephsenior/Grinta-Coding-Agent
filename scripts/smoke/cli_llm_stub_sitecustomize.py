"""Deterministic LLM stub injected via PYTHONPATH sitecustomize for smoke tests.

Patches ``LLM.completion`` / ``LLM.astream`` to return a read tool call on the
first turn and a final message on the second, exercising the real controller
path without live API calls.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import backend.inference.llm as llm_module

_CALL_COUNT = 0
_COMPLETION_TEXT = (
    'Task complete: summarized README.md for the CLI regression.'
)


def _make_tool_response(tool_name: str, arguments: dict[str, object]) -> SimpleNamespace:
    tool_call = SimpleNamespace(
        id='call_stub',
        function=SimpleNamespace(
            name=tool_name,
            arguments=json.dumps(arguments),
        ),
    )
    message = SimpleNamespace(content='', tool_calls=[tool_call])
    choice = SimpleNamespace(message=message, finish_reason='tool_calls')
    return SimpleNamespace(choices=[choice], model='stub-model')


def _make_message_response(text: str) -> SimpleNamespace:
    message = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason='stop')
    return SimpleNamespace(choices=[choice], model='stub-model')


def _next_stub_response() -> SimpleNamespace:
    global _CALL_COUNT
    _CALL_COUNT += 1
    if _CALL_COUNT == 1:
        return _make_tool_response(
            'read',
            {'path': 'README.md', 'security_risk': 'none'},
        )
    return _make_message_response(_COMPLETION_TEXT)


def _stub_completion(self, *args, **kwargs):  # noqa: ANN001, ARG001
    return _next_stub_response()


async def _stub_astream(self, *args, **kwargs):  # noqa: ANN001, ARG001
    response = _next_stub_response()
    yield response


llm_module.LLM.completion = _stub_completion  # type: ignore[method-assign]
llm_module.LLM.astream = _stub_astream  # type: ignore[method-assign]
