"""Tests for the one-off legacy storage cleanup command."""

from __future__ import annotations

from pathlib import Path

from backend.cli.storage_cleanup import cleanup_project_storage


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def test_cleanup_project_storage_moves_legacy_roots(tmp_path: Path) -> None:
    _write_file(tmp_path / 'sessions' / 'sess-a' / 'metadata.json', 'session-a')
    _write_file(
        tmp_path / 'users' / 'u1' / 'conversations' / 'sess-b' / 'metadata.json',
        'session-b',
    )
    _write_file(tmp_path / '.grinta' / 'conversations' / 'sess-c' / 'metadata.json', 'session-c')
    _write_file(
        tmp_path / '.grinta' / 'conversations' / 'oss_user' / 'sess-d' / 'metadata.json',
        'session-d',
    )

    report = cleanup_project_storage(tmp_path)

    canonical_root = tmp_path / '.grinta' / 'storage'
    assert (canonical_root / 'sessions' / 'sess-a' / 'metadata.json').read_text(encoding='utf-8') == 'session-a'
    assert (canonical_root / 'sessions' / 'sess-c' / 'metadata.json').read_text(encoding='utf-8') == 'session-c'
    assert (
        canonical_root / 'users' / 'u1' / 'conversations' / 'sess-b' / 'metadata.json'
    ).read_text(encoding='utf-8') == 'session-b'
    assert (
        canonical_root / 'users' / 'oss_user' / 'conversations' / 'sess-d' / 'metadata.json'
    ).read_text(encoding='utf-8') == 'session-d'
    assert not (tmp_path / 'sessions').exists()
    assert not (tmp_path / 'users').exists()
    assert not (tmp_path / '.grinta' / 'conversations').exists()
    assert report.migrated_entries >= 4


def test_cleanup_project_storage_archives_conflicts(tmp_path: Path) -> None:
    canonical_file = tmp_path / '.grinta' / 'storage' / 'sessions' / 'sess-a' / 'metadata.json'
    _write_file(canonical_file, 'canonical')
    _write_file(tmp_path / 'sessions' / 'sess-a' / 'metadata.json', 'legacy')

    report = cleanup_project_storage(tmp_path)

    assert canonical_file.read_text(encoding='utf-8') == 'canonical'
    archived = report.conflict_root / 'content-conflict' / 'sessions' / 'sess-a' / 'metadata.json'
    assert archived.read_text(encoding='utf-8') == 'legacy'
    assert report.archived_conflicts == 1


def test_cleanup_project_storage_removes_duplicate_files(tmp_path: Path) -> None:
    canonical_file = tmp_path / '.grinta' / 'storage' / 'sessions' / 'sess-a' / 'metadata.json'
    _write_file(canonical_file, 'same')
    _write_file(tmp_path / 'sessions' / 'sess-a' / 'metadata.json', 'same')

    report = cleanup_project_storage(tmp_path)

    assert canonical_file.read_text(encoding='utf-8') == 'same'
    assert not (tmp_path / 'sessions').exists()
    assert report.removed_duplicates == 1


def test_cleanup_project_storage_moves_legacy_storage_grinta_state(tmp_path: Path) -> None:
    _write_file(
        tmp_path / 'storage' / '.grinta' / 'conversations' / 'sess-z' / 'metadata.json',
        'session-z',
    )
    _write_file(tmp_path / 'storage' / '.grinta' / 'agent_notes.json', 'notes')
    _write_file(tmp_path / 'storage' / '.grinta' / 'blackboard.json', '{"k": "v"}')
    _write_file(
        tmp_path / 'storage' / '.grinta' / 'checkpoints' / 'manifest.json',
        '{}',
    )
    _write_file(tmp_path / 'storage' / '.jwt_secret', 'secret')

    report = cleanup_project_storage(tmp_path)

    canonical_root = tmp_path / '.grinta' / 'storage'
    assert (canonical_root / 'sessions' / 'sess-z' / 'metadata.json').read_text(encoding='utf-8') == 'session-z'
    assert (canonical_root / '.jwt_secret').read_text(encoding='utf-8') == 'secret'
    assert (tmp_path / '.grinta' / 'agent_notes.json').read_text(encoding='utf-8') == 'notes'
    assert (tmp_path / '.grinta' / 'blackboard.json').read_text(encoding='utf-8') == '{"k": "v"}'
    assert (
        tmp_path / '.grinta' / 'checkpoints' / 'manifest.json'
    ).read_text(encoding='utf-8') == '{}'
    assert not (tmp_path / 'storage').exists()
    assert report.migrated_entries >= 5