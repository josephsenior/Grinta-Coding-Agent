"""Tests for unified memory tool dispatch."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.core.errors import FunctionCallValidationError
from backend.engine.tools._tool_handlers import (
    _handle_memory_tool,
    _semantic_recall_registry,
    execute_memory_persist,
    execute_memory_recall,
)
from backend.engine.tools.working_memory import execute_working_memory
from backend.ledger.action.memory_tools import (
    MemoryPersistAction,
    MemoryRecallAction,
    WorkingMemoryAction,
)


def test_memory_working_get_empty() -> None:
    with patch(
        'backend.engine.tools.working_memory._load_memory',
        return_value={},
    ):
        action = _handle_memory_tool({'action': 'working', 'update_type': 'get'})
        assert isinstance(action, WorkingMemoryAction)
        obs = execute_working_memory(action)
    assert 'empty' in obs.content.lower()


def test_memory_persist_requires_key_and_value() -> None:
    with pytest.raises(FunctionCallValidationError, match='key'):
        _handle_memory_tool({'action': 'persist', 'value': 'x'})
    with pytest.raises(FunctionCallValidationError, match='value'):
        _handle_memory_tool({'action': 'persist', 'key': 'k'})


def test_create_memory_tool_omits_recall_when_disabled() -> None:
    from backend.engine.tools.memory import create_memory_tool

    tool = create_memory_tool(include_semantic_recall=False)
    props = tool['function']['parameters']['properties']
    assert 'recall' not in props['action']['enum']
    assert 'recall' not in tool['function']['description'].lower()


def test_memory_recall_rejected_when_semantic_recall_unregistered() -> None:
    with patch.dict(_semantic_recall_registry, {}, clear=True):
        with pytest.raises(FunctionCallValidationError, match='not available'):
            _handle_memory_tool({'action': 'recall', 'key': 'auth decision'})


def test_memory_recall_formats_vector_excerpts() -> None:
    action = MemoryRecallAction(query='auth decision')

    def recall(_query: str, _k: int):
        return [
            {
                'excerpt': 'Use the token refresh path before retrying auth.',
                'role': 'assistant',
                'score': 0.91,
            }
        ]

    with patch.dict(_semantic_recall_registry, {'fn': recall}, clear=True):
        obs = execute_memory_recall(action)

    assert 'Use the token refresh path' in obs.content
    assert '(assistant (score=0.910))' in obs.content
    assert obs.hits[0]['excerpt'].startswith('Use the token refresh path')


def test_memory_persist_execute() -> None:
    with patch(
        'backend.engine.tools.workspace_memory.persist_entry',
        return_value=(True, 'stored lesson'),
    ):
        obs = execute_memory_persist(
            MemoryPersistAction(key='k', value='v', kind='lesson')
        )
    assert obs.content == 'stored lesson'
    assert obs.inserted is True
