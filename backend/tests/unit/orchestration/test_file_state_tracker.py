from __future__ import annotations

import os

import pytest

from backend.orchestration.file_state_tracker import (
    FileStateTracker,
    _normalize_path_key,
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


def test_read_snapshot_stale_after_disk_change(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    f = tmp_path / 'stale.txt'
    f.write_text('version-one\n', encoding='utf-8')
    tracker = FileStateTracker()
    tracker.record_read_snapshot_from_disk('stale.txt')
    f.write_text('version-two\n', encoding='utf-8')
    msg = tracker.check_read_stale('stale.txt')
    assert msg is not None
    assert 'changed on disk' in (msg or '')


def test_read_snapshot_not_stale_when_content_matches(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mtime can move without content change; hash match allows edit (Claude-style)."""
    monkeypatch.chdir(tmp_path)
    f = tmp_path / 'same.txt'
    body = b'stable-bytes'
    f.write_bytes(body)
    tracker = FileStateTracker()
    tracker.record_read_snapshot_from_disk('same.txt')
    snap = tracker._read_snapshots.get(_normalize_path_key('same.txt') or '')
    assert snap is not None
    os.utime(f, (snap.mtime + 10, snap.mtime + 10))
    assert tracker.check_read_stale('same.txt') is None


def test_invalidate_read_snapshot(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    f = tmp_path / 'x.txt'
    f.write_text('a', encoding='utf-8')
    tracker = FileStateTracker()
    tracker.record_read_snapshot_from_disk('x.txt')
    assert _normalize_path_key('x.txt') in tracker._read_snapshots
    tracker.invalidate_read_snapshot('x.txt')
    assert _normalize_path_key('x.txt') not in tracker._read_snapshots
