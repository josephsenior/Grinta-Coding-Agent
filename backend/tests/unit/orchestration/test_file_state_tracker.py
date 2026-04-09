from __future__ import annotations

import pytest

from backend.orchestration.file_state_tracker import (
    FileStateTracker,
    file_manifest_path,
)


def test_manifest_path_uses_agent_state_dir(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    assert file_manifest_path() == tmp_path / 'file_manifest.json'


def test_record_keeps_highest_priority_action() -> None:
    tracker = FileStateTracker()

    tracker.record('src/app.py', 'read')
    tracker.record('src/app.py', 'modified')
    tracker.record('src/app.py', 'read')

    assert tracker.to_dict()['src/app.py']['action'] == 'modified'


def test_load_from_dict_restores_entries() -> None:
    tracker = FileStateTracker()
    tracker.load_from_dict({'src/app.py': {'action': 'created', 'timestamp': 123.0}})

    summary = tracker.get_summary()
    assert 'created: src/app.py' in summary
