"""Task-level end-to-end regression for the CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_STUB_RUNNER = _REPO_ROOT / 'scripts' / 'smoke' / 'run_cli_with_stub.py'


def _write_app_settings(app_root: Path) -> None:
    app_root.mkdir(parents=True, exist_ok=True)
    settings = {
        'llm_provider': 'openai',
        'llm_model': 'openai/gpt-4.1',
        'llm_api_key': '${LLM_API_KEY}',
        'llm_base_url': '',
        'agent': {
            'Orchestrator': {
                'autonomy_level': 'balanced',
            },
        },
        'security': {
            'execution_profile': 'hardened_local',
            'enforce_security': True,
        },
    }
    (app_root / 'settings.json').write_text(
        json.dumps(settings, indent=2) + '\n',
        encoding='utf-8',
    )


@pytest.mark.integration
def test_launch_entry_completes_one_task_via_subprocess(tmp_path: Path) -> None:
    project_root = tmp_path / 'project'
    project_root.mkdir()
    (project_root / 'README.md').write_text(
        'CLI task regression target\n', encoding='utf-8'
    )

    app_root = tmp_path / 'app'
    _write_app_settings(app_root)

    env = os.environ.copy()
    env['LLM_API_KEY'] = 'sk-test-cli-task'
    env['LLM_MODEL'] = 'openai/gpt-4.1'
    env['GRINTA_NO_SPLASH'] = '1'
    env['LOG_TO_FILE'] = 'false'
    env['PYTHONUTF8'] = '1'
    env['GRINTA_AGENT_RUN_HARD_TIMEOUT_SECONDS'] = '90'
    env['APP_ROOT'] = str(app_root)
    env['HOME'] = str(tmp_path)
    env['USERPROFILE'] = str(tmp_path)
    existing_path = env.get('PYTHONPATH', '')
    path_parts = [str(_REPO_ROOT)]
    if existing_path:
        path_parts.append(existing_path)
    env['PYTHONPATH'] = os.pathsep.join(path_parts)

    result = subprocess.run(
        [
            sys.executable,
            str(_STUB_RUNNER),
            '--project',
            str(project_root),
            '--no-splash',
        ],
        input='Summarize README.md in one sentence.\n',
        text=True,
        capture_output=True,
        encoding='utf-8',
        errors='replace',
        cwd=_REPO_ROOT,
        env=env,
        timeout=300,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert 'Summarize README.md in one sentence.' in result.stdout
    assert 'Agent completed' in result.stdout
    assert 'Initialization failed' not in result.stdout
