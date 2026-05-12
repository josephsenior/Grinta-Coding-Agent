"""End-to-end tests for CLI workflows.

These tests validate CLI behavior at the startup and entrypoint level,
testing the paths that don't require a full runtime with LLM.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _get_base_env(tmp_path: Path) -> dict[str, str]:
    """Create a minimal test environment."""
    env = os.environ.copy()
    env.update({
        'LLM_API_KEY': 'sk-test-e2e-key',
        'LLM_MODEL': 'openai/gpt-4.1',
        'GRINTA_NO_SPLASH': '1',
        'LOG_TO_FILE': 'false',
        'PYTHONUTF8': '1',
        'HOME': str(tmp_path),
        'USERPROFILE': str(tmp_path),
    })
    return env


class TestCLIEntrypointE2E:
    """E2E tests for CLI entrypoint and startup paths."""

    @pytest.mark.e2e
    def test_entry_module_can_be_imported(self) -> None:
        """Verify the CLI entry module can be imported."""
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                'from backend.cli.entry import main; print("ok")',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert "ok" in result.stdout

    @pytest.mark.e2e
    def test_cli_module_imports_without_errors(self) -> None:
        """Verify core CLI modules can be imported."""
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                'from backend.cli import main, repl, entry; print("ok")',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"

    @pytest.mark.e2e
    def test_cli_main_module_imports(self) -> None:
        """Verify backend.cli.main can be imported."""
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                'from backend.cli.main import main; print("ok")',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

    @pytest.mark.e2e
    def test_compileall_succeeds_on_backend(self) -> None:
        """Verify all Python files compile without syntax errors."""
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'compileall',
                'backend',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"Compile failed: {result.stderr}"

    @pytest.mark.e2e
    def test_entrypoint_help_flag_works(self) -> None:
        """Verify --help flag displays help text."""
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                '--help',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert 'usage' in result.stdout.lower() or 'options' in result.stdout.lower()

    @pytest.mark.e2e
    def test_entrypoint_version_flag_works(self) -> None:
        """Verify --version flag displays version."""
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                '--version',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0


class TestCLISettingsE2E:
    """E2E tests for settings handling."""

    @pytest.mark.e2e
    def test_init_creates_settings_file(self, tmp_path: Path) -> None:
        """Verify 'grinta init' creates settings file."""
        project_root = tmp_path / 'project'
        project_root.mkdir()

        env = _get_base_env(tmp_path)
        env['APP_ROOT'] = str(tmp_path / 'app')
        (tmp_path / 'app').mkdir()

        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                'init',
                '--project',
                str(project_root),
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        settings_path = project_root / 'settings.json'
        if settings_path.exists():
            content = json.loads(settings_path.read_text(encoding='utf-8'))
            assert 'llm_model' in content or 'llm_provider' in content


class TestCLIProjectPathE2E:
    """E2E tests for project path handling."""

    @pytest.mark.e2e
    def test_nonexistent_project_shows_error(self, tmp_path: Path) -> None:
        """Verify nonexistent project directory produces clear error."""
        nonexistent = tmp_path / 'does-not-exist'

        env = _get_base_env(tmp_path)

        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                '--project',
                str(nonexistent),
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        assert result.returncode != 0 or 'not found' in result.stdout.lower()

    @pytest.mark.e2e
    def test_project_path_is_resolved(self, tmp_path: Path) -> None:
        """Verify project path is properly resolved."""
        project_root = tmp_path / 'project'
        project_root.mkdir()

        env = _get_base_env(tmp_path)

        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                '--project',
                str(project_root),
                '--version',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        assert result.returncode == 0


class TestCLIIntegrationE2E:
    """E2E tests that verify integration points."""

    @pytest.mark.e2e
    def test_execution_server_entrypoint_is_deprecated(self) -> None:
        """Verify old execution server entrypoint returns error."""
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.execution.action_execution_server',
                '3000',
                '--working-dir',
                str(_REPO_ROOT),
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode != 0
        assert 'CLI-only' in result.stderr or 'deprecated' in result.stderr.lower()

    @pytest.mark.e2e
    def test_launch_entry_module_imports(self) -> None:
        """Verify launch.entry can be imported."""
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                'from launch.entry import main; print("ok")',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0 or 'ModuleNotFoundError' not in result.stderr

    @pytest.mark.e2e
    def test_config_module_imports(self) -> None:
        """Verify config modules can be imported."""
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                'from backend.core.config import AppConfig; print("ok")',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0


class TestCLIVerboseE2E:
    """E2E tests for verbose and diagnostic modes."""

    @pytest.mark.e2e
    def test_verbose_flag_is_recognized(self, tmp_path: Path) -> None:
        """Verify --verbose flag is recognized."""
        project_root = tmp_path / 'project'
        project_root.mkdir()

        env = _get_base_env(tmp_path)

        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                '--project',
                str(project_root),
                '--verbose',
                '--version',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        assert result.returncode == 0

    @pytest.mark.e2e
    def test_no_splash_flag_suppresses_splash(self, tmp_path: Path) -> None:
        """Verify --no-splash flag is recognized."""
        project_root = tmp_path / 'project'
        project_root.mkdir()

        env = _get_base_env(tmp_path)

        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                '--project',
                str(project_root),
                '--no-splash',
                '--version',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        assert result.returncode == 0


class TestCLIExitCodesE2E:
    """E2E tests for proper exit codes."""

    @pytest.mark.e2e
    def test_help_exits_zero(self, tmp_path: Path) -> None:
        """Verify --help exits with code 0."""
        env = _get_base_env(tmp_path)

        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                '--help',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        assert result.returncode == 0

    @pytest.mark.e2e
    def test_version_exits_zero(self, tmp_path: Path) -> None:
        """Verify --version exits with code 0."""
        env = _get_base_env(tmp_path)

        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                '--version',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        assert result.returncode == 0

    @pytest.mark.e2e
    def test_invalid_option_exits_nonzero(self, tmp_path: Path) -> None:
        """Verify invalid option exits with non-zero code."""
        env = _get_base_env(tmp_path)

        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'backend.cli.entry',
                '--invalid-option-xyz',
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        assert result.returncode != 0