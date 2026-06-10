"""Tests for workspace-scoped durable memory."""

from __future__ import annotations

from backend.engine.tools.workspace_memory import (
    format_prompt_block,
    memory_query_from_text,
    persist_entry,
    rank_entries,
)


def test_persist_entry_dedupes_similar_values(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.engine.tools.workspace_memory._memory_path',
        lambda: tmp_path / 'workspace_memory.json',
    )
    inserted, _ = persist_entry(
        kind='command',
        key='test_cmd',
        value='uv run pytest backend/tests',
    )
    assert inserted is True
    inserted_again, message = persist_entry(
        kind='command',
        key='test_cmd',
        value='uv run pytest backend/tests',
    )
    assert inserted_again is False
    assert 'Updated existing' in message
    assert len(rank_entries()) == 1


def test_rank_entries_prefers_query_overlap(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.engine.tools.workspace_memory._memory_path',
        lambda: tmp_path / 'workspace_memory.json',
    )
    persist_entry(kind='command', key='pytest_cmd', value='uv run pytest backend/tests')
    persist_entry(kind='lesson', key='auth_note', value='JWT tokens expire after one hour')

    ranked = rank_entries('run pytest tests', max_entries=2)
    assert ranked[0]['key'] == 'pytest_cmd'


def test_memory_query_from_text_truncates_long_input() -> None:
    query = memory_query_from_text('x' * 800, max_chars=500)
    assert query is not None
    assert len(query) == 500


def test_format_prompt_block_respects_char_budget(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.engine.tools.workspace_memory._memory_path',
        lambda: tmp_path / 'workspace_memory.json',
    )
    for i in range(5):
        persist_entry(kind='lesson', key=f'key_{i}', value=f'lesson body {i}' * 20)

    block = format_prompt_block(char_budget=300)
    assert block.startswith('<WORKSPACE_MEMORY>')
    assert len(block) <= 320
    assert 'truncated' in block
