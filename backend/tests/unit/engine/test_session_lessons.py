"""Tests for finish-time lesson persistence."""

from __future__ import annotations

from backend.engine.tools.session_lessons import persist_finish_lessons


def test_persist_finish_lessons_writes_workspace_store_and_markdown(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.core.workspace_resolution.get_effective_workspace_root',
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    monkeypatch.setattr(
        'backend.engine.tools.workspace_memory._memory_path',
        lambda: tmp_path / 'workspace_memory.json',
    )
    monkeypatch.setattr(
        'backend.engine.tools.working_memory._memory_path',
        lambda: tmp_path / 'working_memory.json',
    )

    persist_finish_lessons(summary='Implemented unified memory tool.')

    lessons = (tmp_path / 'lessons.md').read_text(encoding='utf-8')
    assert 'unified memory tool' in lessons
    store = (tmp_path / 'workspace_memory.json').read_text(encoding='utf-8')
    assert 'session_summary' in store
