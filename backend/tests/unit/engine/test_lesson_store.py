from __future__ import annotations

from backend.engine.tools.lesson_store import (
    append_markdown_lesson,
    lessons_are_similar,
)


def test_lessons_are_similar_does_not_merge_short_distinct_entries() -> None:
    assert lessons_are_similar('lesson 0', 'lesson 1') is False
    assert lessons_are_similar('PowerShell input stalled', 'PowerShell input stalled')


def test_append_markdown_lesson_skips_duplicate_sections(tmp_path) -> None:
    lessons_path = tmp_path / 'state' / 'lessons.md'
    lesson = (
        'PowerShell terminal input raced the PTY flush, so terminal_manager input '
        'must poll for output after every submitted command.'
    )

    first = append_markdown_lesson(
        lessons_path,
        lesson,
        summary='Terminal run',
        timestamp='2026-06-02 03:00',
    )
    second = append_markdown_lesson(
        lessons_path,
        lesson,
        summary='Terminal rerun',
        timestamp='2026-06-02 03:01',
    )

    assert first is True
    assert second is False
    stored = lessons_path.read_text(encoding='utf-8')
    assert stored.count('## ') == 1
    assert 'Terminal run' in stored
    assert 'Terminal rerun' not in stored
