"""Deterministic LLM stub for smoke tests and CI.

Patches ``LLM.completion`` / ``LLM.astream`` to return a ``read`` tool call on
the first turn and a final assistant message on the second, exercising the real
controller path without live API calls.
"""

from __future__ import annotations

import json
from typing import Any

import backend.inference.llm as llm_module

_CALL_COUNT = 0
_COMPLETION_TEXT = 'Task complete: summarized README.md for the CLI regression.'
_READ_ARGS = {'type': 'file', 'path': 'README.md', 'security_risk': 'LOW'}


def _tool_call_chunks(
    tool_name: str, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    args_json = json.dumps(arguments)
    return [
        {
            'id': 'chatcmpl-stub',
            'model': 'stub-model',
            'choices': [
                {
                    'delta': {
                        'tool_calls': [
                            {
                                'index': 0,
                                'id': 'call_stub',
                                'function': {
                                    'name': tool_name,
                                    'arguments': args_json,
                                },
                            }
                        ]
                    }
                }
            ],
        },
        {
            'id': 'chatcmpl-stub',
            'model': 'stub-model',
            'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}],
        },
    ]


def _message_chunks(text: str) -> list[dict[str, Any]]:
    return [
        {
            'id': 'chatcmpl-stub',
            'model': 'stub-model',
            'choices': [{'delta': {'content': text}}],
        },
        {
            'id': 'chatcmpl-stub',
            'model': 'stub-model',
            'choices': [{'delta': {}, 'finish_reason': 'stop'}],
        },
    ]


def _next_stream_chunks() -> list[dict[str, Any]]:
    global _CALL_COUNT
    _CALL_COUNT += 1
    if _CALL_COUNT == 1:
        return _tool_call_chunks('read', _READ_ARGS)
    return _message_chunks(_COMPLETION_TEXT)


def _make_tool_response(tool_name: str, arguments: dict[str, Any]) -> Any:
    from types import SimpleNamespace

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


def _make_message_response(text: str) -> Any:
    from types import SimpleNamespace

    message = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason='stop')
    return SimpleNamespace(choices=[choice], model='stub-model')


def _stub_completion(self, *args, **kwargs):  # noqa: ANN001, ARG001
    global _CALL_COUNT
    _CALL_COUNT += 1
    if _CALL_COUNT == 1:
        return _make_tool_response('read', _READ_ARGS)
    return _make_message_response(_COMPLETION_TEXT)


async def _stub_astream(self, *args, **kwargs):  # noqa: ANN001, ARG001
    for chunk in _next_stream_chunks():
        yield chunk


llm_module.LLM.completion = _stub_completion  # type: ignore[method-assign]
llm_module.LLM.astream = _stub_astream  # type: ignore[method-assign]
