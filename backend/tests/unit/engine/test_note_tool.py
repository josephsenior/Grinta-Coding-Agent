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

    action = note_tools.build_recall_action('lessons')
    obs = note_tools.execute_scratchpad_recall(action)

    assert 'No lessons stored yet' in obs.content
    assert not notes_path.exists()


def test_recall_missing_non_lessons_key_returns_not_found(monkeypatch, tmp_path):
    notes_path = tmp_path / 'agent_notes.json'
    monkeypatch.setattr(note_tools, '_notes_path', lambda: notes_path)

    action = note_tools.build_recall_action('does_not_exist')
    obs = note_tools.execute_scratchpad_recall(action)

    assert "Note 'does_not_exist' not found" in obs.content
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


def test_build_note_action_persists_via_execute(monkeypatch, tmp_path):
    notes_path = tmp_path / 'agent_notes.json'
    monkeypatch.setattr(note_tools, '_notes_path', lambda: notes_path)

    action = note_tools.build_note_action('auth_decision', 'use JWT')
    obs = note_tools.execute_scratchpad_note(action)

    assert 'Noted [auth_decision]' in obs.content
    payload = json.loads(notes_path.read_text(encoding='utf-8'))
    assert payload['auth_decision'] == 'use JWT'
