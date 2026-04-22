"""Ensure a minimal ``rigour.yml`` exists before starting the Rigour MCP server.

``@rigour-labs/mcp`` calls ``loadConfig(cwd)`` on startup. If ``rigour.yml`` is
missing, upstream runs ``npx rigour init``, which fails on npm (there is no
``rigour`` executable — the CLI is ``@rigour-labs/cli``). Creating a small valid
config avoids that broken auto-init path.
"""

from __future__ import annotations

from pathlib import Path

from backend.core.logger import app_logger as logger
from backend.core.workspace_resolution import get_effective_workspace_root

# Same shape as @rigour-labs/mcp's own supervisor tests (ConfigSchema-compatible).
_MINIMAL_RIGOUR_YML = """version: 1
preset: api
gates:
  max_file_lines: 500
  forbid_todos: true
  required_files: []
ignore: []
"""


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


def ensure_minimal_rigour_yml_for_mcp(env: dict[str, str] | None) -> None:
    """If the workspace has no ``rigour.yml``, write a minimal one in place."""
    workspace = _rigour_workspace_root(env)
    if workspace is None:
        return
    rigour_yml = workspace / 'rigour.yml'
    if rigour_yml.is_file():
        return
    try:
        rigour_yml.write_text(_MINIMAL_RIGOUR_YML, encoding='utf-8')
        logger.info(
            'Created minimal %s so Rigour MCP can start (upstream `npx rigour init` is broken on npm).',
            rigour_yml,
        )
    except OSError as exc:
        logger.warning('Could not write minimal rigour.yml at %s: %s', rigour_yml, exc)
