"""Tests for scratchpad note/recall behavior."""

from __future__ import annotations

import json

from backend.engine.tools import note as note_tools


def test_recall_lessons_bootstraps_empty_note(monkeypatch, tmp_path):
    notes_path = tmp_path / 'agent_notes.json'
    monkeypatch.setattr(note_tools, '_notes_path', lambda: notes_path)

    thought = note_tools.build_recall_action('lessons').thought

    assert "Initialized ['lessons'] as empty" in thought
    payload = json.loads(notes_path.read_text(encoding='utf-8'))
    assert payload['lessons'] == ''
    assert note_tools._SCRATCHPAD_META_KEY in payload


def test_recall_missing_non_lessons_key_returns_not_found(monkeypatch, tmp_path):
    notes_path = tmp_path / 'agent_notes.json'
    monkeypatch.setattr(note_tools, '_notes_path', lambda: notes_path)

    thought = note_tools.build_recall_action('does_not_exist').thought

    assert "Note 'does_not_exist' not found" in thought
    assert not notes_path.exists()
