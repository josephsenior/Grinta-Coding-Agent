"""Fast integration smoke tests for published CLI entrypoints."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _base_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            'LLM_API_KEY': 'sk-test-smoke',
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


@pytest.mark.integration
def test_launch_entry_help_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, '-m', 'launch.entry', '--help'],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert 'usage' in result.stdout.lower() or 'options' in result.stdout.lower()


@pytest.mark.integration
def test_doctor_runs_with_minimal_env(tmp_path: Path) -> None:
    app_root = tmp_path / 'app'
    app_root.mkdir()
    env = _base_env(tmp_path)
    env['APP_ROOT'] = str(app_root)

    result = subprocess.run(
        [sys.executable, '-m', 'backend.cli.entry', 'doctor'],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )

    assert result.returncode in {0, 1}
    combined = f'{result.stdout}\n{result.stderr}'.lower()
    assert 'doctor' in combined or 'check' in combined or 'grinta' in combined
