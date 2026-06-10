"""Tests for unified memory tool dispatch."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.core.errors import FunctionCallValidationError
from backend.engine.tools._tool_handlers import (
    _handle_memory_tool,
    execute_memory_persist,
    execute_memory_recall,
)
from backend.ledger.action.memory_tools import (
    MemoryPersistAction,
    MemoryRecallAction,
    WorkingMemoryAction,
)
from backend.engine.tools.working_memory import execute_working_memory


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


def test_memory_recall_without_vector_store() -> None:
    action = _handle_memory_tool({'action': 'recall', 'key': 'auth decision'})
    assert isinstance(action, MemoryRecallAction)
    obs = execute_memory_recall(action)
    assert 'not available' in obs.content.lower()


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
