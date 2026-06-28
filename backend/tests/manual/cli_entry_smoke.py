"""Manual CLI entry smoke check — not collected by pytest.

Run from repo root when you need to verify the real CLI launches:

    uv run python backend/tests/manual/cli_entry_smoke.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    project_root = _REPO_ROOT / '.cli_entry_smoke_project'
    project_root.mkdir(exist_ok=True)
    (project_root / 'README.md').write_text('cli smoke\n', encoding='utf-8')

    env = os.environ.copy()
    env.setdefault('LLM_API_KEY', 'sk-test-cli-smoke')
    env.setdefault('LLM_MODEL', 'openai/gpt-4.1')
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

    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        return result.returncode

    stdout = result.stdout
    if 'Slash' not in stdout or 'Commands' not in stdout or 'Quit grinta' not in stdout:
        print('Unexpected CLI output:', stdout, file=sys.stderr)
        return 1

    print('CLI entry smoke passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
