"""Tests for unified memory tool dispatch."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.core.errors import FunctionCallValidationError
from backend.engine.tools._tool_handlers import _handle_memory_tool


def test_memory_working_get_empty() -> None:
    with patch(
        'backend.engine.tools.working_memory._load_memory',
        return_value={},
    ):
        action = _handle_memory_tool({'action': 'working', 'update_type': 'get'})
    assert 'empty' in action.thought.lower()


def test_memory_persist_requires_key_and_value() -> None:
    with pytest.raises(FunctionCallValidationError, match='key'):
        _handle_memory_tool({'action': 'persist', 'value': 'x'})
    with pytest.raises(FunctionCallValidationError, match='value'):
        _handle_memory_tool({'action': 'persist', 'key': 'k'})


def test_memory_recall_without_vector_store() -> None:
    action = _handle_memory_tool({'action': 'recall', 'key': 'auth decision'})
    assert 'not available' in action.thought.lower()
