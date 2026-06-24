"""Ensure ``rigour.yml`` exists before starting the Rigour MCP server.

``@rigour-labs/mcp`` calls ``loadConfig(cwd)`` on startup. If ``rigour.yml`` is
missing, upstream runs ``npx rigour init``, which fails on npm (there is no
``rigour`` executable — the CLI is ``@rigour-labs/cli``). Grinta runs the
correct CLI init before connecting so the MCP server never hits the broken path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from backend.core.logging.logger import app_logger as logger
from backend.core.workspace_resolution import get_effective_workspace_root

_RIGOUR_CLI_PACKAGE = '@rigour-labs/cli'


def _rigour_init_timeout_sec() -> float:
    raw = os.getenv('APP_RIGOUR_INIT_TIMEOUT_SEC', '90')
    try:
        timeout = float(raw)
        return timeout if timeout > 0 else 90.0
    except (TypeError, ValueError):
        return 90.0


def _rigour_workspace_root(env: dict[str, str] | None) -> Path | None:
    if env:
        raw = env.get('RIGOUR_CWD', '').strip()
        if raw:
            try:
                return Path(raw).expanduser().resolve()
            except OSError:
                pass
    got = get_effective_workspace_root()
    try:
        return got.resolve() if got is not None else None
    except OSError:
        return None


def _run_rigour_cli_init(workspace: Path) -> bool:
    """Run ``npx -y @rigour-labs/cli init`` in *workspace*. Return True on success."""
    npx = shutil.which('npx')
    if not npx:
        logger.warning(
            'Rigour CLI init skipped: ``npx`` not found on PATH; '
            'run `npx @rigour-labs/cli init` in the project before using Rigour MCP.'
        )
        return False

    cmd = [npx, '-y', _RIGOUR_CLI_PACKAGE, 'init']
    try:
        result = subprocess.run(
            cmd,
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=_rigour_init_timeout_sec(),
            check=False,
        )
    except OSError as exc:
        logger.warning('Rigour CLI init failed to start (%s): %s', cmd, exc)
        return False
    except subprocess.TimeoutExpired:
        logger.warning(
            'Rigour CLI init timed out after %.0fs in %s',
            _rigour_init_timeout_sec(),
            workspace,
        )
        return False

    rigour_yml = workspace / 'rigour.yml'
    if result.returncode == 0 and rigour_yml.is_file():
        return True

    detail = (result.stderr or result.stdout or '').strip()
    if len(detail) > 500:
        detail = detail[:500] + '...'
    logger.warning(
        'Rigour CLI init did not produce rigour.yml (exit=%s): %s',
        result.returncode,
        detail or '(no output)',
    )
    return False


def ensure_rigour_yml_for_mcp(env: dict[str, str] | None) -> None:
    """Ensure the workspace has a ``rigour.yml`` before starting Rigour MCP."""
    workspace = _rigour_workspace_root(env)
    if workspace is None:
        return

    rigour_yml = workspace / 'rigour.yml'
    if rigour_yml.is_file():
        return

    if _run_rigour_cli_init(workspace):
        logger.info(
            'Initialized Rigour via `npx -y %s init` at %s',
            _RIGOUR_CLI_PACKAGE,
            rigour_yml,
        )
