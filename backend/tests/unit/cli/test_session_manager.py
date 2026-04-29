"""Tests for backend.cli.session_manager."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from rich.console import Console

from backend.cli.session_manager import (
    _count_events,
    _list_session_entries,
    _load_metadata,
    _resolve_session_by_id_or_prefix,
    _resolve_session_index,
    get_session_id_by_index,
    get_session_suggestions,
    list_sessions,
    resolve_session_id,
)


def _quiet_console() -> Console:
    return Console(quiet=True)


def _make_session_dir(root: Path, sid: str, meta: dict[str, Any], event_count: int = 0) -> Path:
    """Create a fake session directory with metadata and optional events."""
    session_dir = root / sid
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / 'metadata.json').write_text(
        json.dumps(meta), encoding='utf-8'
    )
    if event_count > 0:
        events_dir = session_dir / 'events'
        events_dir.mkdir()
        for i in range(event_count):
            (events_dir / f'event_{i:04d}.json').write_text('{}', encoding='utf-8')
    return session_dir


# ---------------------------------------------------------------------------
# _load_metadata
# ---------------------------------------------------------------------------

class TestLoadMetadata:
    def test_returns_metadata(self, tmp_path: Path) -> None:
        session_dir = tmp_path / 'sess1'
        session_dir.mkdir()
        (session_dir / 'metadata.json').write_text(
            json.dumps({'title': 'Test Session'}), encoding='utf-8'
        )
        meta = _load_metadata(session_dir)
        assert meta is not None
        assert meta['title'] == 'Test Session'

    def test_no_file_returns_none(self, tmp_path: Path) -> None:
        session_dir = tmp_path / 'sess1'
        session_dir.mkdir()
        assert _load_metadata(session_dir) is None

    def test_invalid_json_returns_none(self, tmp_path: Path) -> None:
        session_dir = tmp_path / 'sess1'
        session_dir.mkdir()
        (session_dir / 'metadata.json').write_text('{bad', encoding='utf-8')
        assert _load_metadata(session_dir) is None


# ---------------------------------------------------------------------------
# _count_events
# ---------------------------------------------------------------------------

class TestCountEvents:
    def test_no_events_dir(self, tmp_path: Path) -> None:
        session_dir = tmp_path / 'sess'
        session_dir.mkdir()
        assert _count_events(session_dir) == 0

    def test_events_counted(self, tmp_path: Path) -> None:
        session_dir = tmp_path / 'sess'
        events_dir = session_dir / 'events'
        events_dir.mkdir(parents=True)
        for i in range(5):
            (events_dir / f'ev{i}.json').write_text('{}', encoding='utf-8')
        # Add a non-json file that should not be counted
        (events_dir / 'other.txt').write_text('x', encoding='utf-8')
        assert _count_events(session_dir) == 5

    def test_empty_events_dir(self, tmp_path: Path) -> None:
        session_dir = tmp_path / 'sess'
        (session_dir / 'events').mkdir(parents=True)
        assert _count_events(session_dir) == 0


# ---------------------------------------------------------------------------
# _list_session_entries
# ---------------------------------------------------------------------------

class TestListSessionEntries:
    def test_sorted_by_last_updated(self, tmp_path: Path) -> None:
        _make_session_dir(tmp_path, 'old-session', {'last_updated_at': '2020-01-01T00:00:00'})
        _make_session_dir(tmp_path, 'new-session', {'last_updated_at': '2024-01-01T00:00:00'})
        entries = _list_session_entries(tmp_path)
        assert entries[0][0] == 'new-session'
        assert entries[1][0] == 'old-session'

    def test_skips_files(self, tmp_path: Path) -> None:
        _make_session_dir(tmp_path, 'sess1', {})
        (tmp_path / 'not_a_dir.txt').write_text('x', encoding='utf-8')
        entries = _list_session_entries(tmp_path)
        sids = [e[0] for e in entries]
        assert 'sess1' in sids
        assert 'not_a_dir.txt' not in sids

    def test_no_metadata_uses_empty_dict(self, tmp_path: Path) -> None:
        (tmp_path / 'bare-sess').mkdir()
        entries = _list_session_entries(tmp_path)
        assert len(entries) == 1
        assert entries[0][1] == {}

    def test_event_count_included(self, tmp_path: Path) -> None:
        _make_session_dir(tmp_path, 'sess-with-events', {}, event_count=3)
        entries = _list_session_entries(tmp_path)
        assert entries[0][2] == 3


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------

class TestListSessions:
    def test_no_storage_found(self) -> None:
        console = _quiet_console()
        with patch('backend.cli.session_manager._find_sessions_root', return_value=None):
            list_sessions(console)  # Should not raise

    def test_no_sessions(self, tmp_path: Path) -> None:
        console = _quiet_console()
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            list_sessions(console)  # Empty dir — should not raise

    def test_with_sessions(self, tmp_path: Path) -> None:
        _make_session_dir(tmp_path, 'sess-abc', {'title': 'Test', 'llm_model': 'openai/gpt-4o', 'accumulated_cost': 0.01, 'last_updated_at': '2024-01-01T12:00:00'}, event_count=2)
        console = _quiet_console()
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            list_sessions(console, limit=5)  # Should not raise

    def test_limit_applied(self, tmp_path: Path) -> None:
        for i in range(5):
            _make_session_dir(tmp_path, f'sess-{i:04d}', {'last_updated_at': f'2024-01-0{i+1}T00:00:00'})
        console = _quiet_console()
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            list_sessions(console, limit=2)  # Should not raise


# ---------------------------------------------------------------------------
# get_session_id_by_index
# ---------------------------------------------------------------------------

class TestGetSessionIdByIndex:
    def test_valid_index(self, tmp_path: Path) -> None:
        _make_session_dir(tmp_path, 'sess-aaa', {'last_updated_at': '2024-02-01T00:00:00'})
        _make_session_dir(tmp_path, 'sess-bbb', {'last_updated_at': '2024-01-01T00:00:00'})
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            result = get_session_id_by_index(1)
        assert result == 'sess-aaa'

    def test_second_index(self, tmp_path: Path) -> None:
        _make_session_dir(tmp_path, 'sess-aaa', {'last_updated_at': '2024-02-01T00:00:00'})
        _make_session_dir(tmp_path, 'sess-bbb', {'last_updated_at': '2024-01-01T00:00:00'})
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            result = get_session_id_by_index(2)
        assert result == 'sess-bbb'

    def test_out_of_range(self, tmp_path: Path) -> None:
        _make_session_dir(tmp_path, 'sess-aaa', {})
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            result = get_session_id_by_index(99)
        assert result is None

    def test_no_storage(self) -> None:
        with patch('backend.cli.session_manager._find_sessions_root', return_value=None):
            assert get_session_id_by_index(1) is None


# ---------------------------------------------------------------------------
# resolve_session_id
# ---------------------------------------------------------------------------

class TestResolveSessionId:
    def test_empty_target(self) -> None:
        with patch('backend.cli.session_manager._find_sessions_root', return_value=None):
            sid, err = resolve_session_id('')
        assert sid is None
        assert err is not None

    def test_no_storage(self) -> None:
        with patch('backend.cli.session_manager._find_sessions_root', return_value=None):
            sid, err = resolve_session_id('abc')
        assert sid is None
        assert 'storage' in (err or '').lower()

    def test_no_sessions(self, tmp_path: Path) -> None:
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            sid, err = resolve_session_id('1')
        assert sid is None
        assert err is not None

    def test_by_index(self, tmp_path: Path) -> None:
        _make_session_dir(tmp_path, 'sess-abc', {})
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            sid, err = resolve_session_id('1')
        assert sid == 'sess-abc'
        assert err is None

    def test_by_exact_id(self, tmp_path: Path) -> None:
        _make_session_dir(tmp_path, 'sess-abc123', {})
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            sid, err = resolve_session_id('sess-abc123')
        assert sid == 'sess-abc123'
        assert err is None

    def test_by_prefix(self, tmp_path: Path) -> None:
        _make_session_dir(tmp_path, 'sess-abcdef', {})
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            sid, err = resolve_session_id('sess-abc')
        assert sid == 'sess-abcdef'
        assert err is None

    def test_index_out_of_range(self, tmp_path: Path) -> None:
        _make_session_dir(tmp_path, 'sess-abc', {})
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            sid, err = resolve_session_id('99')
        assert sid is None
        assert err is not None

    def test_ambiguous_prefix(self, tmp_path: Path) -> None:
        _make_session_dir(tmp_path, 'sess-abc1', {})
        _make_session_dir(tmp_path, 'sess-abc2', {})
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            sid, err = resolve_session_id('sess-abc')
        assert sid is None
        assert 'ambiguous' in (err or '').lower()

    def test_no_match(self, tmp_path: Path) -> None:
        _make_session_dir(tmp_path, 'sess-xyz', {})
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            sid, err = resolve_session_id('zzz-not-here')
        assert sid is None


# ---------------------------------------------------------------------------
# _resolve_session_index helpers
# ---------------------------------------------------------------------------

class TestResolveSessionIndex:
    def test_valid_index(self) -> None:
        sessions = [('sid1', {}, 0), ('sid2', {}, 0)]
        result, err = _resolve_session_index(sessions, '1')
        assert result == 'sid1'
        assert err is None

    def test_invalid_index(self) -> None:
        sessions = [('sid1', {}, 0)]
        result, err = _resolve_session_index(sessions, '5')
        assert result is None
        assert err is not None


class TestResolveSessionByIdOrPrefix:
    def test_exact_id_match(self) -> None:
        sessions = [('session-abc123', {}, 0), ('session-xyz', {}, 0)]
        result, err = _resolve_session_by_id_or_prefix(sessions, 'session-abc123')
        assert result == 'session-abc123'
        assert err is None

    def test_unique_prefix(self) -> None:
        sessions = [('session-abc', {}, 0), ('session-xyz', {}, 0)]
        result, err = _resolve_session_by_id_or_prefix(sessions, 'session-a')
        assert result == 'session-abc'
        assert err is None

    def test_ambiguous_prefix(self) -> None:
        sessions = [('session-abc1', {}, 0), ('session-abc2', {}, 0)]
        result, err = _resolve_session_by_id_or_prefix(sessions, 'session-abc')
        assert result is None
        assert 'ambiguous' in (err or '').lower()

    def test_no_match(self) -> None:
        sessions = [('session-abc', {}, 0)]
        result, err = _resolve_session_by_id_or_prefix(sessions, 'zzz')
        assert result is None

    def test_more_than_4_ambiguous_matches(self) -> None:
        sessions = [(f'session-abc{i}', {}, 0) for i in range(6)]
        result, err = _resolve_session_by_id_or_prefix(sessions, 'session-abc')
        assert result is None
        assert '...' in (err or '')


# ---------------------------------------------------------------------------
# get_session_suggestions
# ---------------------------------------------------------------------------

class TestGetSessionSuggestions:
    def test_no_storage(self) -> None:
        with patch('backend.cli.session_manager._find_sessions_root', return_value=None):
            suggestions = get_session_suggestions()
        assert suggestions == []

    def test_returns_suggestions(self, tmp_path: Path) -> None:
        _make_session_dir(tmp_path, 'sess-abc', {
            'title': 'My Test',
            'llm_model': 'openai/gpt-4o',
            'last_updated_at': '2024-01-01T10:00:00',
        })
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            suggestions = get_session_suggestions()
        # Should have at least 2 entries per session (index + full id)
        assert len(suggestions) >= 2
        labels = [s[0] for s in suggestions]
        assert '1' in labels
        assert 'sess-abc' in labels

    def test_limit_respected(self, tmp_path: Path) -> None:
        for i in range(10):
            _make_session_dir(tmp_path, f'sess-{i:04d}', {'last_updated_at': f'2024-01-{i+1:02d}T00:00:00'})
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            suggestions = get_session_suggestions(limit=2)
        # 2 sessions × 2 entries each = 4
        assert len(suggestions) == 4

    def test_fallback_title(self, tmp_path: Path) -> None:
        _make_session_dir(tmp_path, 'sess-notitle', {})
        with patch('backend.cli.session_manager._find_sessions_root', return_value=tmp_path):
            suggestions = get_session_suggestions()
        descriptors = [s[1] for s in suggestions]
        assert any('Untitled session' in d for d in descriptors)
