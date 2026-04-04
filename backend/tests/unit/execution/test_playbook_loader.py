"""Tests for backend.execution.playbook_loader.PlaybookLoaderMixin.

Targets 18.7% coverage gap.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

import pytest

from backend.execution.playbook_loader import PlaybookLoaderMixin
from backend.ledger.observation import (
    CmdOutputObservation,
    ErrorObservation,
    FileReadObservation,
)
from backend.playbooks.engine import BasePlaybook

# -----------------------------------------------------------
# Concrete host stub
# -----------------------------------------------------------


class _FakeRuntime(PlaybookLoaderMixin):
    """Minimal concrete host so the mixin can be exercised."""

    def __init__(self):
        self.sid = 'test-sid'
        self.workspace_root = Path(tempfile.mkdtemp())
        self.status_callback = None
        self.provider_handler = MagicMock()
        self._logs: list[tuple[str, str]] = []

    def log(self, level: str, message: str) -> None:
        self._logs.append((level, message))

    def read(self, action: Any) -> Any:
        return ErrorObservation(content='not found')

    def list_files(self, path: str, recursive: bool = False) -> list[str]:
        return []

    def copy_from(self, path: str) -> Path:
        return Path(path)

    def run_action(self, action: Any) -> Any:
        return CmdOutputObservation(
            content='ok', command_id=0, command='echo ok', exit_code=0
        )


@pytest.fixture()
def rt():
    r = _FakeRuntime()
    yield r
    shutil.rmtree(r.workspace_root, ignore_errors=True)


# -----------------------------------------------------------
# _extract_org_name
# -----------------------------------------------------------


class TestExtractOrgName:
    def test_valid_repo_path(self, rt: _FakeRuntime):
        assert rt._extract_org_name('github.com/acme-co/api') == 'acme-co'

    def test_two_parts(self, rt: _FakeRuntime):
        assert rt._extract_org_name('acme/repo') == 'acme'

    def test_single_part_returns_none(self, rt: _FakeRuntime):
        assert rt._extract_org_name('single') is None


# -----------------------------------------------------------
# _get_org_config_repo_path
# -----------------------------------------------------------


class TestGetOrgConfigRepoPath:
    def test_returns_org_app_path(self, rt: _FakeRuntime):
        result = rt._get_org_config_repo_path('github.com/acme/repo', 'acme')
        assert result == 'acme/.grinta'


# -----------------------------------------------------------
# _load_playbooks_from_directory
# -----------------------------------------------------------


class TestLoadPlaybooksFromDirectory:
    def test_no_files_returns_empty(self, rt: _FakeRuntime):
        result = rt._load_playbooks_from_directory(Path('/tmp/fake'), 'test')
        assert result == []

    @patch('backend.execution.playbook_loader.load_playbooks_from_dir')
    def test_loads_from_zip(self, mock_load, rt: _FakeRuntime):
        # Set up list_files to return something
        cast(Any, rt).list_files = MagicMock(return_value=['playbook.md'])

        # Create a temp zip file
        tmp_zip = Path(tempfile.mktemp(suffix='.zip'))
        with ZipFile(tmp_zip, 'w') as zf:
            zf.writestr('playbook.md', '# Test')

        cast(Any, rt).copy_from = MagicMock(return_value=tmp_zip)
        mock_load.return_value = ({'a': MagicMock(spec=BasePlaybook)}, {})

        result = rt._load_playbooks_from_directory(Path('/some/dir'), 'test')
        assert len(result) == 1
        mock_load.assert_called_once()

    @patch('backend.execution.playbook_loader.load_playbooks_from_dir')
    def test_loads_from_directory(self, mock_load, rt: _FakeRuntime):
        cast(Any, rt).list_files = MagicMock(return_value=['playbook.md'])

        tmp_dir = Path(tempfile.mkdtemp())
        (tmp_dir / 'playbook.md').write_text('# Test')
        cast(Any, rt).copy_from = MagicMock(return_value=tmp_dir)
        mock_load.return_value = ({}, {'k': MagicMock(spec=BasePlaybook)})

        result = rt._load_playbooks_from_directory(Path('/some/dir'), 'test')
        assert len(result) == 1
        shutil.rmtree(tmp_dir, ignore_errors=True)

    @patch('backend.execution.playbook_loader.load_playbooks_from_dir')
    def test_handles_exception_gracefully(self, mock_load, rt: _FakeRuntime):
        cast(Any, rt).list_files = MagicMock(return_value=['f.md'])
        tmp_zip = Path(tempfile.mktemp(suffix='.zip'))
        with ZipFile(tmp_zip, 'w') as zf:
            zf.writestr('f.md', 'x')
        cast(Any, rt).copy_from = MagicMock(return_value=tmp_zip)
        mock_load.side_effect = RuntimeError('boom')

        result = rt._load_playbooks_from_directory(Path('/d'), 'test')
        assert result == []
        assert any('Failed' in msg for _, msg in rt._logs)


# -----------------------------------------------------------
# _log_clone_failure
# -----------------------------------------------------------


class TestLogCloneFailure:
    def test_with_cmd_output_obs(self, rt: _FakeRuntime):
        obs = CmdOutputObservation(
            content='error output', command_id=0, command='git clone', exit_code=128
        )
        rt._log_clone_failure(obs, 'acme/.grinta')
        assert any('128' in msg for _, msg in rt._logs)

    def test_with_non_cmd_obs(self, rt: _FakeRuntime):
        obs = MagicMock(spec=[])  # no content or exit_code
        rt._log_clone_failure(obs, 'acme/.grinta')
        assert any('N/A' in msg for _, msg in rt._logs)


# -----------------------------------------------------------
# get_playbooks_from_org_or_user
# -----------------------------------------------------------


class TestGetPlaybooksFromOrgOrUser:
    def test_short_repo_path_returns_empty(self, rt: _FakeRuntime):
        assert rt.get_playbooks_from_org_or_user('single') == []

    @patch.object(PlaybookLoaderMixin, '_clone_and_load_org_playbooks')
    def test_valid_repo_delegates_to_clone(self, mock_clone, rt: _FakeRuntime):
        mock_clone.return_value = [MagicMock(spec=BasePlaybook)]
        result = rt.get_playbooks_from_org_or_user('github.com/acme/repo')
        assert len(result) == 1
        mock_clone.assert_called_once_with('acme', 'acme/.grinta')


# -----------------------------------------------------------
# _clone_and_load_org_playbooks
# -----------------------------------------------------------


class TestCloneAndLoadOrgPlaybooks:
    def test_auth_error_returns_empty(self, rt: _FakeRuntime):
        from backend.core.provider_types import AuthenticationError

        rt.provider_handler.get_authenticated_git_url = MagicMock()
        with patch(
            'backend.execution.playbook_loader.call_async_from_sync',
            side_effect=AuthenticationError('nope'),
        ):
            result = rt._clone_and_load_org_playbooks('acme', 'acme/.grinta')
        assert result == []

    def test_generic_error_returns_empty(self, rt: _FakeRuntime):
        with patch(
            'backend.execution.playbook_loader.call_async_from_sync',
            side_effect=RuntimeError('unexpected'),
        ):
            result = rt._clone_and_load_org_playbooks('acme', 'acme/.grinta')
        assert result == []

    @patch.object(PlaybookLoaderMixin, '_execute_clone_and_load')
    def test_successful_auth_delegates(self, mock_exec, rt: _FakeRuntime):
        with patch(
            'backend.execution.playbook_loader.call_async_from_sync',
            return_value='https://token@github.com/acme/.grinta',
        ):
            mock_exec.return_value = []
            rt._clone_and_load_org_playbooks('acme', 'acme/.grinta')
        mock_exec.assert_called_once()


# -----------------------------------------------------------
# _execute_clone_and_load
# -----------------------------------------------------------


class TestExecuteCloneAndLoad:
    def test_clone_failure_returns_empty(self, rt: _FakeRuntime):
        cast(Any, rt).run_action = MagicMock(
            return_value=CmdOutputObservation(
                content='fatal', command_id=0, command='git clone', exit_code=128
            )
        )
        result = rt._execute_clone_and_load(
            rt.workspace_root / 'org', 'https://x', 'acme/.grinta'
        )
        assert result == []

    @patch.object(PlaybookLoaderMixin, '_load_and_cleanup_org_playbooks')
    def test_clone_success_loads(self, mock_load, rt: _FakeRuntime):
        cast(Any, rt).run_action = MagicMock(
            return_value=CmdOutputObservation(
                content='done', command_id=0, command='git clone', exit_code=0
            )
        )
        mock_load.return_value = [MagicMock(spec=BasePlaybook)]
        result = rt._execute_clone_and_load(
            rt.workspace_root / 'org', 'https://x', 'acme/.grinta'
        )
        assert len(result) == 1


# -----------------------------------------------------------
# get_playbooks_from_selected_repo
# -----------------------------------------------------------


class TestGetPlaybooksFromSelectedRepo:
    def test_no_selected_repo_loads_workspace(self, rt: _FakeRuntime):
        # read returns ErrorObservation, no APP_instructions
        result = rt.get_playbooks_from_selected_repo(None)
        # Should still call _load_playbooks_from_directory
        assert isinstance(result, list)

    @patch.object(PlaybookLoaderMixin, '_load_playbooks_from_directory')
    def test_workspace_repo_playbooks_dir_uses_app_path(
        self, mock_load, rt: _FakeRuntime
    ):
        mock_load.return_value = []

        rt.get_playbooks_from_selected_repo(None)

        mock_load.assert_called_once_with(
            rt.workspace_root / '.grinta' / 'playbooks', 'repository'
        )

    @patch.object(PlaybookLoaderMixin, 'get_playbooks_from_org_or_user')
    def test_with_selected_repo_loads_org_and_repo(self, mock_org, rt: _FakeRuntime):
        mock_org.return_value = []
        result = rt.get_playbooks_from_selected_repo('github.com/acme/repo')
        mock_org.assert_called_once_with('github.com/acme/repo')
        assert isinstance(result, list)

    @patch.object(PlaybookLoaderMixin, '_load_playbooks_from_directory')
    @patch.object(PlaybookLoaderMixin, 'get_playbooks_from_org_or_user')
    def test_selected_repo_playbooks_dir_uses_app_path(
        self, mock_org, mock_load, rt: _FakeRuntime
    ):
        mock_org.return_value = []
        mock_load.return_value = []

        rt.get_playbooks_from_selected_repo('github.com/acme/repo')

        mock_load.assert_called_once_with(
            rt.workspace_root / 'repo' / '.grinta' / 'playbooks',
            'repository',
        )

    @patch.object(PlaybookLoaderMixin, 'get_playbooks_from_org_or_user')
    def test_loads_app_instructions_file(self, mock_org, rt: _FakeRuntime):
        mock_org.return_value = []
        # Make read return a FileReadObservation for .APP_instructions
        cast(Any, rt).read = MagicMock(
            return_value=FileReadObservation(
                content='# App instructions content', path='.APP_instructions'
            )
        )
        cast(Any, rt).list_files = MagicMock(return_value=[])
        rt.get_playbooks_from_selected_repo('github.com/acme/repo')
        assert any('APP_instructions' in msg for _, msg in rt._logs)
