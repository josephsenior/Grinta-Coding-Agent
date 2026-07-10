"""Tests for post-session memory reflection and candidate extraction."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.engine.tools.session_lessons import (
    persist_finish_lessons,
    detect_reflection_signals,
    format_history_for_reflection,
)
from backend.context.memory.project_memory import ProjectMemoryService


class MessageAction:
    def __init__(self, source: str, content: str):
        self.source = source
        self.content = content


class FileEditAction:
    def __init__(self, path: str):
        self.path = path
        self.source = "agent"


class TerminalRunObservation:
    def __init__(self, exit_code: int, content: str):
        self.exit_code = exit_code
        self.content = content
        self.source = "environment"


@pytest.mark.asyncio
async def test_persist_finish_lessons_no_signals(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'backend.context.memory.project_memory.ProjectMemoryService._memory_file_path',
        lambda self: tmp_path / 'project_memory.md'
    )
    
    state = MagicMock()
    state.plan = None
    state.history = [
        MessageAction(source="user", content="hello"),
    ]
    
    controller = MagicMock()
    
    # Run: no signals -> should return immediately without triggering LLM
    await persist_finish_lessons(summary="Done", session_id="sess-123", state=state, controller=controller)
    assert not (tmp_path / 'project_memory.md').is_file()


@pytest.mark.asyncio
async def test_persist_finish_lessons_with_signals_and_reflection(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'backend.context.memory.project_memory.ProjectMemoryService._memory_file_path',
        lambda self: tmp_path / 'project_memory.md'
    )
    
    state = MagicMock()
    state.plan = None
    # Signal: mutation (FileEditAction) and command run
    state.history = [
        FileEditAction(path="app.py"),
        TerminalRunObservation(exit_code=0, content="test output"),
    ]
    
    # Mock LLM completion response
    mock_response = MagicMock()
    mock_response.content = json.dumps({
        "candidates": [
            {
                "kind": "command",
                "fact": "Run integration tests with uv run pytest.",
                "evidence": ["pytest passed"],
                "confidence": 0.95,
                "superseded_ids": []
            }
        ]
    })
    
    llm = AsyncMock()
    llm.completion.return_value = mock_response
    
    controller = MagicMock()
    controller.agent.llm = llm
    
    await persist_finish_lessons(summary="Done task", session_id="sess-123", state=state, controller=controller)
    
    # Verify ProjectMemoryService wrote the file
    service = ProjectMemoryService(workspace_root=tmp_path)
    entries = service.load()
    assert len(entries) == 1
    assert entries[0].fact == "Run integration tests with uv run pytest."
