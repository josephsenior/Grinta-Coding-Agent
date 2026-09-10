"""Compatibility tests for recorded Ollama and LM Studio responses."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openai.types.chat import ChatCompletion

from backend.engine.planner import OrchestratorPlanner
from backend.inference.providers.openai_ops import (
    _build_llm_response,
    extract_openai_tool_calls,
)

FIXTURE_DIR = Path(__file__).parents[2] / 'fixtures' / 'local_models'


def _load_fixture(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding='utf-8'))


def _parse_completion(name: str):
    response = ChatCompletion.model_validate(_load_fixture(name))
    client = SimpleNamespace(_extract_openai_tool_calls=extract_openai_tool_calls)
    return _build_llm_response(response, client)


@pytest.mark.parametrize(
    ('fixture_name', 'finish_reason', 'has_tool_calls'),
    [
        ('ollama_llama3_no_tools.json', 'stop', False),
        ('ollama_codellama_truncated.json', 'length', False),
        ('ollama_mistral_tool_call.json', 'tool_calls', True),
    ],
)
def test_ollama_openai_compatible_responses(
    fixture_name: str,
    finish_reason: str,
    has_tool_calls: bool,
) -> None:
    response = _parse_completion(fixture_name)

    assert response.finish_reason == finish_reason
    assert bool(response.tool_calls) is has_tool_calls
    assert response.usage['total_tokens'] > 0


def test_explicitly_disabled_native_tools_use_text_fallback() -> None:
    fixture = _load_fixture('ollama_llama3_no_tools.json')
    llm = SimpleNamespace(
        config=SimpleNamespace(
            model=f'ollama/{fixture["model"]}',
            native_tool_calling=False,
        )
    )
    planner = OrchestratorPlanner(
        config=SimpleNamespace(),
        llm=llm,
        safety_manager=MagicMock(),
    )
    tools = [
        {
            'type': 'function',
            'function': {
                'name': 'read_file',
                'description': 'Read a file',
                'parameters': {'type': 'object', 'properties': {}},
            },
        }
    ]
    params = planner._configure_tool_routing(
        {'messages': [{'role': 'system', 'content': 'You are helpful.'}]},
        tools,
        [{'role': 'system', 'content': 'You are helpful.'}],
        'auto',
    )

    assert 'tools' not in params
    assert '<TOOL_CALL_FORMAT>' in params['messages'][0]['content']


def test_lm_studio_stream_preserves_terminal_finish_reason(monkeypatch) -> None:
    import backend.engine.function_calling.dispatch as function_calling
    from backend.engine import executor as executor_module
    from backend.engine.executor import OrchestratorExecutor

    sys.modules.setdefault('app.engine.function_calling', function_calling)
    monkeypatch.setattr(
        executor_module.orchestrator_function_calling,
        'response_to_actions',
        lambda *_args, **_kwargs: [],
    )
    chunks = _load_fixture('lm_studio_mistral_stream.json')

    async def fake_astream(**_kwargs):
        for chunk in chunks:
            yield chunk

    llm = MagicMock()
    llm.astream = fake_astream
    llm.model = chunks[0]['model']
    llm.config.model = f'lm_studio/{chunks[0]["model"]}'
    safety_manager = MagicMock()
    safety_manager.apply.side_effect = lambda _content, actions: (True, actions)
    executor = OrchestratorExecutor(
        llm=llm,
        safety_manager=safety_manager,
        planner=MagicMock(),
        mcp_tools_provider=lambda: {},
    )

    result = asyncio.run(executor.async_execute({'messages': []}, None))

    assert result.response.content == 'The answer is truncated'
    assert result.response.finish_reason == 'length'
    assert result.response.usage['total_tokens'] == 19
