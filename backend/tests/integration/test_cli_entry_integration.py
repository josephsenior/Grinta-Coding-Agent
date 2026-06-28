"""Integration smoke tests for the CLI entrypoint."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.integration
def test_action_execution_server_entrypoint_is_retired() -> None:
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'
    env['PYTHONPATH'] = str(_REPO_ROOT) + os.pathsep + env.get('PYTHONPATH', '')

    result = subprocess.run(
        [
            sys.executable,
            '-m',
            'backend.execution.server.action_execution_server',
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
