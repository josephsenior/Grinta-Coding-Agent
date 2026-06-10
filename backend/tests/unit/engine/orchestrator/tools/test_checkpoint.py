"""Unit tests for backend.engine.tools.checkpoint."""

from __future__ import annotations

import json
from pathlib import Path

from backend.engine.tools import checkpoint


def test_save_checkpoint_success_and_structured_payload(
    monkeypatch, tmp_path: Path
) -> None:
    cp_file = tmp_path / 'checkpoints.json'
    monkeypatch.setattr(checkpoint, '_checkpoints_path', lambda: cp_file)

    action = checkpoint.build_checkpoint_action(
        {'command': 'save', 'label': 'phase 1', 'files_modified': 'a.txt,b.txt'}
    )
    obs = checkpoint.execute_checkpoint(action)

    assert 'Saved #1: phase 1' in obs.content
    assert obs.ok is True
    assert obs.status == 'saved'
    assert obs.reason_code == 'CHECKPOINT_SAVED'
    assert obs.changed_state is True
    assert obs.data['checkpoint_id'] == 1
    assert obs.data['files'] == ['a.txt', 'b.txt']


def test_save_checkpoint_duplicate_is_noop(monkeypatch, tmp_path: Path) -> None:
    cp_file = tmp_path / 'checkpoints.json'
    monkeypatch.setattr(checkpoint, '_checkpoints_path', lambda: cp_file)

    first_action = checkpoint.build_checkpoint_action(
        {'command': 'save', 'label': 'same', 'files_modified': 'x.py'}
    )
    second_action = checkpoint.build_checkpoint_action(
        {'command': 'save', 'label': 'same', 'files_modified': 'x.py'}
    )

    first = checkpoint.execute_checkpoint(first_action)
    second = checkpoint.execute_checkpoint(second_action)

    assert first.status == 'saved'
    assert second.ok is True
    assert second.status == 'noop'
    assert second.reason_code == 'DUPLICATE_CHECKPOINT'
    assert second.changed_state is False

    checkpoints = json.loads(cp_file.read_text(encoding='utf-8'))
    assert len(checkpoints) == 1


def test_save_checkpoint_missing_label_returns_failed_payload() -> None:
    action = checkpoint.build_checkpoint_action({'command': 'save'})
    obs = checkpoint.execute_checkpoint(action)

    assert obs.ok is False
    assert obs.status == 'failed'
    assert obs.reason_code == 'MISSING_LABEL'
    assert obs.retryable is True


def test_clear_when_empty_returns_noop(monkeypatch, tmp_path: Path) -> None:
    cp_file = tmp_path / 'checkpoints.json'
    monkeypatch.setattr(checkpoint, '_checkpoints_path', lambda: cp_file)

    action = checkpoint.build_checkpoint_action({'command': 'clear'})
    obs = checkpoint.execute_checkpoint(action)

    assert obs.ok is True
    assert obs.status == 'noop'
    assert obs.reason_code == 'ALREADY_EMPTY'
    assert obs.changed_state is False
