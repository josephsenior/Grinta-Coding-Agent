"""Tests for backend/core/workspace_context.py."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import backend.core.workspace_context as workspace_context
from backend.core.workspace_context import (
    _CHANGELOG_FILE,
    _CONTEXT_FILE,
    _FINGERPRINTS,
    _TAGS_FILE,
    _workspace_anchor,
    append_changelog,
    detect_project_type,
    detect_test_runner,
    ensure_project_state_dir,
    get_conversation_meta,
    get_project_state_dir,
    list_all_tags,
    list_projects,
    read_all_changelog,
    read_month_changelog,
    read_project_memory,
    read_today_changelog,
    read_week_changelog,
    set_conversation_tags,
    today_stats,
    today_total_cost,
    write_context_template,
)


@pytest.fixture
def grinta_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = tmp_path / '_gh'
    fake.mkdir()
    monkeypatch.setenv('HOME', str(fake))
    monkeypatch.setenv('USERPROFILE', str(fake))
    monkeypatch.delenv('PROJECT_ROOT', raising=False)
    monkeypatch.delenv('APP_PROJECT_ROOT', raising=False)


def _project_context(ws: Path) -> Path:
    from backend.core.workspace_resolution import workspace_grinta_root

    return workspace_grinta_root(ws) / 'project_context'


def _write_changelog_entries(ws: Path, entries: list[dict[str, object]]) -> None:
    ensure_project_state_dir(ws)
    changelog = _project_context(ws) / _CHANGELOG_FILE
    lines = [json.dumps(entry) for entry in entries]
    changelog.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _tags_path(ws: Path) -> Path:
    return _project_context(ws) / _TAGS_FILE


# ── get_project_state_dir ────────────────────────────────────────────


class TestGetProjectStateDir:
    def test_uses_cwd_when_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, grinta_home: None
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = get_project_state_dir()
        assert result == _project_context(tmp_path)

    def test_uses_provided_path(self, tmp_path: Path, grinta_home: None) -> None:
        result = get_project_state_dir(tmp_path)
        assert result == _project_context(tmp_path)

    def test_returns_path_object(self, tmp_path: Path, grinta_home: None) -> None:
        result = get_project_state_dir(tmp_path)
        assert isinstance(result, Path)

    def test_subdir_name_is_project_context(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        result = get_project_state_dir(tmp_path)
        assert result.name == 'project_context'


# ── ensure_project_state_dir ────────────────────────────────────────


class TestEnsureProjectStateDir:
    def test_creates_directory(self, tmp_path: Path, grinta_home: None) -> None:
        result = ensure_project_state_dir(tmp_path)
        assert result.is_dir()
        assert result == _project_context(tmp_path)

    def test_creates_gitignore(self, tmp_path: Path, grinta_home: None) -> None:
        result = ensure_project_state_dir(tmp_path)
        gitignore = result / '.gitignore'
        assert gitignore.exists()
        assert 'changelog.jsonl' in gitignore.read_text(encoding='utf-8')

    def test_returns_existing_dir(self, tmp_path: Path, grinta_home: None) -> None:
        ensure_project_state_dir(tmp_path)
        # Second call should not raise
        result = ensure_project_state_dir(tmp_path)
        assert result.is_dir()

    def test_does_not_overwrite_existing_gitignore(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        result = ensure_project_state_dir(tmp_path)
        gitignore = result / '.gitignore'
        original = gitignore.read_text(encoding='utf-8')
        # Write custom content
        gitignore.write_text('custom\n', encoding='utf-8')
        ensure_project_state_dir(tmp_path)
        # Custom content should remain
        assert gitignore.read_text(encoding='utf-8') == 'custom\n'
        assert (
            gitignore.read_text(encoding='utf-8') != original or True
        )  # just doesn't overwrite

    def test_uses_cwd_when_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, grinta_home: None
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = ensure_project_state_dir()
        assert result == _project_context(tmp_path)


# ── read_project_memory ──────────────────────────────────────────────


class TestReadProjectMemory:
    def test_returns_none_when_file_absent(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        assert read_project_memory(tmp_path) is None

    def test_returns_content_when_file_exists(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        project_state_dir = ensure_project_state_dir(tmp_path)
        (project_state_dir / _CONTEXT_FILE).write_text('hello world', encoding='utf-8')
        assert read_project_memory(tmp_path) == 'hello world'

    def test_returns_none_for_empty_file(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        project_state_dir = ensure_project_state_dir(tmp_path)
        (project_state_dir / _CONTEXT_FILE).write_text('', encoding='utf-8')
        assert read_project_memory(tmp_path) is None

    def test_returns_none_for_whitespace_only(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        project_state_dir = ensure_project_state_dir(tmp_path)
        (project_state_dir / _CONTEXT_FILE).write_text('   \n\t  ', encoding='utf-8')
        assert read_project_memory(tmp_path) is None

    def test_strips_content(self, tmp_path: Path, grinta_home: None) -> None:
        project_state_dir = ensure_project_state_dir(tmp_path)
        (project_state_dir / _CONTEXT_FILE).write_text(
            '  content  \n', encoding='utf-8'
        )
        assert read_project_memory(tmp_path) == 'content'

    def test_returns_none_on_os_error(self, tmp_path: Path, grinta_home: None) -> None:
        project_state_dir = ensure_project_state_dir(tmp_path)
        context_path = project_state_dir / _CONTEXT_FILE
        context_path.write_text('data', encoding='utf-8')
        with patch.object(Path, 'read_text', side_effect=OSError('fail')):
            assert read_project_memory(tmp_path) is None


# ── write_context_template ──────────────────────────────────────────


class TestWriteContextTemplate:
    def test_creates_context_file_when_absent(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        path = write_context_template(tmp_path)
        assert path.exists()
        assert path.name == _CONTEXT_FILE

    def test_does_not_overwrite_existing_file(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        project_state_dir = ensure_project_state_dir(tmp_path)
        context_path = project_state_dir / _CONTEXT_FILE
        context_path.write_text('my content', encoding='utf-8')
        write_context_template(tmp_path)
        assert context_path.read_text(encoding='utf-8') == 'my content'

    def test_template_contains_fingerprint(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        # Create pyproject.toml to trigger fingerprint detection
        (tmp_path / 'pyproject.toml').write_text('[project]\n', encoding='utf-8')
        path = write_context_template(tmp_path)
        content = path.read_text(encoding='utf-8')
        assert 'Python' in content

    def test_template_contains_project_context_header(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        path = write_context_template(tmp_path)
        content = path.read_text(encoding='utf-8')
        assert '# Project Context' in content

    def test_creates_project_context_dir_if_missing(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        write_context_template(tmp_path)
        assert _project_context(tmp_path).is_dir()


# ── detect_project_type ──────────────────────────────────────────────


class TestDetectProjectType:
    def test_unknown_for_empty_dir(self, tmp_path: Path) -> None:
        result = detect_project_type(tmp_path)
        assert result == 'Unknown project'

    def test_detects_python_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / 'pyproject.toml').touch()
        result = detect_project_type(tmp_path)
        assert 'Python' in result

    def test_detects_rust(self, tmp_path: Path) -> None:
        (tmp_path / 'Cargo.toml').touch()
        assert 'Rust' in detect_project_type(tmp_path)

    def test_detects_javascript(self, tmp_path: Path) -> None:
        (tmp_path / 'package.json').touch()
        assert 'JavaScript' in detect_project_type(tmp_path)

    def test_detects_go(self, tmp_path: Path) -> None:
        (tmp_path / 'go.mod').touch()
        assert 'Go' in detect_project_type(tmp_path)

    def test_detects_java_maven(self, tmp_path: Path) -> None:
        (tmp_path / 'pom.xml').touch()
        assert 'Java' in detect_project_type(tmp_path)

    def test_detects_docker(self, tmp_path: Path) -> None:
        (tmp_path / 'Dockerfile').touch()
        assert 'Docker' in detect_project_type(tmp_path)

    def test_multiple_detected_comma_separated(self, tmp_path: Path) -> None:
        (tmp_path / 'pyproject.toml').touch()
        (tmp_path / 'Dockerfile').touch()
        result = detect_project_type(tmp_path)
        assert ',' in result
        assert 'Python' in result
        assert 'Docker' in result

    def test_uses_cwd_when_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        # no sentinel files in tmp_path
        assert detect_project_type() == 'Unknown project'

    def test_github_project_detected(self, tmp_path: Path) -> None:
        # .github is a directory sentinel
        (tmp_path / '.github').mkdir()
        assert 'GitHub' in detect_project_type(tmp_path)

    def test_fingerprints_list_non_empty(self) -> None:
        assert len(_FINGERPRINTS) > 0


# ── detect_test_runner ──────────────────────────────────────────────


class TestDetectTestRunner:
    def test_returns_none_for_empty_dir(self, tmp_path: Path) -> None:
        assert detect_test_runner(tmp_path) is None

    def test_detects_pytest_via_pytest_ini(self, tmp_path: Path) -> None:
        (tmp_path / 'pytest.ini').touch()
        assert detect_test_runner(tmp_path) == 'pytest'

    def test_detects_pytest_via_pyproject_toml(self, tmp_path: Path) -> None:
        (tmp_path / 'pyproject.toml').touch()
        assert detect_test_runner(tmp_path) == 'pytest'

    def test_detects_npm_test(self, tmp_path: Path) -> None:
        (tmp_path / 'package.json').touch()
        assert detect_test_runner(tmp_path) == 'npm test'

    def test_detects_cargo_test(self, tmp_path: Path) -> None:
        (tmp_path / 'Cargo.toml').touch()
        assert detect_test_runner(tmp_path) == 'cargo test'

    def test_detects_go_test(self, tmp_path: Path) -> None:
        (tmp_path / 'go.mod').touch()
        assert detect_test_runner(tmp_path) == 'go test ./...'

    def test_detects_make_test(self, tmp_path: Path) -> None:
        (tmp_path / 'Makefile').touch()
        assert detect_test_runner(tmp_path) == 'make test'

    def test_pytest_wins_over_makefile(self, tmp_path: Path) -> None:
        # pytest.ini check comes first
        (tmp_path / 'pytest.ini').touch()
        (tmp_path / 'Makefile').touch()
        assert detect_test_runner(tmp_path) == 'pytest'

    def test_uses_cwd_when_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert detect_test_runner() is None


# ── append_changelog ────────────────────────────────────────────────


class TestAppendChangelog:
    def test_creates_changelog_file(self, tmp_path: Path, grinta_home: None) -> None:
        append_changelog('test_event', {'key': 'val'}, cwd=tmp_path)
        changelog = _project_context(tmp_path) / _CHANGELOG_FILE
        assert changelog.exists()

    def test_appends_valid_json(self, tmp_path: Path, grinta_home: None) -> None:
        append_changelog('test_event', {'key': 'val'}, cwd=tmp_path)
        changelog = _project_context(tmp_path) / _CHANGELOG_FILE
        lines = changelog.read_text(encoding='utf-8').strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry['event'] == 'test_event'
        assert entry['key'] == 'val'

    def test_appends_multiple_entries(self, tmp_path: Path, grinta_home: None) -> None:
        append_changelog('event1', {}, cwd=tmp_path)
        append_changelog('event2', {}, cwd=tmp_path)
        changelog = _project_context(tmp_path) / _CHANGELOG_FILE
        lines = changelog.read_text(encoding='utf-8').strip().splitlines()
        assert len(lines) == 2

    def test_includes_timestamp(self, tmp_path: Path, grinta_home: None) -> None:
        append_changelog('ts_test', {}, cwd=tmp_path)
        changelog = _project_context(tmp_path) / _CHANGELOG_FILE
        entry = json.loads(changelog.read_text(encoding='utf-8').strip())
        assert 'ts' in entry
        assert 'date' in entry

    def test_includes_conversation_id(self, tmp_path: Path, grinta_home: None) -> None:
        append_changelog('ev', {}, conversation_id='conv-123', cwd=tmp_path)
        changelog = _project_context(tmp_path) / _CHANGELOG_FILE
        entry = json.loads(changelog.read_text(encoding='utf-8').strip())
        assert entry['conversation_id'] == 'conv-123'

    def test_swallows_errors_silently(self, tmp_path: Path) -> None:
        # Should not raise even when directory is unwritable
        with patch(
            'backend.core.workspace_context.ensure_project_state_dir',
            side_effect=Exception('boom'),
        ):
            # Should complete without raising
            append_changelog('ev', {}, cwd=tmp_path)

    def test_data_kwargs_merged_into_entry(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        append_changelog('ev', {'path': '/some/file.py', 'size': 42}, cwd=tmp_path)
        changelog = _project_context(tmp_path) / _CHANGELOG_FILE
        entry = json.loads(changelog.read_text(encoding='utf-8').strip())
        assert entry['path'] == '/some/file.py'
        assert entry['size'] == 42


# ── read_today_changelog / read_all_changelog ────────────────────────


class TestReadChangelog:
    def test_returns_empty_when_no_file(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        assert read_today_changelog(tmp_path) == []
        assert read_all_changelog(tmp_path) == []

    def test_read_all_returns_all_entries(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        append_changelog('ev1', {}, cwd=tmp_path)
        append_changelog('ev2', {}, cwd=tmp_path)
        entries = read_all_changelog(tmp_path)
        assert len(entries) == 2
        events = {e['event'] for e in entries}
        assert events == {'ev1', 'ev2'}

    def test_read_today_returns_todays_entries(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        append_changelog('today_event', {}, cwd=tmp_path)
        entries = read_today_changelog(tmp_path)
        assert any(e['event'] == 'today_event' for e in entries)

    def test_skips_invalid_json_lines(self, tmp_path: Path, grinta_home: None) -> None:
        ensure_project_state_dir(tmp_path)
        changelog = _project_context(tmp_path) / _CHANGELOG_FILE
        today = datetime.now(UTC).strftime('%Y-%m-%d')
        changelog.write_text(
            f'{{invalid json}}\n{{"event": "ok", "date": "{today}"}}\n',
            encoding='utf-8',
        )
        entries = read_all_changelog(tmp_path)
        assert len(entries) == 1
        assert entries[0]['event'] == 'ok'

    def test_skips_blank_lines(self, tmp_path: Path, grinta_home: None) -> None:
        ensure_project_state_dir(tmp_path)
        changelog = _project_context(tmp_path) / _CHANGELOG_FILE
        today = datetime.now(UTC).strftime('%Y-%m-%d')
        changelog.write_text(
            f'\n{{"event": "ev", "date": "{today}"}}\n\n',
            encoding='utf-8',
        )
        entries = read_all_changelog(tmp_path)
        assert len(entries) == 1

    def test_read_today_excludes_old_date(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        ensure_project_state_dir(tmp_path)
        changelog = _project_context(tmp_path) / _CHANGELOG_FILE
        changelog.write_text(
            '{"event": "old", "date": "2000-01-01"}\n',
            encoding='utf-8',
        )
        entries = read_today_changelog(tmp_path)
        assert entries == []

    def test_returns_empty_on_os_error(self, tmp_path: Path, grinta_home: None) -> None:
        ensure_project_state_dir(tmp_path)
        changelog = _project_context(tmp_path) / _CHANGELOG_FILE
        changelog.write_text('{"event": "ev"}\n', encoding='utf-8')
        with patch.object(Path, 'read_text', side_effect=OSError('denied')):
            entries = read_all_changelog(tmp_path)
        assert entries == []


# ── today_stats ──────────────────────────────────────────────────────


class TestTodayStats:
    def _write_entries(self, tmp_path: Path, entries: list[dict]) -> None:
        """Helper to write changelog entries with today's date."""
        ensure_project_state_dir(tmp_path)
        changelog = _project_context(tmp_path) / _CHANGELOG_FILE
        today = datetime.now(UTC).strftime('%Y-%m-%d')
        lines = []
        for e in entries:
            e.setdefault('date', today)
            e.setdefault('ts', datetime.now(UTC).isoformat())
            lines.append(json.dumps(e))
        changelog.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    def test_empty_when_no_changelog(self, tmp_path: Path, grinta_home: None) -> None:
        stats = today_stats(tmp_path)
        assert stats['sessions'] == 0
        assert stats['edits'] == 0
        assert stats['files'] == 0

    def test_counts_sessions(self, tmp_path: Path, grinta_home: None) -> None:
        self._write_entries(
            tmp_path,
            [
                {'event': 'file_edit', 'conversation_id': 'session-A', 'path': '/a.py'},
                {'event': 'file_edit', 'conversation_id': 'session-B', 'path': '/b.py'},
                {'event': 'file_edit', 'conversation_id': 'session-A', 'path': '/c.py'},
            ],
        )
        stats = today_stats(tmp_path)
        assert stats['sessions'] == 2

    def test_counts_file_edits(self, tmp_path: Path, grinta_home: None) -> None:
        self._write_entries(
            tmp_path,
            [
                {'event': 'file_edit', 'path': '/a.py'},
                {'event': 'file_edit', 'path': '/a.py'},
                {'event': 'file_edit', 'path': '/b.py'},
            ],
        )
        stats = today_stats(tmp_path)
        assert stats['edits'] == 3
        assert stats['files'] == 2  # unique paths

    def test_counts_new_files(self, tmp_path: Path, grinta_home: None) -> None:
        self._write_entries(
            tmp_path,
            [
                {'event': 'file_write', 'path': '/new.py'},
                {'event': 'file_write', 'path': '/new2.py'},
            ],
        )
        stats = today_stats(tmp_path)
        assert stats['new_files'] == 2

    def test_counts_tasks_done(self, tmp_path: Path, grinta_home: None) -> None:
        self._write_entries(
            tmp_path,
            [
                {'event': 'task_finished'},
                {'event': 'task_finished'},
                {'event': 'task_error'},
            ],
        )
        stats = today_stats(tmp_path)
        assert stats['tasks_done'] == 2
        assert stats['tasks_error'] == 1

    def test_accumulates_cost_update_max(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        self._write_entries(
            tmp_path,
            [
                {'event': 'cost_update', 'cost': 1.5},
                {'event': 'cost_update', 'cost': 2.5},
                {'event': 'cost_update', 'cost': 0.5},
            ],
        )
        stats = today_stats(tmp_path)
        assert stats['total_cost'] == pytest.approx(2.5)

    def test_empty_path_not_added_to_files(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        self._write_entries(
            tmp_path,
            [
                {'event': 'file_edit', 'path': ''},
            ],
        )
        stats = today_stats(tmp_path)
        assert stats['files'] == 0

    def test_keys_present_in_result(self, tmp_path: Path, grinta_home: None) -> None:
        stats = today_stats(tmp_path)
        expected_keys = {
            'sessions',
            'files',
            'edits',
            'new_files',
            'total_cost',
            'tasks_done',
            'tasks_error',
        }
        assert expected_keys.issubset(stats.keys())


class TestWorkspaceAnchorFallbacks:
    def test_returns_unresolved_provided_cwd_when_resolution_fails(
        self, tmp_path: Path
    ) -> None:
        with patch.object(workspace_context.Path, 'resolve', side_effect=OSError('boom')):
            assert _workspace_anchor(tmp_path) == tmp_path

    def test_returns_unresolved_workspace_root_when_resolution_fails(
        self, tmp_path: Path
    ) -> None:
        with patch(
            'backend.core.workspace_resolution.get_effective_workspace_root',
            return_value=tmp_path,
        ):
            with patch.object(
                workspace_context.Path,
                'resolve',
                side_effect=OSError('boom'),
            ):
                assert _workspace_anchor(None) == tmp_path

    def test_falls_back_to_process_cwd_when_workspace_root_missing_and_unresolvable(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with patch(
            'backend.core.workspace_resolution.get_effective_workspace_root',
            return_value=None,
        ):
            with patch.object(
                workspace_context.Path,
                'resolve',
                side_effect=OSError('boom'),
            ):
                assert _workspace_anchor(None) == tmp_path


class TestAdditionalChangelogViews:
    def test_read_week_changelog_filters_to_last_seven_days(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        today = datetime.now(UTC)
        cutoff = (today - timedelta(days=6)).strftime('%Y-%m-%d')
        too_old = (today - timedelta(days=7)).strftime('%Y-%m-%d')
        _write_changelog_entries(
            tmp_path,
            [
                {'event': 'today', 'date': today.strftime('%Y-%m-%d')},
                {'event': 'cutoff', 'date': cutoff},
                {'event': 'old', 'date': too_old},
            ],
        )

        events = {entry['event'] for entry in read_week_changelog(tmp_path)}

        assert events == {'today', 'cutoff'}

    def test_read_month_changelog_filters_to_current_month(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        today = datetime.now(UTC)
        if today.month == 1:
            previous_month = f'{today.year - 1}-12-15'
        else:
            previous_month = f'{today.year}-{today.month - 1:02d}-15'
        _write_changelog_entries(
            tmp_path,
            [
                {'event': 'current', 'date': today.strftime('%Y-%m-01')},
                {'event': 'previous', 'date': previous_month},
            ],
        )

        entries = read_month_changelog(tmp_path)

        assert [entry['event'] for entry in entries] == ['current']


class TestTodayTotalCost:
    def test_sums_max_cost_per_session(self, tmp_path: Path, grinta_home: None) -> None:
        today = datetime.now(UTC).strftime('%Y-%m-%d')
        _write_changelog_entries(
            tmp_path,
            [
                {'event': 'cost_update', 'conversation_id': 'a', 'cost': 1.25, 'date': today},
                {'event': 'cost_update', 'conversation_id': 'a', 'cost': 2.5, 'date': today},
                {'event': 'cost_update', 'conversation_id': 'b', 'cost': 3.75, 'date': today},
                {'event': 'file_edit', 'conversation_id': 'a', 'path': '/tmp/x.py', 'date': today},
            ],
        )

        assert today_total_cost(tmp_path) == pytest.approx(6.25)

    def test_uses_single_anonymous_bucket_for_missing_conversation_id(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        today = datetime.now(UTC).strftime('%Y-%m-%d')
        _write_changelog_entries(
            tmp_path,
            [
                {'event': 'cost_update', 'cost': 1.0, 'date': today},
                {'event': 'cost_update', 'cost': 2.5, 'date': today},
                {'event': 'cost_update', 'conversation_id': 'named', 'cost': 4.0, 'date': today},
            ],
        )

        assert today_total_cost(tmp_path) == pytest.approx(6.5)


class TestConversationTags:
    def test_get_conversation_meta_defaults_when_store_missing(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        assert get_conversation_meta('missing', cwd=tmp_path) == {
            'tags': [],
            'project': '',
        }

    def test_get_conversation_meta_defaults_when_store_is_invalid_json(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        ensure_project_state_dir(tmp_path)
        _tags_path(tmp_path).write_text('{bad json', encoding='utf-8')

        assert get_conversation_meta('missing', cwd=tmp_path) == {
            'tags': [],
            'project': '',
        }

    def test_set_conversation_tags_normalizes_deduplicates_and_preserves_project(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        ensure_project_state_dir(tmp_path)
        _tags_path(tmp_path).write_text(
            json.dumps(
                {
                    'conv-1': {'tags': ['legacy'], 'project': 'Alpha'},
                }
            ),
            encoding='utf-8',
        )

        set_conversation_tags(
            'conv-1',
            [' Bug ', '#bug', 'Feature', '  '],
            cwd=tmp_path,
        )

        assert get_conversation_meta('conv-1', cwd=tmp_path) == {
            'tags': ['bug', 'feature'],
            'project': 'Alpha',
        }

    def test_set_conversation_tags_updates_project_and_lists_unique_values(
        self, tmp_path: Path, grinta_home: None
    ) -> None:
        set_conversation_tags('conv-a', ['#beta', 'alpha'], project=' Zebra ', cwd=tmp_path)
        set_conversation_tags('conv-b', ['alpha', 'gamma'], project='Alpha', cwd=tmp_path)
        set_conversation_tags('conv-c', ['gamma'], project='Alpha', cwd=tmp_path)

        assert get_conversation_meta('conv-a', cwd=tmp_path) == {
            'tags': ['alpha', 'beta'],
            'project': 'Zebra',
        }
        assert list_projects(tmp_path) == ['Alpha', 'Zebra']
        assert list_all_tags(tmp_path) == ['alpha', 'beta', 'gamma']

    def test_save_tags_store_swallows_errors(self, tmp_path: Path) -> None:
        with patch(
            'backend.core.workspace_context.ensure_project_state_dir',
            side_effect=OSError('boom'),
        ):
            workspace_context._save_tags_store(
                {'conv': {'tags': ['alpha'], 'project': 'proj'}},
                cwd=tmp_path,
            )
