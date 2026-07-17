"""Extended E2E tests for CLI workflows, subcommands, and session management."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _get_base_env(tmp_path: Path) -> dict[str, str]:
    """Create a minimal test environment with PYTHONPATH set to repo root."""
    env = os.environ.copy()
    env.update(
        {
            'LLM_API_KEY': 'sk-test-e2e-key',
            'LLM_MODEL': 'openai/gpt-4.1',
            'GRINTA_NO_SPLASH': '1',
            'LOG_TO_FILE': 'false',
            'PYTHONUTF8': '1',
            'HOME': str(tmp_path),
            'USERPROFILE': str(tmp_path),
        }
    )
    existing = env.get('PYTHONPATH', '')
    parts = [str(_REPO_ROOT)]
    if existing:
        parts.append(existing)
    env['PYTHONPATH'] = os.pathsep.join(parts)
    return env


class TestCLISessionsE2E:
    """E2E tests for session management subcommands."""

    @pytest.mark.e2e
    def test_sessions_list_empty(self, tmp_path: Path) -> None:
        """Verify sessions list runs and is empty for a fresh home directory."""
        env = _get_base_env(tmp_path)
        
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                'sessions',
                'list',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        assert result.returncode == 0
        assert 'session' in result.stdout.lower() or result.stdout.strip() == ""

    @pytest.mark.e2e
    def test_sessions_show_nonexistent(self, tmp_path: Path) -> None:
        """Verify showing a nonexistent session exits with error."""
        env = _get_base_env(tmp_path)
        
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                'sessions',
                'show',
                '00000000',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        # Should exit with non-zero code or print error
        assert result.returncode != 0
        combined = f"{result.stdout}\n{result.stderr}".lower()
        assert 'no session matches' in combined or 'not found' in combined

    @pytest.mark.e2e
    def test_sessions_delete_nonexistent(self, tmp_path: Path) -> None:
        """Verify deleting a nonexistent session exits with error."""
        env = _get_base_env(tmp_path)
        
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                'sessions',
                'delete',
                '00000000',
                '--yes',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        # Should exit with non-zero code or print error
        assert result.returncode != 0
        combined = f"{result.stdout}\n{result.stderr}".lower()
        assert 'no session matches' in combined or 'not found' in combined

    @pytest.mark.e2e
    def test_sessions_export_nonexistent(self, tmp_path: Path) -> None:
        """Verify exporting a nonexistent session exits with error."""
        env = _get_base_env(tmp_path)
        
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                'sessions',
                'export',
                '00000000',
                str(tmp_path / 'export_out'),
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        # Should exit with non-zero code or print error
        assert result.returncode != 0
        combined = f"{result.stdout}\n{result.stderr}".lower()
        assert 'no session matches' in combined or 'not found' in combined

    @pytest.mark.e2e
    def test_sessions_prune_runs(self, tmp_path: Path) -> None:
        """Verify session pruning executes without errors."""
        env = _get_base_env(tmp_path)
        
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                'sessions',
                'prune',
                '--days',
                '30',
                '--yes',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        assert result.returncode == 0
        assert 'no sessions' in result.stdout.lower() or 'pruned' in result.stdout.lower()
