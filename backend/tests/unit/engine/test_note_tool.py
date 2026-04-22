"""Tests for scratchpad note/recall behavior."""

from __future__ import annotations

import json

from backend.engine.tools import note as note_tools


def test_recall_lessons_empty_returns_clear_message_without_write(
    monkeypatch, tmp_path
):
    """Recalling 'lessons' before any have been stored must NOT bootstrap-write
    an empty key. The previous behavior masked the true empty state and made
    `recall` look like a side-effectful tool. finish() now owns lessons
    persistence via append_to_note, so recall must stay read-only.
    """
    notes_path = tmp_path / 'agent_notes.json'
    monkeypatch.setattr(note_tools, '_notes_path', lambda: notes_path)

    thought = note_tools.build_recall_action('lessons').thought

    assert 'No lessons stored yet' in thought
    assert not notes_path.exists()


def test_recall_missing_non_lessons_key_returns_not_found(monkeypatch, tmp_path):
    notes_path = tmp_path / 'agent_notes.json'
    monkeypatch.setattr(note_tools, '_notes_path', lambda: notes_path)

    thought = note_tools.build_recall_action('does_not_exist').thought

    assert "Note 'does_not_exist' not found" in thought
    assert not notes_path.exists()


def test_append_to_note_accumulates_with_timestamps(monkeypatch, tmp_path):
    """append_to_note should accumulate dated entries under a single key so
    finish(lessons_learned=...) across multiple sessions produces a running log
    rather than overwriting the previous session's lesson.
    """
    notes_path = tmp_path / 'agent_notes.json'
    monkeypatch.setattr(note_tools, '_notes_path', lambda: notes_path)

    note_tools.append_to_note('lessons', 'First session lesson')
    note_tools.append_to_note('lessons', 'Second session lesson')

    payload = json.loads(notes_path.read_text(encoding='utf-8'))
    stored = payload['lessons']
    assert 'First session lesson' in stored
    assert 'Second session lesson' in stored
    # Entries are newline-separated so the log reads as a bulleted history.
    assert stored.count('\n') == 1


def test_append_to_note_ignores_empty_values(monkeypatch, tmp_path):
    notes_path = tmp_path / 'agent_notes.json'
    monkeypatch.setattr(note_tools, '_notes_path', lambda: notes_path)

    note_tools.append_to_note('lessons', '')
    note_tools.append_to_note('lessons', '   ')

    assert not notes_path.exists()


def test_append_to_note_caps_entry_count(monkeypatch, tmp_path):
    notes_path = tmp_path / 'agent_notes.json'
    monkeypatch.setattr(note_tools, '_notes_path', lambda: notes_path)

    for i in range(5):
        note_tools.append_to_note('lessons', f'lesson {i}', max_entries=3)

    payload = json.loads(notes_path.read_text(encoding='utf-8'))
    lines = payload['lessons'].splitlines()
    assert len(lines) == 3
    # Only the most recent entries are retained.
    assert 'lesson 2' in lines[0]
    assert 'lesson 4' in lines[-1]
