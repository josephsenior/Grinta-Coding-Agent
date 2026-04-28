"""Integration smoke tests for the CLI entrypoint."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

import backend.cli.repl as cli_repl
from backend.core.config import AppConfig
from backend.persistence.locations import get_project_local_data_root


_REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, width=100)


@pytest.mark.integration
def test_entry_main_launches_cli_repl_with_project_and_piped_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = AppConfig()
    config.get_llm_config().model = 'openai/gpt-4.1'

    repl = MagicMock()
    repl.run = AsyncMock()

    stdin = MagicMock()
    stdin.isatty.return_value = False
    stdin.read.return_value = 'queued task\n'

    sim_home = tmp_path / 'SIM_HOME'
    sim_home.mkdir()
    monkeypatch.setenv('HOME', str(sim_home))
    monkeypatch.setenv('USERPROFILE', str(sim_home))
    monkeypatch.delenv('PROJECT_ROOT', raising=False)

    with patch.object(sys, 'argv', ['grinta', '--project', str(tmp_path), '--no-splash']):
        with patch.object(sys, 'stdin', stdin):
            with patch('backend.cli.main._load_dotenv_early'):
                with patch('backend.cli.main._setup_logging'):
                    with patch('backend.core.logger.configure_file_logging'):
                        with patch(
                            'backend.core.config.load_app_config', return_value=config
                        ):
                            with patch(
                                'backend.cli.main.Console', return_value=_make_console()
                            ):
                                with patch.object(cli_repl, 'Repl', return_value=repl):
                                    with patch(
                                        'backend.cli.config_manager.needs_onboarding',
                                        return_value=False,
                                    ):
                                        with patch(
                                            'backend.cli.config_manager.ensure_default_model',
                                            return_value='openai/gpt-4.1',
                                        ):
                                            from backend.cli.entry import main

                                            main()

    resolved = str(tmp_path.resolve())
    assert os.environ['PROJECT_ROOT'] == resolved
    assert config.project_root == resolved
    assert config.local_data_root == get_project_local_data_root(tmp_path)
    assert config.get_agent_config(config.default_agent).cli_mode is True
    repl.queue_initial_input.assert_called_once_with('queued task\n')
    repl.run.assert_awaited_once()


@pytest.mark.integration
def test_launch_entry_runs_real_cli_session_via_subprocess(tmp_path: Path) -> None:
    project_root = tmp_path / 'project'
    project_root.mkdir()
    (project_root / 'README.md').write_text('cli smoke\n', encoding='utf-8')

    env = os.environ.copy()
    env['LLM_API_KEY'] = 'sk-test-cli-smoke'
    env['LLM_MODEL'] = 'openai/gpt-4.1'
    env['GRINTA_NO_SPLASH'] = '1'
    env['LOG_TO_FILE'] = 'false'
    env['PYTHONUTF8'] = '1'
    env['PYTHONPATH'] = str(_REPO_ROOT) + os.pathsep + env.get('PYTHONPATH', '')

    result = subprocess.run(
        [
            sys.executable,
            '-m',
            'launch.entry',
            '--project',
            str(project_root),
            '--no-splash',
        ],
        input='/help\n',
        text=True,
        capture_output=True,
        encoding='utf-8',
        errors='replace',
        cwd=_REPO_ROOT,
        env=env,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert 'Input tips' in result.stdout
    assert 'Quit grinta' in result.stdout


@pytest.mark.integration
def test_action_execution_server_entrypoint_is_retired() -> None:
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'
    env['PYTHONPATH'] = str(_REPO_ROOT) + os.pathsep + env.get('PYTHONPATH', '')

    result = subprocess.run(
        [
            sys.executable,
            '-m',
            'backend.execution.action_execution_server',
            '3000',
            '--working-dir',
            str(_REPO_ROOT),
        ],
        text=True,
        capture_output=True,
        encoding='utf-8',
        errors='replace',
        cwd=_REPO_ROOT,
        env=env,
        timeout=60,
        check=False,
    )

    assert result.returncode != 0
    assert 'CLI-only product' in result.stderr