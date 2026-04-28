"""Tests for backend.cli.sessions_cli."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from backend.cli.sessions_cli import (
    _SessionResolveFailure,
    _build_session_table,
    _format_session_row,
    _resolve_by_index,
    _resolve_by_prefix,
    _session_older_than_cutoff,
    cmd_delete,
    cmd_export,
    cmd_list,
    cmd_prune,
    cmd_show,
)


def _make_console() -> Console:
    return Console(quiet=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_META: dict[str, Any] = {
    'title': 'My Session',
    'llm_model': 'openai/gpt-4o',
    'accumulated_cost': 0.0012,
    'last_updated_at': '2024-11-15T12:00:00',
}

_SAMPLE_ROWS: list[tuple[str, dict[str, Any], int, Path]] = [
    ('session-aabbcc', _SAMPLE_META, 10, Path('/fake/session-aabbcc')),
    ('session-ddeeff', {'title': 'Second'}, 5, Path('/fake/session-ddeeff')),
    ('session-112233', {}, 0, Path('/fake/session-112233')),
]


class TestFormatSessionRow:
    def test_full_metadata(self) -> None:
        row = _format_session_row(1, 'abc123456789', _SAMPLE_META, 10)
        assert row[0] == '1'
        assert row[1] == 'abc123456789'[:12]
        assert row[2] == 'My Session'
        assert 'gpt-4o' in row[3]
        assert row[4] == '10'
        assert row[5].startswith('$')
        assert row[6] == '2024-11-15T12:00:00'[:19]

    def test_missing_metadata(self) -> None:
        row = _format_session_row(2, 'xyz', {}, 0)
        assert row[0] == '2'
        assert row[2] == '—'
        assert row[3] == '—'
        assert row[5] == '—'

    def test_zero_cost_renders_dash(self) -> None:
        row = _format_session_row(1, 'abc', {'accumulated_cost': 0}, 0)
        assert row[5] == '—'

    def test_cost_present(self) -> None:
        row = _format_session_row(1, 'abc', {'accumulated_cost': 1.5}, 3)
        assert row[5] == '$1.5000'

    def test_model_truncated_to_24(self) -> None:
        long_model = 'anthropic/claude-opus-long-name-here-x'
        row = _format_session_row(1, 'abc', {'llm_model': long_model}, 0)
        assert len(row[3]) <= 24

    def test_sid_truncated_to_12(self) -> None:
        row = _format_session_row(1, 'abcdefghijklmnopqrst', {}, 0)
        assert row[1] == 'abcdefghijkl'


class TestBuildSessionTable:
    def test_returns_table_with_columns(self) -> None:
        table = _build_session_table()
        # Rich Table has column_headers list
        col_names = [c.header for c in table.columns]
        assert '#' in col_names
        assert 'ID' in col_names
        assert 'Title' in col_names


class TestResolveByIndex:
    def test_valid_index(self) -> None:
        result = _resolve_by_index(_SAMPLE_ROWS, 1)
        assert result is not None
        assert result[0] == 'session-aabbcc'

    def test_last_index(self) -> None:
        result = _resolve_by_index(_SAMPLE_ROWS, 3)
        assert result is not None
        assert result[0] == 'session-112233'

    def test_zero_returns_none(self) -> None:
        assert _resolve_by_index(_SAMPLE_ROWS, 0) is None

    def test_too_large_returns_none(self) -> None:
        assert _resolve_by_index(_SAMPLE_ROWS, 100) is None


class TestResolveByPrefix:
    def test_exact_match(self) -> None:
        result = _resolve_by_prefix(_SAMPLE_ROWS, 'session-aabbcc')
        assert result is not None
        assert not isinstance(result, _SessionResolveFailure)
        assert result[0] == 'session-aabbcc'

    def test_unique_prefix(self) -> None:
        result = _resolve_by_prefix(_SAMPLE_ROWS, 'session-aa')
        assert result is not None
        assert not isinstance(result, _SessionResolveFailure)
        assert result[0] == 'session-aabbcc'

    def test_ambiguous_prefix(self) -> None:
        result = _resolve_by_prefix(_SAMPLE_ROWS, 'session-')
        assert isinstance(result, _SessionResolveFailure)
        assert 'ambiguous' in result.message.lower()

    def test_no_match(self) -> None:
        result = _resolve_by_prefix(_SAMPLE_ROWS, 'zzz')
        assert result is None


class TestSessionOlderThanCutoff:
    def test_old_timestamp(self) -> None:
        meta = {'last_updated_at': '2020-01-01T00:00:00'}
        cutoff = datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert _session_older_than_cutoff(meta, Path('/fake'), cutoff) is True

    def test_recent_timestamp(self) -> None:
        meta = {'last_updated_at': '2099-01-01T00:00:00'}
        cutoff = datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert _session_older_than_cutoff(meta, Path('/fake'), cutoff) is False

    def test_no_timestamp_uses_mtime(self, tmp_path: Path) -> None:
        old_file = tmp_path / 'old'
        old_file.mkdir()
        import os
        import time

        # Set mtime to a very old value
        old_ts = 1000.0  # very old epoch
        os.utime(old_file, (old_ts, old_ts))
        cutoff = datetime.now(timezone.utc)
        assert _session_older_than_cutoff({}, old_file, cutoff) is True

    def test_no_timestamp_missing_path_returns_false(self) -> None:
        assert _session_older_than_cutoff({}, Path('/does-not-exist'), datetime.now(timezone.utc)) is False

    def test_invalid_timestamp_format(self) -> None:
        meta = {'last_updated_at': 'not-a-date'}
        cutoff = datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert _session_older_than_cutoff(meta, Path('/fake'), cutoff) is False


class TestCmdList:
    def test_no_sessions(self) -> None:
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=[]):
            rc = cmd_list(console)
        assert rc == 0

    def test_with_sessions(self) -> None:
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=_SAMPLE_ROWS):
            rc = cmd_list(console, limit=10)
        assert rc == 0

    def test_limit_too_small(self) -> None:
        console = _make_console()
        rc = cmd_list(console, limit=0)
        assert rc == 2

    def test_limit_negative(self) -> None:
        console = _make_console()
        rc = cmd_list(console, limit=-1)
        assert rc == 2

    def test_limit_respected(self) -> None:
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=_SAMPLE_ROWS):
            rc = cmd_list(console, limit=1)
        assert rc == 0


class TestCmdShow:
    def test_no_sessions(self) -> None:
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=[]):
            rc = cmd_show(console, 'abc')
        assert rc == 2

    def test_found_by_prefix(self) -> None:
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=_SAMPLE_ROWS):
            rc = cmd_show(console, 'session-aa')
        assert rc == 0

    def test_found_by_index(self) -> None:
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=_SAMPLE_ROWS):
            rc = cmd_show(console, '1')
        assert rc == 0

    def test_ambiguous_target(self) -> None:
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=_SAMPLE_ROWS):
            rc = cmd_show(console, 'session-')
        assert rc == 2

    def test_not_found(self) -> None:
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=_SAMPLE_ROWS):
            rc = cmd_show(console, 'zzz-not-there')
        assert rc == 2

    def test_shows_metadata(self, capsys) -> None:
        console = Console()
        with patch('backend.cli.sessions_cli._entries', return_value=_SAMPLE_ROWS):
            cmd_show(console, 'session-aabbcc')
        # No error = success


class TestCmdExport:
    def test_export_as_tree(self, tmp_path: Path) -> None:
        src = tmp_path / 'source' / 'session-aabbcc'
        src.mkdir(parents=True)
        (src / 'events').mkdir()
        (src / 'events' / 'ev1.json').write_text('{}', encoding='utf-8')
        rows: list[tuple[str, dict[str, Any], int, Path]] = [
            ('session-aabbcc', _SAMPLE_META, 1, src),
        ]
        out = tmp_path / 'export' / 'out'
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=rows):
            rc = cmd_export(console, 'session-aabbcc', str(out))
        assert rc == 0
        assert (out / 'events' / 'ev1.json').exists()

    def test_export_as_zip(self, tmp_path: Path) -> None:
        src = tmp_path / 'session-aabbcc'
        src.mkdir()
        (src / 'data.json').write_text('{}', encoding='utf-8')
        rows: list[tuple[str, dict[str, Any], int, Path]] = [
            ('session-aabbcc', _SAMPLE_META, 1, src),
        ]
        out = tmp_path / 'archive.zip'
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=rows):
            rc = cmd_export(console, 'session-aabbcc', str(out))
        assert rc == 0

    def test_not_found(self, tmp_path: Path) -> None:
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=_SAMPLE_ROWS):
            rc = cmd_export(console, 'zzz', str(tmp_path / 'out'))
        assert rc == 2

    def test_ambiguous(self, tmp_path: Path) -> None:
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=_SAMPLE_ROWS):
            rc = cmd_export(console, 'session-', str(tmp_path / 'out'))
        assert rc == 2


class TestCmdDelete:
    def test_delete_with_yes(self, tmp_path: Path) -> None:
        src = tmp_path / 'session-aabbcc'
        src.mkdir()
        rows: list[tuple[str, dict[str, Any], int, Path]] = [
            ('session-aabbcc', _SAMPLE_META, 1, src),
        ]
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=rows):
            rc = cmd_delete(console, 'session-aabbcc', yes=True)
        assert rc == 0
        assert not src.exists()

    def test_delete_aborted_no_confirm(self, tmp_path: Path) -> None:
        src = tmp_path / 'session-aabbcc'
        src.mkdir()
        rows: list[tuple[str, dict[str, Any], int, Path]] = [
            ('session-aabbcc', _SAMPLE_META, 1, src),
        ]
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=rows):
            with patch('rich.prompt.Confirm.ask', return_value=False):
                rc = cmd_delete(console, 'session-aabbcc', yes=False)
        assert rc == 0
        assert src.exists()

    def test_delete_confirmed(self, tmp_path: Path) -> None:
        src = tmp_path / 'session-aabbcc'
        src.mkdir()
        rows: list[tuple[str, dict[str, Any], int, Path]] = [
            ('session-aabbcc', _SAMPLE_META, 1, src),
        ]
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=rows):
            with patch('rich.prompt.Confirm.ask', return_value=True):
                rc = cmd_delete(console, 'session-aabbcc', yes=False)
        assert rc == 0
        assert not src.exists()

    def test_delete_not_found(self) -> None:
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=_SAMPLE_ROWS):
            rc = cmd_delete(console, 'zzz', yes=True)
        assert rc == 2

    def test_delete_ambiguous(self) -> None:
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=_SAMPLE_ROWS):
            rc = cmd_delete(console, 'session-', yes=True)
        assert rc == 2


class TestCmdPrune:
    def test_negative_days(self) -> None:
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=_SAMPLE_ROWS):
            rc = cmd_prune(console, days=-1)
        assert rc == 2

    def test_no_old_sessions(self) -> None:
        console = _make_console()
        future_meta = {'last_updated_at': '2099-01-01T00:00:00'}
        rows: list[tuple[str, dict[str, Any], int, Path]] = [
            ('session-future', future_meta, 1, Path('/fake/session-future')),
        ]
        with patch('backend.cli.sessions_cli._entries', return_value=rows):
            rc = cmd_prune(console, days=30)
        assert rc == 0

    def test_prune_aborted(self, tmp_path: Path) -> None:
        src = tmp_path / 'session-old'
        src.mkdir()
        old_meta = {'last_updated_at': '2020-01-01T00:00:00'}
        rows: list[tuple[str, dict[str, Any], int, Path]] = [
            ('session-old', old_meta, 0, src),
        ]
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=rows):
            with patch('rich.prompt.Confirm.ask', return_value=False):
                rc = cmd_prune(console, days=30, yes=False)
        assert rc == 0
        assert src.exists()

    def test_prune_with_yes(self, tmp_path: Path) -> None:
        src = tmp_path / 'session-old'
        src.mkdir()
        old_meta = {'last_updated_at': '2020-01-01T00:00:00'}
        rows: list[tuple[str, dict[str, Any], int, Path]] = [
            ('session-old', old_meta, 0, src),
        ]
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=rows):
            rc = cmd_prune(console, days=30, yes=True)
        assert rc == 0
        assert not src.exists()

    def test_prune_confirmed(self, tmp_path: Path) -> None:
        src = tmp_path / 'session-old'
        src.mkdir()
        old_meta = {'last_updated_at': '2020-01-01T00:00:00'}
        rows: list[tuple[str, dict[str, Any], int, Path]] = [
            ('session-old', old_meta, 0, src),
        ]
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=rows):
            with patch('rich.prompt.Confirm.ask', return_value=True):
                rc = cmd_prune(console, days=30, yes=False)
        assert rc == 0
        assert not src.exists()

    def test_empty_entries(self) -> None:
        console = _make_console()
        with patch('backend.cli.sessions_cli._entries', return_value=[]):
            rc = cmd_prune(console, days=30)
        assert rc == 0
