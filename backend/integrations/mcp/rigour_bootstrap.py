"""Ensure a minimal ``rigour.yml`` exists before starting the Rigour MCP server.

``@rigour-labs/mcp`` calls ``loadConfig(cwd)`` on startup. If ``rigour.yml`` is
missing, upstream runs ``npx rigour init``, which fails on npm (there is no
``rigour`` executable — the CLI is ``@rigour-labs/cli``) and scaffolds IDE
rules, hooks, and other project files.

Grinta writes only a tiny stub so MCP connect stays runtime-only. Users who want
full Rigour project setup run ``npx @rigour-labs/cli init`` themselves.
"""

from __future__ import annotations

from pathlib import Path

from backend.core.logging.logger import app_logger as logger
from backend.core.workspace_resolution import get_effective_workspace_root

# Enough for @rigour-labs/mcp to load; no IDE rules, hooks, or preset detection.
MINIMAL_RIGOUR_YML = """\
version: 1
ignore:
  - .git/**
  - node_modules/**
  - __pycache__/**
  - venv/**
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


def write_minimal_rigour_yml(workspace: Path) -> bool:
    """Write a minimal ``rigour.yml`` in *workspace*. Return True on success."""
    rigour_yml = workspace / 'rigour.yml'
    if rigour_yml.is_file():
        return True
    try:
        rigour_yml.write_text(MINIMAL_RIGOUR_YML, encoding='utf-8')
    except OSError as exc:
        logger.warning('Failed to write minimal rigour.yml at %s: %s', rigour_yml, exc)
        return False
    return True


def ensure_rigour_yml_for_mcp(env: dict[str, str] | None) -> None:
    """Ensure the workspace has a minimal ``rigour.yml`` before starting Rigour MCP."""
    workspace = _rigour_workspace_root(env)
    if workspace is None:
        return

    rigour_yml = workspace / 'rigour.yml'
    if rigour_yml.is_file():
        return

    if write_minimal_rigour_yml(workspace):
        logger.info(
            'Wrote minimal rigour.yml at %s (run `npx @rigour-labs/cli init` for full setup)',
            rigour_yml,
        )
