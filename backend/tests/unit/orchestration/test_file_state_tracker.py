from __future__ import annotations

import os

from backend.orchestration.file_state_tracker import _MANIFEST_PATH, FileStateTracker


def test_manifest_path_uses_app_dir() -> None:
    assert _MANIFEST_PATH == os.path.join('.grinta', 'file_manifest.json')


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
